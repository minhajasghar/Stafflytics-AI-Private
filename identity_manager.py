"""
Stafflytics AI - Identity-Centric Persistent Tracking & Re-ID Engine
=====================================================================
Architecture:
1. Identities are the primary source of truth (stored in memory, backed by DB).
2. Tracks (ByteTrack track_id) are temporary pointers to identities.
3. Hungarian assignment (scipy linear_sum_assignment) pairs detections with identities
   using Body Appearance Re-ID as primary cue, plus spatial gating and optional face bonus.
4. Strict 1-to-1 exclusivity: one identity = one track. Moved persons take their identity
   with them; stale ghost boxes at old positions are immediately evicted.
5. Provisional tracks (Provisional-TID) prevent minting spurious Customer numbers.
6. Once locked, identities never drop to 'Unknown'.
"""

import os
import time
import pickle
import threading
import numpy as np
import cv2
from scipy.optimize import linear_sum_assignment
import database

# ---------------------------------------------------------------------------
# Tuned Thresholds for High-Angle Ceiling Camera
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    # Match Thresholds
    "BODY_REID_THRESHOLD": 0.72,           # Primary cue: Appearance vector cosine similarity
    "FACE_MATCH_THRESHOLD": 0.34,          # Bonus cue: ArcFace cosine similarity when face >= 45px
    "FUSED_MATCH_THRESHOLD": 0.65,         # Combined fused threshold
    "SPATIAL_GATE_PIXELS": 450.0,          # Maximum pixel center jump for short-time association
    
    # Time Windows
    "RECENTLY_LOST_WINDOW_SEC": 60.0,      # Retain recently lost identities for re-attachment
    "CUSTOMER_CONFIRMATION_WINDOW_SEC": 10.0, # Must be stable 10s before minting Customer number
    "CONFIRMATION_MIN_HITS": 12,           # Minimum detection hits required before confirmation
    "VERIFICATION_INTERVAL_FRAMES": 25,    # Re-verify and refresh appearance periodically
    
    # Gallery & Drift Protection
    "MAX_GALLERY_SIZE": 5,                 # Maximum embeddings kept per identity
    "GALLERY_UPDATE_MIN_CONF": 0.78,       # Only update gallery when appearance match is very high
    "GALLERY_UPDATE_MIN_SHARPNESS": 18.0,  # Minimum Laplacian variance for face updates
    "CUSTOMER_RETENTION_DAYS": 30          # Customer retention window
}


def compute_laplacian_sharpness(img_bgr):
    """Computes Laplacian variance for image sharpness."""
    if img_bgr is None or img_bgr.size == 0:
        return 0.0
    try:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return 0.0


def extract_body_reid_vector(body_crop):
    """
    Standardized 128-dimensional spatial-color and texture appearance vector.
    Primary cue for overhead CCTV where faces are small, turned, or occluded.
    Normalized to unit L2 length (dot product = cosine similarity).
    """
    if body_crop is None or body_crop.size == 0:
        return None
    try:
        h_orig, w_orig = body_crop.shape[:2]
        if h_orig < 40 or w_orig < 20:
            return None
            
        img = cv2.resize(body_crop, (128, 256))
        h, w = img.shape[:2]
        
        # 3 Vertical Body Zones (Head/Shoulders, Torso/Shirt, Lower Body)
        # Weight Torso/Shirt (upper-body clothing) heavily as primary cue for seated overhead CCTV
        zones = [
            img[0:int(h * 0.25), :],
            img[int(h * 0.25):int(h * 0.65), :],
            img[int(h * 0.65):h, :]
        ]
        zone_weights = [0.25, 0.55, 0.15]
        
        features = []
        for zone, w_z in zip(zones, zone_weights):
            if zone.size == 0:
                features.extend([0.0] * 38)
                continue
            hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
            lab = cv2.cvtColor(zone, cv2.COLOR_BGR2LAB)
            
            # HSV Histograms: H(16), S(8), V(8) = 32 bins
            h_hist = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()
            s_hist = cv2.calcHist([hsv], [1], None, [8], [0, 256]).flatten()
            v_hist = cv2.calcHist([hsv], [2], None, [8], [0, 256]).flatten()
            
            # Lab Histograms: a(3), b(3) = 6 bins for illumination invariance
            a_hist = cv2.calcHist([lab], [1], None, [3], [0, 256]).flatten()
            b_hist = cv2.calcHist([lab], [2], None, [3], [0, 256]).flatten()
            
            zone_feat = np.concatenate([h_hist, s_hist, v_hist, a_hist, b_hist])
            zone_norm = np.linalg.norm(zone_feat)
            if zone_norm > 0:
                zone_feat = (zone_feat / zone_norm) * w_z
            features.extend(zone_feat)
            
        # Global texture gradient energy (Sobel on grayscale) = 14 bins
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag, _ = cv2.cartToPolar(gx, gy)
        mag_hist = cv2.calcHist([mag.astype(np.uint8)], [0], None, [14], [0, 256]).flatten()
        mag_norm = np.linalg.norm(mag_hist)
        if mag_norm > 0:
            mag_hist = (mag_hist / mag_norm) * 0.05
        features.extend(mag_hist)
        
        vec = np.array(features, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec
    except Exception:
        return None


class PersistentIdentityManager:
    """
    Identity-Centric Persistent Tracking & Re-ID Engine.
    Source of truth is Identity, not track_id or screen position.
    """

    def __init__(self, config=None):
        self.lock = threading.RLock()
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)

        # Global Persistent Identity Store: identity_id -> IdentityDict
        # {
        #   "id": str, "type": "staff"|"customer", "label": "Staff 1 (Name)",
        #   "numeric_index": int, "face_gallery": [vec, ...], "body_gallery": [vec, ...],
        #   "last_seen": float, "last_box": [x1, y1, x2, y2], "bound_track_id": int|None
        # }
        self.identities = {}

        # Bidirectional Binding Maps (Strict 1-to-1)
        self.track_to_identity = {}  # track_id (int) -> identity_id (str)
        self.identity_to_track = {}  # identity_id (str) -> track_id (int)

        # Provisional Candidates: track_id -> dict
        # {
        #   "first_seen": float, "last_seen": float, "hits": int,
        #   "body_gallery": list, "best_face": vec|None, "last_box": list
        # }
        self.provisional_tracks = {}

        # Recently Lost Identities Buffer: identity_id -> dict
        # Held for RECENTLY_LOST_WINDOW_SEC for instant re-attachment
        self.recently_lost = {}

        # Tracks evicted because their identity moved to a new detection
        self.evicted_tracks = set()

        # Enrollment mode flag (manual staff capture)
        self.enrollment_mode_active = False
        self.enrollment_target_track = None

        # Load existing identities from database
        self.load_from_database()

    # -----------------------------------------------------------------------
    # Database Persistence & Initialization
    # -----------------------------------------------------------------------
    def load_from_database(self):
        """Loads all stored identities and galleries from database into memory."""
        with self.lock:
            try:
                self._sync_legacy_staff_to_identities()

                id_rows = database.get_all_identities()
                embeddings = database.get_identity_embeddings()

                emb_map = {}
                for emb in embeddings:
                    iid = emb["identity_id"]
                    kind = emb["kind"]
                    raw_vec = emb["vector"]
                    try:
                        vec = pickle.loads(raw_vec)
                    except Exception:
                        vec = np.frombuffer(raw_vec, dtype=np.float32)
                    if isinstance(vec, np.ndarray) and vec.size > 0:
                        norm = np.linalg.norm(vec)
                        if norm > 0:
                            vec = vec / norm
                        emb_map.setdefault(iid, {}).setdefault(kind, []).append(vec)

                self.identities.clear()
                for r in id_rows:
                    iid = r["id"]
                    itype = r["type"]
                    label = r["label"]
                    n_idx = r["numeric_index"]

                    stored_embs = emb_map.get(iid, {})
                    f_list = list(stored_embs.get("face", []))
                    b_list = list(stored_embs.get("body", []))

                    self.identities[iid] = {
                        "id": iid,
                        "type": itype,
                        "label": label,
                        "numeric_index": n_idx,
                        "face_gallery": f_list,
                        "body_gallery": b_list,
                        "last_seen": time.time(),
                        "last_box": None,
                        "bound_track_id": None
                    }

                print(f"[IDENTITY MANAGER] Preloaded {len(self.identities)} persistent identities "
                      f"({sum(1 for v in self.identities.values() if v['type'] == 'staff')} Staff, "
                      f"{sum(1 for v in self.identities.values() if v['type'] == 'customer')} Customers) from DB.")
            except Exception as e:
                print(f"[IDENTITY MANAGER ERROR] Failed to load identities from DB: {e}")

    def _sync_legacy_staff_to_identities(self):
        """Maps staff from the 'staff' table into the persistent identity store."""
        try:
            staff_rows = database.get_all_staff()
            for s in staff_rows:
                s_id, s_name, s_role, shift_time, rate, enc_blob = s[:6]
                iid = f"staff_{s_id}"
                existing = database.get_identity(iid)
                if not existing:
                    idx = database.get_next_identity_index("staff")
                    label = f"Staff {idx} ({s_name})" if s_name else f"Staff {idx}"
                    database.save_identity(iid, "staff", label, idx)
                else:
                    idx = existing["numeric_index"]
                    if s_name and ("(" not in existing["label"]):
                        label = f"Staff {idx} ({s_name})"
                        database.save_identity(iid, "staff", label, idx)

                if enc_blob:
                    try:
                        raw = pickle.loads(enc_blob)
                        enc_list = raw if isinstance(raw, list) else [raw]
                        for e in enc_list:
                            if e is not None:
                                database.save_identity_embedding(iid, "face", pickle.dumps(e), 1.0)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[SYNC STAFF ERROR] {e}")

    # -----------------------------------------------------------------------
    # Global Hungarian Assignment (Identity-Centric Matching)
    # -----------------------------------------------------------------------
    def assign_detections(self, detections, current_time=None, frame_shape=(1080, 1920)):
        """
        Global Bipartite Matching (Hungarian Algorithm) between current detections
        and persistent identities (both active and recently lost).

        detections: list of dicts:
          [{"track_id": int, "box": [x1, y1, x2, y2], "body_crop": np.ndarray,
            "face_crop": np.ndarray, "face_enc": np.ndarray|None}, ...]

        Returns:
          assigned_results: dict[track_id -> {"label": str, "color": str, "identity_id": str, "is_locked": bool}]
          evicted_track_ids: list[int] (tracks killed because their identity moved)
        """
        if current_time is None:
            current_time = time.time()

        with self.lock:
            # 1. Clean expired recently_lost buffer (> RECENTLY_LOST_WINDOW_SEC)
            lost_win = self.config["RECENTLY_LOST_WINDOW_SEC"]
            expired_lost = [k for k, v in self.recently_lost.items() if (current_time - v["lost_at"]) > lost_win]
            for k in expired_lost:
                del self.recently_lost[k]

            assigned_results = {}
            newly_evicted = set()

            if not detections:
                return assigned_results, list(self.evicted_tracks)

            # Pre-extract body appearance vectors for incoming detections
            for det in detections:
                det["body_vec"] = extract_body_reid_vector(det.get("body_crop"))

            # Build candidate identities pool: all known identities (staff first, then customers)
            # Include both active identities and recently lost ones
            candidate_ids = list(self.identities.keys())
            matched_dets = set()
            matched_iids = set()

            if candidate_ids:
                # Build Cost Matrix between M detections and N identities
                num_dets = len(detections)
                num_ids = len(candidate_ids)
                cost_matrix = np.ones((num_dets, num_ids), dtype=np.float32)

                body_thresh = self.config["BODY_REID_THRESHOLD"]
                face_thresh = self.config["FACE_MATCH_THRESHOLD"]

                for i, det in enumerate(detections):
                    d_box = det["box"]
                    d_center = ((d_box[0] + d_box[2]) / 2.0, (d_box[1] + d_box[3]) / 2.0)
                    d_body = det.get("body_vec")
                    d_face = det.get("face_enc")

                    for j, iid in enumerate(candidate_ids):
                        id_data = self.identities[iid]
                        b_gallery = id_data.get("body_gallery", [])
                        f_gallery = id_data.get("face_gallery", [])
                        last_box = id_data.get("last_box")

                        # Primary Cue: Body Appearance Cosine Distance
                        body_sim = -1.0
                        if d_body is not None and b_gallery:
                            sims = [float(np.dot(d_body, g)) for g in b_gallery if g is not None]
                            if sims:
                                body_sim = max(sims)

                        # Bonus Cue: Face Cosine Distance
                        face_sim = -1.0
                        if d_face is not None and f_gallery:
                            sims_f = [float(np.dot(d_face, g)) for g in f_gallery if g is not None]
                            if sims_f:
                                face_sim = max(sims_f)

                        # Spatial Gating
                        spatial_penalty = 0.0
                        if last_box is not None:
                            l_center = ((last_box[0] + last_box[2]) / 2.0, (last_box[1] + last_box[3]) / 2.0)
                            dist_px = np.hypot(d_center[0] - l_center[0], d_center[1] - l_center[1])
                            spatial_penalty = min(0.20, dist_px / 2000.0)

                        # Combined Cost (lower is better, match threshold <= 0.32)
                        if face_sim >= face_thresh and body_sim >= body_thresh:
                            fused_sim = 0.55 * face_sim + 0.45 * body_sim
                            cost = max(0.0, 1.0 - fused_sim)
                        elif body_sim >= body_thresh:
                            cost = max(0.0, 1.0 - body_sim) + (0.05 * spatial_penalty)
                        elif face_sim >= face_thresh:
                            cost = max(0.0, 1.0 - face_sim)
                        elif face_sim > 0.30 and body_sim > 0.65:
                            fused_sim = 0.50 * face_sim + 0.50 * body_sim
                            cost = max(0.0, 1.0 - fused_sim) + (0.10 * spatial_penalty)
                        else:
                            cost = 1.0

                        cost_matrix[i, j] = cost

                # Solve Hungarian matching
                row_ind, col_ind = linear_sum_assignment(cost_matrix)

                for r, c in zip(row_ind, col_ind):
                    cost = cost_matrix[r, c]
                    # Accept match if appearance distance is within threshold (cost <= 0.32, i.e., similarity >= 0.68)
                    if cost <= 0.32:
                        det = detections[r]
                        tid = det["track_id"]
                        iid = candidate_ids[c]
                        id_data = self.identities[iid]

                        matched_dets.add(r)
                        matched_iids.add(iid)

                        # 1-to-1 Exclusivity Check: If this identity was bound to another track, MOVE it!
                        old_tid = self.identity_to_track.get(iid)
                        if old_tid is not None and old_tid != tid:
                            print(f"[IDENTITY MOVED] Moved Identity '{id_data['label']}' ({iid}) "
                                  f"from stale Track #{old_tid} -> new Track #{tid} (appearance cost: {cost:.3f}).")
                            self.track_to_identity.pop(old_tid, None)
                            newly_evicted.add(old_tid)

                        # Bind identity to new track
                        self.track_to_identity[tid] = iid
                        self.identity_to_track[iid] = tid
                        id_data["bound_track_id"] = tid
                        id_data["last_seen"] = current_time
                        id_data["last_box"] = det["box"]

                        # If identity was in recently_lost, remove it
                        self.recently_lost.pop(iid, None)

                        # Update appearance gallery with high-quality observation
                        self._maybe_update_gallery(iid, det.get("face_enc"), det.get("body_vec"))

                        itype = id_data["type"]
                        color = "#3b82f6" if itype == "staff" else "#eab308"
                        assigned_results[tid] = {
                            "label": id_data["label"],
                            "color": color,
                            "identity_id": iid,
                            "is_locked": True,
                            "type": itype
                        }

            # ---------------------------------------------------------------
            # Handle Unmatched Detections: Provisional Tracking (No Blind Minting!)
            # ---------------------------------------------------------------
            for i, det in enumerate(detections):
                if i in matched_dets:
                    continue

                tid = det["track_id"]

                # If track was already bound to an identity that didn't match this frame,
                # keep sticky lock (never drop to Unknown if temporarily occluded/turned)
                if tid in self.track_to_identity:
                    iid = self.track_to_identity[tid]
                    id_data = self.identities[iid]
                    id_data["last_seen"] = current_time
                    id_data["last_box"] = det["box"]
                    itype = id_data["type"]
                    color = "#3b82f6" if itype == "staff" else "#eab308"
                    assigned_results[tid] = {
                        "label": id_data["label"],
                        "color": color,
                        "identity_id": iid,
                        "is_locked": True,
                        "type": itype
                    }
                    continue

                # Provisional Candidate Processing
                cand = self.provisional_tracks.setdefault(tid, {
                    "first_seen": current_time,
                    "last_seen": current_time,
                    "hits": 0,
                    "body_vec": None,
                    "face_enc": None,
                    "last_box": det["box"]
                })
                cand["last_seen"] = current_time
                cand["hits"] += 1
                cand["last_box"] = det["box"]
                if det.get("body_vec") is not None and cand["body_vec"] is None:
                    cand["body_vec"] = det["body_vec"]
                if det.get("face_enc") is not None and cand["face_enc"] is None:
                    cand["face_enc"] = det["face_enc"]

                duration = current_time - cand["first_seen"]
                confirm_win = self.config["CUSTOMER_CONFIRMATION_WINDOW_SEC"]
                min_hits = self.config["CONFIRMATION_MIN_HITS"]

                # Staff Enrollment Override
                if self.enrollment_mode_active and (self.enrollment_target_track in [None, tid]):
                    new_staff_id, new_staff_label = self._create_new_identity("staff", cand["face_enc"], cand["body_vec"])
                    self.track_to_identity[tid] = new_staff_id
                    self.identity_to_track[new_staff_id] = tid
                    self.enrollment_mode_active = False
                    self.enrollment_target_track = None
                    self.provisional_tracks.pop(tid, None)
                    print(f"[IDENTITY ENROLLED] *** Enrolled Track #{tid} as '{new_staff_label}' ({new_staff_id}) ***")
                    assigned_results[tid] = {
                        "label": new_staff_label, "color": "#3b82f6", "identity_id": new_staff_id,
                        "is_locked": True, "type": "staff"
                    }
                    continue

                # Check if provisional candidate can now be safely minted as a new Customer
                if duration >= confirm_win and cand["hits"] >= min_hits:
                    # Final re-check against ALL identities before minting to prevent duplicate
                    recheck_match = self._find_best_appearance_match(cand["body_vec"], cand["face_enc"])
                    if recheck_match is not None:
                        # Found existing identity: MERGE provisional track into existing identity!
                        existing_iid, sim_score = recheck_match
                        id_data = self.identities[existing_iid]
                        print(f"[PROVISIONAL MERGE] Merged Provisional Track #{tid} into existing '{id_data['label']}' "
                              f"({existing_iid}) via appearance similarity ({sim_score:.3f}).")
                        self.track_to_identity[tid] = existing_iid
                        self.identity_to_track[existing_iid] = tid
                        id_data["bound_track_id"] = tid
                        id_data["last_seen"] = current_time
                        self.provisional_tracks.pop(tid, None)
                        itype = id_data["type"]
                        color = "#3b82f6" if itype == "staff" else "#eab308"
                        assigned_results[tid] = {
                            "label": id_data["label"], "color": color, "identity_id": existing_iid,
                            "is_locked": True, "type": itype
                        }
                    else:
                        # Genuinely new unique customer: mint atomic Customer ID
                        new_cust_id, new_cust_label = self._create_new_identity("customer", cand["face_enc"], cand["body_vec"])
                        self.track_to_identity[tid] = new_cust_id
                        self.identity_to_track[new_cust_id] = tid
                        self.provisional_tracks.pop(tid, None)
                        print(f"[IDENTITY MINTED] *** Minted '{new_cust_label}' ({new_cust_id}) for Track #{tid} "
                              f"(Reason: Stable {duration:.1f}s, hits={cand['hits']}, unmatched across gallery) ***")
                        assigned_results[tid] = {
                            "label": new_cust_label, "color": "#eab308", "identity_id": new_cust_id,
                            "is_locked": True, "type": "customer"
                        }
                else:
                    # Stays provisional: NOT displayed as a numbered Customer!
                    assigned_results[tid] = {
                        "label": f"Provisional-T{tid}",
                        "color": "#94a3b8",
                        "identity_id": f"provisional_{tid}",
                        "is_locked": False,
                        "type": "provisional"
                    }

            self.evicted_tracks.update(newly_evicted)
            return assigned_results, list(newly_evicted)

    def _process_all_as_provisional(self, detections, current_time):
        """Fallback when gallery is completely empty."""
        results = {}
        for det in detections:
            tid = det["track_id"]
            results[tid] = {
                "label": f"Provisional-T{tid}",
                "color": "#94a3b8",
                "identity_id": f"provisional_{tid}",
                "is_locked": False,
                "type": "provisional"
            }
        return results, []

    @property
    def active_locks(self):
        """Backward-compatible mapping track_id -> lock metadata dict."""
        locks = {}
        with self.lock:
            for tid, iid in self.track_to_identity.items():
                ident = self.identities.get(iid)
                if ident:
                    locks[tid] = {
                        "label": ident["label"],
                        "type": ident["type"],
                        "identity_id": iid,
                        "numeric_index": ident.get("numeric_index", 1),
                        "confidence": 0.95,
                        "last_verified_frame": 0
                    }
        return locks

    def _find_best_appearance_match(self, body_vec, face_enc):
        """Scans all identities (active and recently lost) for an appearance match."""
        if body_vec is None and face_enc is None:
            return None
        best_id = None
        best_sim = -1.0
        
        all_sources = dict(self.identities)
        for r_id, r_data in self.recently_lost.items():
            if r_id not in all_sources:
                all_sources[r_id] = r_data

        for iid, id_data in all_sources.items():
            b_gal = id_data.get("body_gallery", [])
            f_gal = id_data.get("face_gallery", [])
            b_sim = max([float(np.dot(body_vec, g)) for g in b_gal]) if (body_vec is not None and b_gal) else -1.0
            f_sim = max([float(np.dot(face_enc, g)) for g in f_gal]) if (face_enc is not None and f_gal) else -1.0

            if b_sim >= self.config["BODY_REID_THRESHOLD"] and b_sim > best_sim:
                best_sim = b_sim
                best_id = iid
            elif f_sim >= self.config["FACE_MATCH_THRESHOLD"] and f_sim > best_sim:
                best_sim = f_sim
                best_id = iid
        if best_id is not None:
            return best_id, best_sim
        return None

    # -----------------------------------------------------------------------
    # Track Drop & Eviction
    # -----------------------------------------------------------------------
    def handle_track_lost(self, track_id):
        """Called when ByteTrack permanently drops a track."""
        current_time = time.time()
        with self.lock:
            self.provisional_tracks.pop(track_id, None)
            iid = self.track_to_identity.pop(track_id, None)
            if iid:
                self.identity_to_track.pop(iid, None)
                id_data = self.identities.get(iid)
                if id_data:
                    id_data["bound_track_id"] = None
                    self.recently_lost[iid] = {
                        "identity_id": iid,
                        "label": id_data["label"],
                        "type": id_data["type"],
                        "lost_at": current_time,
                        "last_box": id_data.get("last_box"),
                        "face_gallery": list(id_data.get("face_gallery", [])),
                        "body_gallery": list(id_data.get("body_gallery", []))
                    }
                    print(f"[IDENTITY RELEASED] Track #{track_id} dropped. Identity '{id_data['label']}' ({iid}) "
                          f"moved to recently_lost buffer (60s grace).")

    # -----------------------------------------------------------------------
    # Identity Creation & Gallery Updates
    # -----------------------------------------------------------------------
    def _create_new_identity(self, itype, face_embedding=None, body_reid_vec=None):
        """Atomically mints next identity in database and in-memory store."""
        numeric_idx = database.get_next_identity_index(itype)
        prefix = "Staff" if itype == "staff" else "Customer"
        label = f"{prefix} {numeric_idx}"
        identity_id = f"{itype}_{numeric_idx}"

        database.save_identity(identity_id, itype, label, numeric_idx)

        f_list = []
        b_list = []
        if face_embedding is not None:
            f_list.append(face_embedding)
            database.save_identity_embedding(identity_id, "face", pickle.dumps(face_embedding), 1.0)
        if body_reid_vec is not None:
            b_list.append(body_reid_vec)
            database.save_identity_embedding(identity_id, "body", pickle.dumps(body_reid_vec), 1.0)

        self.identities[identity_id] = {
            "id": identity_id,
            "type": itype,
            "label": label,
            "numeric_index": numeric_idx,
            "face_gallery": f_list,
            "body_gallery": b_list,
            "last_seen": time.time(),
            "last_box": None,
            "bound_track_id": None
        }
        return identity_id, label

    def _maybe_update_gallery(self, identity_id, face_embedding, body_reid_vec):
        """Enriches appearance gallery with high-confidence observations (drift protected)."""
        if identity_id not in self.identities:
            return
        id_data = self.identities[identity_id]
        max_size = self.config["MAX_GALLERY_SIZE"]

        if body_reid_vec is not None:
            b_gal = id_data["body_gallery"]
            # Only add distinct angle/pose (similarity between 0.75 and 0.94)
            sims = [float(np.dot(body_reid_vec, g)) for g in b_gal]
            is_redundant = any(s > 0.94 for s in sims)
            if not is_redundant:
                b_gal.append(body_reid_vec)
                if len(b_gal) > max_size:
                    b_gal.pop(0)
                database.save_identity_embedding(identity_id, "body", pickle.dumps(body_reid_vec), 1.0)
                database.prune_identity_embeddings(identity_id, "body", max_size)

        if face_embedding is not None:
            f_gal = id_data["face_gallery"]
            sims_f = [float(np.dot(face_embedding, g)) for g in f_gal]
            is_redundant_f = any(s > 0.92 for s in sims_f)
            if not is_redundant_f:
                f_gal.append(face_embedding)
                if len(f_gal) > max_size:
                    f_gal.pop(0)
                database.save_identity_embedding(identity_id, "face", pickle.dumps(face_embedding), 1.0)
                database.prune_identity_embeddings(identity_id, "face", max_size)

    # -----------------------------------------------------------------------
    # Manual Re-Assignment & Enrollment API
    # -----------------------------------------------------------------------
    def assign_track_to_identity(self, track_id, identity_id, body_crop=None, face_crop=None):
        """Manually binds track_id to a specific identity_id and captures body ReID."""
        with self.lock:
            if identity_id not in self.identities:
                self.load_from_database()
            if identity_id not in self.identities:
                if f"staff_{identity_id}" in self.identities:
                    identity_id = f"staff_{identity_id}"
                else:
                    return False, f"Identity {identity_id} not found"

            id_data = self.identities[identity_id]
            label = id_data["label"]
            current_time = time.time()

            body_vec = extract_body_reid_vector(body_crop) if body_crop is not None else None
            if body_vec is not None:
                self._maybe_update_gallery(identity_id, None, body_vec)

            # Evict old track if another track had this identity
            old_tid = self.identity_to_track.get(identity_id)
            if old_tid and old_tid != track_id:
                self.track_to_identity.pop(old_tid, None)
                self.evicted_tracks.add(old_tid)

            self.track_to_identity[track_id] = identity_id
            self.identity_to_track[identity_id] = track_id
            id_data["bound_track_id"] = track_id
            id_data["last_seen"] = current_time

            self.provisional_tracks.pop(track_id, None)
            database.update_identity_last_seen(identity_id)
            database.log_sighting(identity_id)
            print(f"[MANUAL BIND] Manually bound Track #{track_id} -> '{label}' ({identity_id})")
            return True, label

    def process_track_observation(self, track_id, box, frame_count, face_embedding=None, body_crop=None, face_crop=None, current_zone="Main Hall"):
        """Background observation processor for gallery enrichment and staff matching."""
        with self.lock:
            # Staff Enrollment Override
            if self.enrollment_mode_active and (self.enrollment_target_track in [None, track_id]):
                body_vec = extract_body_reid_vector(body_crop) if body_crop is not None else None
                new_staff_id, new_staff_label = self._create_new_identity("staff", face_embedding, body_vec)
                self.track_to_identity[track_id] = new_staff_id
                self.identity_to_track[new_staff_id] = track_id
                self.enrollment_mode_active = False
                self.enrollment_target_track = None
                self.provisional_tracks.pop(track_id, None)
                print(f"[IDENTITY ENROLLED] *** Enrolled Track #{track_id} as '{new_staff_label}' ({new_staff_id}) ***")
                return new_staff_label, "#3b82f6", new_staff_id, True

            det = {
                "track_id": track_id,
                "box": box or [0, 0, 100, 100],
                "body_crop": body_crop,
                "face_crop": face_crop,
                "face_enc": face_embedding
            }
            assigned, _ = self.assign_detections([det])
            res = assigned.get(track_id, {})
            label = res.get("label", "Unknown")
            return label, res.get("color", "#94a3b8"), res.get("identity_id"), res.get("is_locked", False)

    def enable_enrollment_mode(self, target_track_id=None):
        with self.lock:
            self.enrollment_mode_active = True
            self.enrollment_target_track = target_track_id
            print(f"[IDENTITY ENROLLMENT] Enrollment mode ENABLED (target: {target_track_id or 'next clear track'})")

    def disable_enrollment_mode(self):
        with self.lock:
            self.enrollment_mode_active = False
            self.enrollment_target_track = None
            print("[IDENTITY ENROLLMENT] Enrollment mode DISABLED")


# Singleton Instance
identity_manager = PersistentIdentityManager()
