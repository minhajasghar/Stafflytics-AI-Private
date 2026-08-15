import cv2
import numpy as np
import os
import time
import database
import pickle
import queue
import threading

# YOLO and face_recognition moved inside for lazy loading
model = None
model_loading_active = False


def _start_model_load():
    """Start loading the YOLO model in a background thread (idempotent).

    Loads once; safe to call repeatedly before or after the model is ready.
    Used by process_frame (lazy) and VisionEngine.warmup (eager at startup).
    """
    global model, model_loading_active
    if model is not None or model_loading_active:
        return
    model_loading_active = True

    def load():
        global model, model_loading_active
        try:
            from ultralytics import YOLO
            import torch
            base_dir = os.path.abspath(os.path.dirname(__file__))
            model_path = os.path.join(base_dir, 'models', 'yolov8n-pose.pt')
            print(f"[AI] Attempting to load YOLO model from: {model_path}")
            if os.path.exists(model_path):
                device = 'cpu' if not torch.cuda.is_available() else 0
                model = YOLO(model_path)
                model.to(device)
                print(f"[AI] Background Model Load Complete. Running on {device}")
            else:
                print(f"[AI ERROR] YOLO model file does not exist at {model_path}!")
        except Exception as e:
            import traceback
            print(f"[AI CRITICAL ERROR] Lazy load failed: {e}")
            traceback.print_exc()
        finally:
            model_loading_active = False

    import threading
    threading.Thread(target=load, daemon=True).start()
face_rec_lock = threading.Lock()


# ---------------------------------------------------------------------------
# OpenCV face recognition backend (YuNet detection + SFace recognition).
# Replaces the broken dlib/face_recognition install (rogue dlib 19.24.99).
# Embeds are 128-d float vectors; normalized to unit length so matching is a
# cosine similarity (dot product). Stored in DB via pickle like before.
# ---------------------------------------------------------------------------
_face_detector = None
_face_recognizer = None
_face_models_loaded = False

# SFace cosine-similarity thresholds (same person is typically > 0.5).
FACE_STAFF_STRONG = 0.45   # immediate staff match
FACE_STAFF_RELAXED = 0.35  # quick / last-chance staff check
FACE_CUSTOMER = 0.45       # known customer match


def _load_face_models():
    """Load YuNet detector + SFace recognizer ONNX models (idempotent)."""
    global _face_detector, _face_recognizer, _face_models_loaded
    if _face_models_loaded:
        return True
    base = os.path.abspath(os.path.dirname(__file__))
    yunet = os.path.join(base, 'face_models', 'face_detection_yunet_2023mar.onnx')
    sface = os.path.join(base, 'face_models', 'face_recognition_sface_2021oct.onnx')
    if not (os.path.exists(yunet) and os.path.exists(sface)):
        print(f"[AI ERROR] Face models missing: {yunet} / {sface}")
        return False
    try:
        _face_detector = cv2.FaceDetectorYN.create(yunet, "", (320, 320), 0.6, 0.3, 50)
        _face_recognizer = cv2.FaceRecognizerSF.create(sface, "")
        _face_models_loaded = True
        print("[AI] OpenCV face models loaded (YuNet + SFace).")
        return True
    except Exception as e:
        print(f"[AI ERROR] Failed to load face models: {e}")
        return False


def _detect_face_box(bgr):
    """Return the largest detected face (all 15 elements including landmarks) in a BGR image, or None."""
    if bgr is None or bgr.size == 0:
        return None
    if not _load_face_models():
        return None
    h, w = bgr.shape[:2]
    det = _face_detector
    try:
        det.setInputSize((w, h))
        result = det.detect(bgr)
        # result is a tuple: (retval, faces) where faces is ndarray
        faces = result[1] if isinstance(result, tuple) else result
        if faces is None or getattr(faces, 'ndim', 0) != 2 or len(faces) == 0:
            return None
        # Maximize width * height (f[2] * f[3])
        best = max(faces, key=lambda f: f[2] * f[3])
        return best.copy()
    except Exception as e:
        print(f"[AI ERROR] YuNet detect failed: {e}")
        return None


def _encode_face(bgr):
    """Detect the largest face in a BGR image and return a normalized 128-d
    SFace embedding, or None when no face is found."""
    face = _detect_face_box(bgr)
    if face is None:
        return None
    try:
        aligned = _face_recognizer.alignCrop(bgr, face)
        feat = _face_recognizer.feature(aligned)
        v = feat.flatten().astype(np.float64)
        n = np.linalg.norm(v)
        if n == 0:
            return None
        return v / n
    except Exception as e:
        print(f"[AI ERROR] SFace feature failed: {e}")
        return None


def _cos_sims(known_encodings, enc):
    """Cosine similarity of `enc` against every known encoding (all normalized)."""
    if not known_encodings:
        return None
    arr = np.asarray(known_encodings, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr @ enc


class Zone:
    def __init__(self, name, points, unauthorized_roles=[]):
        self.name = name
        self.points = np.array(points, np.int32)
        self.unauthorized_roles = unauthorized_roles

    def is_inside(self, point):
        return cv2.pointPolygonTest(self.points, point, False) >= 0

class VisionEngine:
    def reload_zones(self):
        """Loads zones from database or uses defaults"""
        try:
            saved_zones = database.get_zones_config()
            if saved_zones:
                new_zones = []
                for name, points_str, unauthorized in saved_zones:
                    import ast
                    try:
                        points = ast.literal_eval(points_str)
                        roles = unauthorized.split(",") if unauthorized else []
                        new_zones.append(Zone(name, points, unauthorized_roles=roles))
                    except: continue
                if new_zones: 
                    self.zones = new_zones
                    return
        except: pass
        
        # Default Fallback Zones (Must include 'Dining Area' for customer tracking)
        # IMPORTANT: Main Hall must be LAST — it covers the full frame and would
        # prevent smaller zones (Kitchen, Dining Area) from ever matching.
        self.zones = [
            Zone("Kitchen", [[50, 200], [250, 200], [250, 450], [50, 450]]),
            Zone("Dining Area", [[260, 50], [600, 50], [600, 450], [260, 450]]),
            Zone("Main Hall", [[10, 10], [630, 10], [630, 470], [10, 470]])
        ]

    def __init__(self):
        self.lock = threading.Lock()
        self.recognition_queue = queue.Queue()
        self.processing_tracks = set()
        self.last_rec_attempt = {}
        self.known_face_encodings = []
        self.known_face_metadata = [] 
        self.known_customer_encodings = []
        self.known_customer_metadata = []
        self.person_states = {} # track_id -> {"id": "Unknown", ...}
        self.recognition_consensus = {}
        self.customer_timers = {} # track_id -> {"start": time, "zone": name}
        self.alerted_tracks = set() # (track_id, zone_name)
        self.last_positions = {} # track_id -> (x, y)
        self.activity_buffer = {} # track_id -> seconds_active
        self.last_activity_sync = time.time()
        self.visitor_logged = set() # track_ids that have been logged to visitor_log
        self.dwell_buffer = [] # (detection, timestamp) for persistence when YOLO briefly misses
        
        self.frame_count = 0
        self.rec_throttle_frames = 5
        self.heartbeat_interval = 60
        
        self.role_work_zones = {
            "Chef": ["Kitchen"],
            "Cook": ["Kitchen"],
            "Waitstaff": ["Dining Area", "Kitchen", "Main Hall"],
            "Server": ["Dining Area", "Kitchen", "Main Hall"],
            "Manager": ["Kitchen", "Dining Area", "Main Hall"],
            "Owner": ["Kitchen", "Dining Area", "Main Hall"]
        }
        
        self.load_known_faces()
        self.reload_zones()

        # Start the background face recognition thread
        threading.Thread(target=self._recognition_worker, daemon=True, name="FaceRecWorkerThread").start()

    def warmup(self):
        """Start loading the YOLO model immediately (used at app startup so
        detection is ready as soon as the camera comes online)."""
        _start_model_load()

    def load_known_faces(self):
        try:
            # Load Staff
            staff_data = database.get_all_staff()
            new_encodings = []
            new_metadata = []
            for row in staff_data:
                s_id, name, role, shift_time, rate, encoding_blob, shift_name = row[:7]
                if encoding_blob:
                    try: raw = pickle.loads(encoding_blob)
                    except: raw = np.frombuffer(encoding_blob, dtype=np.float64)
                    # Support both single encoding (legacy) and multi-encoding list
                    if isinstance(raw, list):
                        enc_list = raw
                    else:
                        enc_list = [raw]
                    for enc in enc_list:
                        new_encodings.append(enc)
                        new_metadata.append({"id": s_id, "name": name, "role": role})
            
            # Load Customers
            cust_data = database.get_known_customers()
            c_encodings = []
            c_metadata = []
            for row in cust_data:
                c_id, name, encoding_blob, visit_count, photo = row[:5]
                try: encoding = pickle.loads(encoding_blob)
                except: encoding = np.frombuffer(encoding_blob, dtype=np.float64)
                c_encodings.append(encoding)
                c_metadata.append({"id": c_id, "name": name, "visits": visit_count, "photo": photo})
            
            with self.lock:
                self.known_face_encodings = new_encodings
                self.known_face_metadata = new_metadata
                self.known_customer_encodings = c_encodings
                self.known_customer_metadata = c_metadata
                # Flush recognition consensus so existing tracks get re-evaluated
                self.recognition_consensus.clear()
                self.last_rec_attempt.clear()
            
            print(f"[AI] System Ready: {len(new_encodings)} Staff, {len(c_encodings)} Customers loaded.")
        except Exception as e: print(f"[AI Initialization Error] {e}")

    def _recognition_worker(self):
        while True:
            try:
                track_id, face_crop, current_zone, current_time = self.recognition_queue.get()
                if face_crop is None or face_crop.size == 0:
                    self.recognition_queue.task_done()
                    with self.lock:
                        self.processing_tracks.discard(track_id)
                    continue

                # Ensure the face crop is a valid 8-bit uint8 BGR array
                if not isinstance(face_crop, np.ndarray):
                    raise ValueError("face_crop must be a numpy array")
                if face_crop.dtype != np.uint8:
                    face_crop = face_crop.astype(np.uint8)

                # Standardize channel layout (must be 3-channel BGR)
                if len(face_crop.shape) == 2:
                    face_crop = cv2.cvtColor(face_crop, cv2.COLOR_GRAY2BGR)
                elif len(face_crop.shape) == 3 and face_crop.shape[2] == 4:
                    face_crop = cv2.cvtColor(face_crop, cv2.COLOR_BGRA2BGR)
                elif len(face_crop.shape) == 3 and face_crop.shape[2] == 3:
                    pass
                else:
                    raise ValueError(f"Unexpected image shape for face recognition: {face_crop.shape}")

                h_f, w_f = face_crop.shape[:2]

                # Encode the face (YuNet detect + SFace embed).
                with face_rec_lock:
                    enc = _encode_face(face_crop)

                # Try upscaling for small crops
                if enc is None and (h_f < 160 or w_f < 160):
                    scale = min(4.0, max(160.0 / max(h_f, 1), 160.0 / max(w_f, 1), 1.0))
                    enlarged = cv2.resize(face_crop, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                    with face_rec_lock:
                        enc = _encode_face(enlarged)

                face_encodings = [enc] if enc is not None else []

                match_id = "Unknown"
                match_source = None
                if face_encodings:
                    with self.lock:
                        known_staff_enc = list(self.known_face_encodings)
                        known_staff_meta = list(self.known_face_metadata)
                        known_cust_enc = list(self.known_customer_encodings)
                        known_cust_meta = list(self.known_customer_metadata)
                    
                    # LOG: confirm which tables are being checked
                    print(f"[AI] Matching track {track_id} against {len(known_staff_enc)} staff emb, {len(known_cust_enc)} customer emb")
                    
                    best_staff_sim = -1.0
                    if known_staff_enc:
                        staff_sims = _cos_sims(known_staff_enc, face_encodings[0])
                        best_staff_idx = int(np.argmax(staff_sims))
                        best_staff_sim = float(staff_sims[best_staff_idx])
                        if best_staff_sim >= FACE_STAFF_RELAXED:
                            match_id = known_staff_meta[best_staff_idx]["id"]
                            match_source = "staff"
                            print(f"[AI] Staff match: {known_staff_meta[best_staff_idx]['name']} ({match_id}) — sim={best_staff_sim:.4f} (threshold={FACE_STAFF_RELAXED})")
                            # Immediately set db_id when the match is strong
                            with self.lock:
                                if best_staff_sim >= FACE_STAFF_STRONG and track_id in self.person_states:
                                    s = self.person_states[track_id]
                                    if s.get("db_id") is None:
                                        s["db_id"] = match_id
                                        s["id"] = f"ID: {match_id}"
                                        s["name"] = known_staff_meta[best_staff_idx]["name"]
                                        s["role"] = known_staff_meta[best_staff_idx]["role"]
                                        s["last_sync"] = current_time
                                        print(f"[AI] IMMEDIATE STAFF SET: track {track_id} -> {match_id}")
                            # Record attendance outside lock to avoid deadlock
                            try:
                                database.record_attendance(match_id)
                            except Exception as eat:
                                print(f"[AI] Attendance record error: {eat}")
                        else:
                            print(f"[AI] Staff check — best sim={best_staff_sim:.4f} for {known_staff_meta[best_staff_idx]['name']} (below {FACE_STAFF_RELAXED} threshold)")

                    best_cust_sim = -1.0
                    if match_id == "Unknown" and known_cust_enc:
                        c_sims = _cos_sims(known_cust_enc, face_encodings[0])
                        best_cust_idx = int(np.argmax(c_sims))
                        best_cust_sim = float(c_sims[best_cust_idx])
                        if best_cust_sim >= FACE_CUSTOMER:
                            match_id = f"CUST:{known_cust_meta[best_cust_idx]['id']}"
                            match_source = "customer"
                            matched_cust_idx = best_cust_idx
                            database.update_customer_encoding(known_cust_meta[matched_cust_idx]['id'], pickle.dumps(face_encodings[0]))
                            print(f"[AI] Customer match: {known_cust_meta[best_cust_idx]['name']} (ID {known_cust_meta[best_cust_idx]['id']}) — sim={best_cust_sim:.4f}")

                    if match_id == "Unknown":
                        print(f"[AI] No match found — best staff sim={best_staff_sim:.4f}, best cust sim={best_cust_sim:.4f}")
                
                # Update consensus and state under lock
                refresh_faces = False
                with self.lock:
                    if track_id not in self.recognition_consensus:
                        self.recognition_consensus[track_id] = []
                    self.recognition_consensus[track_id].append(match_id)
                    # Keep a larger window of 10 samples for better accuracy
                    if len(self.recognition_consensus[track_id]) > 10:
                        self.recognition_consensus[track_id].pop(0)
                        
                    counts = {cid: self.recognition_consensus[track_id].count(cid) for cid in set(self.recognition_consensus[track_id])}
                    winner = max(counts, key=counts.get)
                    
                    # Update state if it still exists
                    if track_id in self.person_states:
                        state = self.person_states[track_id]
                        # Require 3 confident votes in the window to confirm identity
                        if counts[winner] >= 3:
                            if winner.startswith("CUST:"):
                                c_id = int(winner.split(":")[1])
                                meta = next((m for m in self.known_customer_metadata if m["id"] == c_id), None)
                                if meta:
                                    state["id"] = f"GUEST #{c_id}"
                                    state["db_id"] = f"C_{c_id}"
                                    state["name"] = meta["name"]
                                    # Fetch fresh visit count from DB to avoid stale data
                                    try:
                                        fresh_rows = database.get_known_customers()
                                        fresh_meta = next((r for r in fresh_rows if r[0] == c_id), None)
                                        state["visits"] = fresh_meta[3] if fresh_meta else meta.get("visits", 1)
                                    except:
                                        state["visits"] = meta.get("visits", 1)
                                    state["photo"] = meta.get("photo")
                                    state["last_sync"] = current_time
                                    refresh_faces = True
                            elif winner != "Unknown":
                                meta = next((m for m in self.known_face_metadata if m["id"] == winner), None)
                                if meta:
                                    state["id"] = f"ID: {meta['id']}"
                                    state["name"] = meta["name"]
                                    state["role"] = meta["role"]
                                    state["db_id"] = meta["id"]
                                    state["last_sync"] = current_time
                                    database.record_attendance(meta["id"])
                                    # Remove any stale customer timer for this track (they're staff!)
                                    if track_id in self.customer_timers:
                                        del self.customer_timers[track_id]
                                    print(f"[AI CONSENSUS] track {track_id} -> STAFF db_id={state['db_id']!r} name={state['name']!r}")
                if refresh_faces:
                    self.load_known_faces()
                
                # Handle auto-registration outside lock
                if match_id == "Unknown" and face_encodings:
                    # CRITICAL: Check if this track already has a staff identity — if so, DO NOT overwrite
                    with self.lock:
                        existing_db_id = self.person_states.get(track_id, {}).get("db_id")
                    if existing_db_id and not str(existing_db_id).startswith("C_"):
                        print(f"[AI] Skipping auto-registration for track {track_id} — already identified as staff ({existing_db_id})")
                    else:
                        # ALWAYS do a quick staff check with relaxed threshold BEFORE waiting for 15 votes
                        # This prevents 30-second delay when distance is between 0.60 and 0.65
                        with self.lock:
                            known_staff_enc_q = list(self.known_face_encodings)
                            known_staff_meta_q = list(self.known_face_metadata)
                        if known_staff_enc_q:
                            s_sims_q = _cos_sims(known_staff_enc_q, face_encodings[0])
                            best_s_idx_q = int(np.argmax(s_sims_q))
                            best_s_sim_q = float(s_sims_q[best_s_idx_q])
                            if best_s_sim_q >= FACE_STAFF_RELAXED:
                                s_meta_q = known_staff_meta_q[best_s_idx_q]
                                print(f"[AI] Quick staff check: {s_meta_q['name']} (sim={best_s_sim_q:.4f}) — identifying immediately")
                                with self.lock:
                                    if track_id in self.person_states:
                                        state = self.person_states[track_id]
                                        state["id"] = f"ID: {s_meta_q['id']}"
                                        state["name"] = s_meta_q["name"]
                                        state["role"] = s_meta_q["role"]
                                        state["db_id"] = s_meta_q["id"]
                                        state["last_sync"] = current_time
                                        if track_id in self.customer_timers:
                                            del self.customer_timers[track_id]
                                    if track_id in self.recognition_consensus:
                                        self.recognition_consensus[track_id].append(s_meta_q["id"])
                                database.record_attendance(s_meta_q["id"])
                                self.recognition_queue.task_done()
                                with self.lock:
                                    self.processing_tracks.discard(track_id)
                                continue
                        
                        with self.lock:
                            consensus_list = self.recognition_consensus.get(track_id, [])
                            consensus_len = len(consensus_list)
                            counts = {cid: consensus_list.count(cid) for cid in set(consensus_list)} if consensus_list else {}
                            winner = max(counts, key=counts.get) if counts else "Unknown"
                            known_staff_count = len(self.known_face_encodings)
                        
                        # CRITICAL FIX: Only auto-register as customer after 15 consecutive Unknown votes
                        # This gives face recognition enough time to properly identify enrolled staff.
                        # If staff encodings exist, be even more conservative (wait longer).
                        min_unknown_votes = 15 if known_staff_count > 0 else 8
                        
                        if consensus_len >= min_unknown_votes and winner == "Unknown":
                            # Double-check with relaxed threshold before creating new customer
                            with self.lock:
                                known_cust_enc = list(self.known_customer_encodings)
                                known_cust_meta = list(self.known_customer_metadata)
                                known_staff_enc = list(self.known_face_encodings)
                                known_staff_meta = list(self.known_face_metadata)
                            
                            # Last-chance staff check with relaxed threshold
                            if known_staff_enc:
                                s_sims = _cos_sims(known_staff_enc, face_encodings[0])
                                best_s_idx = int(np.argmax(s_sims))
                                best_s_sim = float(s_sims[best_s_idx])
                                if best_s_sim >= FACE_STAFF_RELAXED:
                                    # Found a plausible staff match — update and skip customer creation
                                    s_meta = known_staff_meta[best_s_idx]
                                    print(f"[AI] Last-chance staff match: {s_meta['name']} (sim={best_s_sim:.4f}) — NOT creating new customer")
                                    with self.lock:
                                        if track_id in self.person_states:
                                            state = self.person_states[track_id]
                                            state["id"] = f"ID: {s_meta['id']}"
                                            state["name"] = s_meta["name"]
                                            state["role"] = s_meta["role"]
                                            state["db_id"] = s_meta["id"]
                                            state["last_sync"] = current_time
                                            if track_id in self.customer_timers:
                                                del self.customer_timers[track_id]
                                        if track_id in self.recognition_consensus:
                                            self.recognition_consensus[track_id].append(s_meta["id"])
                                    database.record_attendance(s_meta["id"])
                                    self.recognition_queue.task_done()
                                    with self.lock:
                                        self.processing_tracks.discard(track_id)
                                    continue
                            
                            fallback_match = False
                            if known_cust_enc:
                                c_sims = _cos_sims(known_cust_enc, face_encodings[0])
                                best_cust_idx = int(np.argmax(c_sims))
                                best_cust_sim = float(c_sims[best_cust_idx])
                                if best_cust_sim >= FACE_CUSTOMER:
                                    match_id = f"CUST:{known_cust_meta[best_cust_idx]['id']}"
                                    
                                    # Convert face_crop to base64 photo
                                    import base64
                                    _, buffer = cv2.imencode('.jpg', face_crop)
                                    b64_photo = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
                                    
                                    database.update_customer_encoding(known_cust_meta[best_cust_idx]['id'], pickle.dumps(face_encodings[0]), photo=b64_photo)
                                    fallback_match = True
                                    print(f"[AI] Auto-registered as RETURNING customer: {known_cust_meta[best_cust_idx]['name']} (sim={best_cust_sim:.4f})")
                                    with self.lock:
                                        if track_id in self.recognition_consensus:
                                            self.recognition_consensus[track_id].append(match_id)
                                        if track_id in self.person_states:
                                            state = self.person_states[track_id]
                                            c_id = int(known_cust_meta[best_cust_idx]['id'])
                                            state["db_id"] = f"C_{c_id}"
                                            state["id"] = f"GUEST #{c_id}"
                                            state["name"] = known_cust_meta[best_cust_idx]["name"]
                                            # Fetch fresh visit count
                                            try:
                                                fresh_rows = database.get_known_customers()
                                                fresh_meta = next((r for r in fresh_rows if r[0] == c_id), None)
                                                state["visits"] = fresh_meta[3] if fresh_meta else known_cust_meta[best_cust_idx].get("visits", 1)
                                            except:
                                                state["visits"] = known_cust_meta[best_cust_idx].get("visits", 1)
                                            state["photo"] = b64_photo
                                            state["last_sync"] = current_time
                            if not fallback_match:
                                # Convert face_crop to base64 photo
                                import base64
                                _, buffer = cv2.imencode('.jpg', face_crop)
                                b64_photo = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
                                
                                new_c_id = database.register_customer(pickle.dumps(face_encodings[0]), photo=b64_photo)
                                print(f"[AI] Auto-registered as NEW customer (ID {new_c_id})")
                                self.load_known_faces()
                                with self.lock:
                                    if track_id in self.person_states:
                                        state = self.person_states[track_id]
                                        state["db_id"] = f"C_{new_c_id}"
                                        state["id"] = f"GUEST #{new_c_id}"
                                        state["name"] = "New Guest"
                                        state["last_sync"] = current_time
                                        state["visits"] = 1
                                        state["photo"] = b64_photo
                            else:
                                self.load_known_faces()
                                
                self.recognition_queue.task_done()
                with self.lock:
                    self.processing_tracks.discard(track_id)
            except Exception as e:
                print(f"[AI BACKGROUND ERROR] {e}")
                try:
                    self.recognition_queue.task_done()
                except:
                    pass
                if 'track_id' in locals():
                    with self.lock:
                        self.processing_tracks.discard(track_id)

    def process_frame(self, frame, target_size=(640, 480), original_frame=None):
        try:
            global model, model_loading_active
            if model is None:
                _start_model_load()
                return cv2.resize(frame, target_size), []
                
            current_time = time.time()
            detections = []
            
            # Use the original camera frame for face cropping (highest quality)
            # output_frame goes to display at the user-selected resolution
            h_orig, w_orig = frame.shape[:2]
            h_out, w_out = target_size
            if h_out != h_orig or w_out != w_orig:
                output_frame = cv2.resize(frame, target_size)
            else:
                output_frame = frame
            
            # Face crop source: use original_frame when provided (native camera res), else output_frame
            face_source = original_frame if original_frame is not None else output_frame
            fh, fw = face_source.shape[:2]
            
            # Run YOLO on the native camera frame directly (cam_ai is already
            # small — 640x360 16:9), keeping boxes in the SAME native coordinate
            # space as the video the browser displays. No scaling, no distortion.
            DETECTION_WIDTH = w_orig
            DETECTION_HEIGHT = h_orig
            small_frame = frame
            results = model.track(small_frame, persist=True, verbose=False, conf=0.25, iou=0.45)
            
            # Detection boxes stay in native pixel space (scale = 1.0).
            scale_x = 1.0
            scale_y = 1.0
            
            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                if results[0].boxes.id is not None:
                    track_ids = results[0].boxes.id.int().cpu().numpy()
                else:
                    # Spatial proximity-based fallback tracker when results[0].boxes.id is None
                    track_ids = []
                    with self.lock:
                        used_tids = set()
                        for box in boxes:
                            x1, y1, x2, y2 = map(int, box)
                            center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                            
                            best_tid = None
                            best_dist = 100  # Association distance threshold (pixels)
                            
                            for tid, pos in self.last_positions.items():
                                if tid not in used_tids:
                                    dist = np.sqrt((center[0] - pos[0])**2 + (center[1] - pos[1])**2)
                                    if dist < best_dist:
                                        best_dist = dist
                                        best_tid = tid
                                        
                            if best_tid is not None:
                                track_ids.append(best_tid)
                                used_tids.add(best_tid)
                            else:
                                # Generate a new unique track ID
                                new_tid = 1
                                while new_tid in self.person_states or new_tid in self.last_positions or new_tid in used_tids:
                                    new_tid += 1
                                track_ids.append(new_tid)
                                used_tids.add(new_tid)
                    track_ids = np.array(track_ids, dtype=np.int32)
                
                # Check for tracks to stitch / merge
                with self.lock:
                    for box, track_id in zip(boxes, track_ids):
                        x1, y1, x2, y2 = map(int, box)
                        center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                        
                        if track_id not in self.person_states:
                            merged = False
                            candidates = []
                            for old_tid, old_state in list(self.person_states.items()):
                                time_since_last_active = current_time - old_state["last_active"]
                                if old_tid != track_id and old_tid not in track_ids and time_since_last_active < 3.0:
                                    old_pos = self.last_positions.get(old_tid)
                                    if old_pos:
                                        dist = np.sqrt((center[0] - old_pos[0])**2 + (center[1] - old_pos[1])**2)
                                        if dist < 100:
                                            candidates.append((dist, old_tid, old_state))
                            
                            if candidates:
                                candidates.sort(key=lambda x: x[0])
                                best_dist, old_tid, old_state = candidates[0]
                                self.person_states[track_id] = {
                                    "id": old_state["id"],
                                    "db_id": old_state["db_id"],
                                    "zone": "Main Hall",
                                    "last_active": current_time,
                                    "last_sync": old_state.get("last_sync", 0),
                                    "role": old_state.get("role", "None"),
                                    "name": old_state.get("name", "")
                                }
                                if "pose_multiplier" in old_state:
                                    self.person_states[track_id]["pose_multiplier"] = old_state["pose_multiplier"]
                                if "pose_label" in old_state:
                                    self.person_states[track_id]["pose_label"] = old_state["pose_label"]
                                    
                                if old_tid in self.recognition_consensus:
                                    self.recognition_consensus[track_id] = self.recognition_consensus[old_tid].copy()
                                
                                if old_tid in self.customer_timers:
                                    self.customer_timers[track_id] = self.customer_timers[old_tid]
                                    del self.customer_timers[old_tid]
                                    
                                to_add = []
                                for tid, zname in list(self.alerted_tracks):
                                    if tid == old_tid:
                                        to_add.append((track_id, zname))
                                self.alerted_tracks = {(tid, zname) for tid, zname in self.alerted_tracks if tid != old_tid}
                                for item in to_add:
                                    self.alerted_tracks.add(item)
                                    
                                if old_tid in self.person_states:
                                    del self.person_states[old_tid]
                                if old_tid in self.last_positions:
                                    del self.last_positions[old_tid]
                                
                                print(f"[AI] Merged track {old_tid} into new track {track_id} (dist={best_dist:.1f})")
                                merged = True
                                
                            if not merged:
                                self.person_states[track_id] = {
                                    "id": "Unknown", "db_id": None, "zone": "Main Hall", 
                                    "last_active": current_time, "last_sync": 0, "role": "None"
                                }
                
                # Process active tracks
                all_kps = results[0].keypoints.xy.cpu().numpy() if results[0].keypoints is not None else None
                for i, (box, track_id) in enumerate(zip(boxes, track_ids)):
                    x1, y1, x2, y2 = map(int, box)
                    center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                    
                    # Scaled coordinates for drawing on the HD output frame
                    x1_out = int(x1 * scale_x)
                    y1_out = int(y1 * scale_y)
                    x2_out = int(x2 * scale_x)
                    y2_out = int(y2 * scale_y)
                    
                    with self.lock:
                        if track_id not in self.person_states:
                            self.person_states[track_id] = {
                                "id": "Unknown", "db_id": None, "zone": "Main Hall", 
                                "last_active": current_time, "last_sync": 0, "role": "None"
                            }
                        state = self.person_states[track_id]
                        state["last_active"] = current_time
                    
                    # Zone Detection
                    current_zone = "Main Hall"
                    for zone in self.zones:
                        if zone.is_inside(center):
                            current_zone = zone.name
                            break
                    with self.lock:
                        state["zone"] = current_zone
                    
                    # Pose & Action Analysis
                    keypoints = results[0].keypoints.xy.cpu().numpy()[0] if results[0].keypoints is not None else None
                    pose_label = "NEUTRAL"
                    pose_multiplier = 1.0
                    
                    if keypoints is not None and len(keypoints) > 10:
                        try:
                            l_shoulder, r_shoulder = keypoints[5], keypoints[6]
                            l_wrist, r_wrist = keypoints[9], keypoints[10]
                            l_hip, r_hip = keypoints[11], keypoints[12]
                            
                            hip_y = (l_hip[1] + r_hip[1]) / 2
                            shoulder_y = (l_shoulder[1] + r_shoulder[1]) / 2
                            torso_height = abs(hip_y - shoulder_y)
                            
                            hands_active = l_wrist[1] < (hip_y - 0.1*torso_height) or r_wrist[1] < (hip_y - 0.1*torso_height)
                            is_leaning = abs(l_shoulder[0] - l_hip[0]) > (0.15 * torso_height)
                            hands_at_side = abs(l_wrist[1] - l_hip[1]) < (0.1 * torso_height) and abs(r_wrist[1] - r_hip[1]) < (0.1 * torso_height)
                            
                            if hands_active:
                                pose_label = "ACTIVE"
                                pose_multiplier = 1.3
                            elif is_leaning:
                                pose_label = "ENGAGED"
                                pose_multiplier = 1.1
                            elif hands_at_side:
                                pose_label = "RELAXED"
                                pose_multiplier = 0.5
                            
                            with self.lock:
                                state["pose_multiplier"] = pose_multiplier
                                state["pose_label"] = pose_label
                        except: pass

                    # Identification Logic (Offloaded to background queue)
                    with self.lock:
                        db_id = state["db_id"]
                    
                    if db_id is None:
                        with self.lock:
                            is_processing = track_id in self.processing_tracks
                        
                        last_attempt = self.last_rec_attempt.get(track_id, 0)
                        # Retry recognition every 2 seconds for unidentified faces
                        if not is_processing and (current_time - last_attempt > 2.0):
                            self.last_rec_attempt[track_id] = current_time

                            face_img = None

                            # Compute scale from DETECTION (640x480) to face_source (native camera res)
                            fs_scale_x = fw / DETECTION_WIDTH
                            fs_scale_y = fh / DETECTION_HEIGHT

                            # Try precise face crop using YOLO keypoints (nose)
                            if all_kps is not None and i < len(all_kps):
                                kp = all_kps[i]
                                nose = kp[0]
                                if nose[0] > 0 and nose[1] > 0:
                                    nose_x = int(nose[0] * fs_scale_x)
                                    nose_y = int(nose[1] * fs_scale_y)
                                    det_box_h = y2 - y1
                                    face_size = max(int(det_box_h * fs_scale_y * 0.35), 80)
                                    # Shift crop upward so more area is above the nose
                                    # to consistently capture eyes and forehead
                                    shift_up = int(face_size * 0.15)
                                    x1f = max(0, nose_x - face_size)
                                    y1f = max(0, nose_y - face_size - shift_up)
                                    x2f = min(fw, nose_x + face_size)
                                    y2f = min(fh, nose_y + face_size - shift_up)
                                    if x2f > x1f and y2f > y1f:
                                        face_img = face_source[y1f:y2f, x1f:x2f]

                            if face_img is None:
                                y1f = int(y1 * fs_scale_y)
                                y2f = int(y1f + (y2 - y1) * fs_scale_y * 0.30)
                                x_margin = int((x2 - x1) * fs_scale_x * 0.10)
                                x1f = max(0, int(x1 * fs_scale_x) - x_margin)
                                x2f = min(fw, int(x2 * fs_scale_x) + x_margin)
                                if x2f > x1f and y2f > y1f:
                                    face_img = face_source[y1f:y2f, x1f:x2f]

                            if face_img is not None and face_img.shape[0] >= 64 and face_img.shape[1] >= 64:
                                with self.lock:
                                    self.processing_tracks.add(track_id)
                                self.recognition_queue.put((track_id, face_img.copy(), current_zone, current_time))
                    else:
                        # Sync presence heartbeat (only for confirmed staff, not customers)
                        with self.lock:
                            last_sync = state["last_sync"]
                        if current_time - last_sync > self.heartbeat_interval:
                            if db_id and not str(db_id).startswith("C_"):
                                database.record_attendance(db_id)
                            with self.lock:
                                state["last_sync"] = current_time
                        
                    # Path Context & Exact Efficiency Logic
                    with self.lock:
                        db_id = state["db_id"]
                        role = state["role"]
                        
                    if db_id and not str(db_id).startswith("C_"):
                        prev_pos = self.last_positions.get(track_id)
                        if prev_pos:
                            dist = np.sqrt((center[0]-prev_pos[0])**2 + (center[1]-prev_pos[1])**2)
                            
                            # 1. Base Multiplier (Idle check)
                            multiplier = 0.0
                            if dist > 3: # Some movement detected
                                multiplier = 1.0
                            
                            # 2. Zone Precision check (Anti-Fake)
                            authorized_zones = self.role_work_zones.get(role, ["Main Hall"])
                            if current_zone not in authorized_zones:
                                multiplier *= 0.1 # Severe penalty for being in unauthorized areas
                            elif current_zone == "Main Hall":
                                multiplier *= 0.3 # Low value for walking in halls
                            
                            # 3. Service Engagement (Customer Proximity)
                            is_near_customer = False
                            with self.lock:
                                for other_tid, other_state in self.person_states.items():
                                    if other_tid != track_id and str(other_state.get("db_id", "")).startswith("C_"):
                                        other_pos = self.last_positions.get(other_tid)
                                        if other_pos:
                                            p_dist = np.sqrt((center[0]-other_pos[0])**2 + (center[1]-other_pos[1])**2)
                                            if p_dist < 150: # Proximity to a registered customer (approx 5ft)
                                                is_near_customer = True
                                                break
                            
                            if is_near_customer:
                                multiplier *= 2.0 # DOUBLE efficiency for guest interaction
                            
                            # 4. Pose-Based Action Refinement
                            with self.lock:
                                p_mult = state.get("pose_multiplier", 1.0)
                            multiplier *= p_mult
                            
                            # 5. Stationary Work Check
                            if dist <= 3 and current_zone in authorized_zones and current_zone != "Main Hall":
                                multiplier = 0.3
                            
                            self.activity_buffer[db_id] = self.activity_buffer.get(db_id, 0) + multiplier
                        
                    self.last_positions[track_id] = center
                    
                    # RESTRICTED ZONE MONITORING
                    if db_id:
                        in_unauth_zone = False
                        for zone in self.zones:
                            if zone.is_inside(center) and role in zone.unauthorized_roles:
                                in_unauth_zone = True
                                if (track_id, zone.name) not in self.alerted_tracks:
                                    database.log_activity(db_id, zone.name, "Security Alert", f"Unauthorized role ({role}) detected in restricted zone.")
                                    with self.lock:
                                        state["needs_security_email"] = zone.name
                                    self.alerted_tracks.add((track_id, zone.name))
                                break
                        
                        if not in_unauth_zone:
                            # Clear alerts for zones this track is no longer in
                            self.alerted_tracks = {(tid, zname) for tid, zname in self.alerted_tracks if tid != track_id}

                    # CUSTOMER INTELLIGENCE (Track every non-staff person as a customer)
                    is_staff = db_id and not str(db_id).startswith("C_")
                    if not is_staff:
                        # Only start customer timer once we have a confirmed customer identity (C_xxx)
                        # or after they've been unidentified for a while (avoid tracking enrolled staff
                        # as customers during the recognition warm-up period)
                        if db_id and str(db_id).startswith("C_"):
                            # Confirmed customer identity — track them
                            if track_id not in self.customer_timers:
                                c_id = int(str(db_id).split("_")[1])
                                self.customer_timers[track_id] = {"start": current_time, "zone": current_zone, "c_id": c_id}
                            else:
                                # Update c_id in case it was set before identity was confirmed
                                self.customer_timers[track_id]["c_id"] = int(str(db_id).split("_")[1])
                        elif db_id is None:
                            # Unknown face — only track as anonymous if YOLO face keypoints confirm
                            # a face is present AND the person has been visible for a sustained period.
                            # This prevents briefly-seen people (walk-bys) from inflating visit counts.
                            with self.lock:
                                unknown_votes = len([v for v in self.recognition_consensus.get(track_id, []) if v == "Unknown"])
                                first_seen = self.person_states.get(track_id, {}).get("last_active", current_time)
                            track_age = current_time - self.person_states.get(track_id, {}).get("last_sync", current_time - 999)
                            # Require at least 20 "Unknown" votes (≈40s at 0.5fps recognition) AND
                            # that the track has been alive for at least 8 seconds before counting.
                            if unknown_votes >= 20 and track_id not in self.customer_timers:
                                # Has been consistently unidentified — track as anonymous visitor
                                self.customer_timers[track_id] = {"start": current_time, "zone": current_zone, "c_id": None}
                    elif track_id in self.customer_timers:
                        # Person confirmed as staff — remove any stale customer timer
                        del self.customer_timers[track_id]

                    # Visuals (Bounding Boxes for EVERYONE)
                    with self.lock:
                        db_id = state.get("db_id")
                        state_id = state.get("id")
                        state_name = state.get("name", "Unknown")
                        state_role = state.get("role", "None")
                        status = state.get("pose_label", "NEUTRAL")
                        
                    if not db_id:
                        color_hex = "#f97316"  # Orange for Unknown/Unidentified Face
                        label = "Detecting..."
                        print(f"[AI LABEL] track {track_id}: db_id={db_id!r} -> Detecting")
                    elif str(db_id).startswith("C_"):
                        visits = state.get("visits", 1)
                        if visits <= 1:
                            color_hex = "#f97316"  # Orange for New Customer (first visit)
                            label = "New Customer (1st visit)"
                            print(f"[AI LABEL] track {track_id}: db_id={db_id!r} -> New Customer")
                        else:
                            color_hex = "#eab308"  # Yellow for Regular Guest (2+ visits on different days)
                            suffix = "th" if visits >= 4 else ({1:"st",2:"nd",3:"rd"}.get(visits, "th"))
                            label = f"Regular Customer ({visits}{suffix} visit)"
                            print(f"[AI LABEL] track {track_id}: db_id={db_id!r} -> Regular Customer (visits={visits})")
                    else:
                        color_hex = "#3b82f6"  # Blue for Enrolled Staff (Type 3)
                        role_tag = f" ({state_role})" if state_role and state_role != "None" else ""
                        label = f"STAFF: {state_name}{role_tag}"
                        print(f"[AI LABEL] track {track_id}: db_id={db_id!r} -> STAFF: {state_name}")
                    
                    # Store last box in state for carry-forward during brief YOLO misses
                    state["last_box"] = [float(x1), float(y1), float(x2), float(y2)]
                    state["last_label"] = label
                    state["last_color"] = color_hex
                    # Compile detection metadata for canvas rendering
                    detections.append({
                        "box": state["last_box"],
                        "label": label,
                        "color": color_hex
                    })

            # Cleanup expired tracks under lock
            with self.lock:
                expired = [tid for tid, s in self.person_states.items() if current_time - s["last_active"] > 10]
                for tid in expired:
                    if tid in self.customer_timers:
                        duration = current_time - self.customer_timers[tid]["start"]
                        if duration > 15:
                            database.record_customer_session("Auto-Table", duration, self.customer_timers[tid]["c_id"])
                        del self.customer_timers[tid]
                    
                    # Log visitor detection for analytics (once per track lifetime)
                    # GUARD: Only log if the track lived long enough to be a real person
                    # (>= 5 seconds). Prevents brief detections / shadows from inflating counts.
                    if tid not in self.visitor_logged:
                        state = self.person_states[tid]
                        track_lifetime = current_time - state.get("last_sync", current_time - 999)
                        db_id = state.get("db_id")
                        zone = state.get("zone", "Main Hall")

                        # For unknown anonymous faces: require at least 20 "Unknown" consensus
                        # votes so a face was genuinely detected and failed to match (not a shadow).
                        if db_id is None:
                            consensus = self.recognition_consensus.get(tid, [])
                            unknown_votes = consensus.count("Unknown")
                            if unknown_votes < 15:
                                # Not enough face evidence — skip logging this track
                                del self.person_states[tid]
                                if tid in self.recognition_consensus: del self.recognition_consensus[tid]
                                continue

                        self.visitor_logged.add(tid)
                        if db_id and not str(db_id).startswith("C_"):
                            database.log_visitor_detection(None, False, staff_id=db_id, zone=zone)
                        elif db_id and str(db_id).startswith("C_"):
                            c_id = int(str(db_id).split("_")[1])
                            database.log_visitor_detection(c_id, False, zone=zone)
                        else:
                            database.log_visitor_detection(None, True, zone=zone)
                    
                    del self.person_states[tid]
                    if tid in self.recognition_consensus: del self.recognition_consensus[tid]

            self.frame_count += 1
            
            # Periodic Active Time Sync (every 10 seconds)
            if current_time - self.last_activity_sync > 10:
                for staff_id, seconds in self.activity_buffer.items():
                    if seconds > 0:
                        database.update_active_time(staff_id, seconds)
                self.activity_buffer = {}
                self.last_activity_sync = current_time

            # Carry-forward: add synthetic detection entries for active tracks YOLO briefly missed
            with self.lock:
                tracked_ids = {d["box"][0] for d in detections}  # crude dedup set, refined below
                # Build set of track_ids already covered in current detections
                carried = set()
                for tid, s in list(self.person_states.items()):
                    if current_time - s["last_active"] < 3.0 and "last_box" in s:
                        carried.add(tid)
                # Remove any track that IS already in the current YOLO output
                for d in detections:
                    bx = d["box"]
                    cx = (bx[0] + bx[2]) / 2
                    cy = (bx[1] + bx[3]) / 2
                    for tid in list(carried):
                        lb = self.person_states[tid]["last_box"]
                        lcx = (lb[0] + lb[2]) / 2
                        lcy = (lb[1] + lb[3]) / 2
                        if abs(cx - lcx) < 40 and abs(cy - lcy) < 40:
                            carried.discard(tid)
                            break
                for tid in carried:
                    s = self.person_states[tid]
                    detections.append({
                        "box": s["last_box"],
                        "label": s.get("last_label", "Detecting..."),
                        "color": s.get("last_color", "#f97316")
                    })

            # Detection dwell: keep showing last known positions if YOLO briefly misses
            now = time.time()
            if not detections and self.dwell_buffer:
                self.dwell_buffer = [(d, t) for d, t in self.dwell_buffer if now - t < 2.5]
                detections = [d for d, _ in self.dwell_buffer]
            elif detections:
                self.dwell_buffer = [(d, now) for d in detections]

            return output_frame, detections
        except Exception as e:
            print(f"[VISION ERROR] {e}")
            return cv2.resize(frame, target_size), []

    def get_active_staff(self):
        """Returns only confirmed staff members currently visible (excludes customers)."""
        active_dict = {}
        with self.lock:
            for tid, state in self.person_states.items():
                db_id = state.get("db_id")
                # Only include enrolled staff — skip None (unknown) and C_xxx (customers)
                if (time.time() - state["last_active"] < 8
                        and db_id is not None
                        and not str(db_id).startswith("C_")):
                    active_dict[db_id] = {
                        "id": state["id"],
                        "name": state.get("name", "Unknown"),
                        "role": state.get("role", "None"),
                        "zone": state["zone"]
                    }
        return list(active_dict.values())
