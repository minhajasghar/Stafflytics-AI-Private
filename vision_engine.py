import cv2
import numpy as np
import os
import time
from datetime import datetime
import database
import pickle
import queue
import threading

# Limit background thread count for ONNXRuntime (InsightFace) to prevent CPU starvation / video buffering
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["VECLIB_MAXIMUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"

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
            model_path = os.path.join(base_dir, 'models', 'yolov8n-pose.onnx')
            print(f"[AI] Attempting to load YOLO model from: {model_path}")
            device = 'cpu' if not torch.cuda.is_available() else 0
            if os.path.exists(model_path):
                model = YOLO(model_path, task='pose')
            else:
                print(f"[AI INFO] Local model {model_path} not found. Ultralytics will auto-download.")
                model = YOLO('yolov8n-pose.pt') # Let ultralytics download and we use pt as fallback
            model.to(device)
            print(f"[AI] Background Model Load Complete. Running on {device}")
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
# InsightFace backend (SCRFD detection + ArcFace recognition).
# Embeds are 512-d float vectors; normalized to unit length so matching is a
# cosine similarity (dot product). Stored in DB via pickle.
# ---------------------------------------------------------------------------
_face_app = None
_face_models_loaded = False
_last_ai_error = None

# ArcFace cosine-similarity thresholds (Production Tuned)
FACE_STAFF_THRESHOLD = 0.60      # Strict staff threshold for reliable recognition
FACE_CUSTOMER_THRESHOLD = 0.65   # Strict customer threshold to prevent false merges
FACE_STAFF_RELAXED = 0.55        # Slightly relaxed threshold for rapid checks
FACE_CUSTOMER = 0.65             # Backward-compatibility alias


def _load_face_models():
    """Load InsightFace models (idempotent)."""
    global _face_app, _face_models_loaded, _last_ai_error
    if _face_models_loaded:
        return True
    try:
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        # Use a larger det_size to prevent 1080p web captures from being downscaled too much,
        # which causes small faces to disappear during enrollment. 
        # (Real-time tracking is unaffected because it passes pre-cropped small faces).
        _face_app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.3)
        _face_models_loaded = True
        print("[AI] InsightFace models loaded (SCRFD + ArcFace).")
        return True
    except Exception as e:
        _last_ai_error = str(e)
        print(f"[AI ERROR] Failed to load InsightFace models: {e}")
        return False


def _get_best_face(bgr):
    """Return the largest detected Face object from InsightFace, or None."""
    if bgr is None or bgr.size == 0:
        return None
    if not _load_face_models():
        return None
    try:
        faces = _face_app.get(bgr)
        if not faces:
            return None
        # InsightFace returns bounding boxes as [x1, y1, x2, y2]
        # Maximize width * height: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1])
        best = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        return best
    except Exception as e:
        global _last_ai_error
        _last_ai_error = str(e)
        print(f"[AI ERROR] InsightFace detect failed: {e}")
        return None


def _encode_face(bgr, strict=True):
    """Detect the largest face in a BGR image and return a normalized 512-d
    ArcFace embedding, or None when no face is found or quality is low."""
    face = _get_best_face(bgr)
    if face is None:
        return None
    
    # Pre-Inference Quality Filters (FIQA)
    if strict:
        # 1. Minimum Resolution (80x80)
        w = face.bbox[2] - face.bbox[0]
        h = face.bbox[3] - face.bbox[1]
        if w < 70 or h < 70:
            return None
            
        # 2. Blur / Sharpness Check (Laplacian Variance)
        # Crop the face from the original image using the bounding box
        x1, y1, x2, y2 = map(int, face.bbox)
        x1, y1 = max(0, x1), max(0, y1)
        face_crop = bgr[y1:y2, x1:x2]
        if face_crop.size > 0:
            lap_var = cv2.Laplacian(face_crop, cv2.CV_64F).var()
            if lap_var < 40.0:
                return None
    
    try:
        v = face.embedding.flatten().astype(np.float64)
        n = np.linalg.norm(v)
        if n == 0:
            return None
        return v / n
    except Exception as e:
        print(f"[AI ERROR] ArcFace feature extraction failed: {e}")
        return None


def _cos_sims(known_encodings, enc):
    """Cosine similarity of `enc` against every known encoding (all normalized)."""
    if not known_encodings:
        return None
    arr = np.asarray(known_encodings, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr @ enc


def _box_iou(boxA, boxB):
    """Compute Intersection over Union (IoU) of two bounding boxes [x1, y1, x2, y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union = boxAArea + boxBArea - interArea
    return interArea / float(union + 1e-6) if union > 0 else 0.0

def _extract_dominant_color(body_crop):
    """Extract mean color (B, G, R) of the torso region."""
    if body_crop is None or body_crop.size == 0:
        return None
    try:
        h, w = body_crop.shape[:2]
        torso = body_crop[int(h*0.25):int(h*0.65), int(w*0.25):int(w*0.75)]
        if torso.size == 0:
            return None
        mean_color = cv2.mean(torso)
        return (int(mean_color[0]), int(mean_color[1]), int(mean_color[2]))
    except:
        return None


def _extract_appearance_embedding(body_crop):
    """
    Extracts a 128-dimensional spatial-color and texture appearance embedding (Person Re-ID)
    from a full person body bounding box crop.
    Works robustly even when the face is occluded, turned away, or camera is at a steep ceiling angle.
    """
    if body_crop is None or body_crop.size == 0:
        return None
    try:
        # Standardize size for consistent feature representation (128w x 256h)
        img = cv2.resize(body_crop, (128, 256))
        h, w = img.shape[:2]
        
        # 3 Vertical Body Zones:
        # 1. Head / Shoulders (0 - 25% height)
        # 2. Upper Torso / Shirt (25% - 65% height)
        # 3. Lower Body / Pants (65% - 100% height)
        zones = [
            img[0:int(h*0.25), :],
            img[int(h*0.25):int(h*0.65), :],
            img[int(h*0.65):h, :]
        ]
        
        features = []
        for zone in zones:
            if zone.size == 0:
                features.extend([0.0]*38)
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
            zone_feat = zone_feat / (np.linalg.norm(zone_feat) + 1e-6)
            features.extend(zone_feat)
            
        # Global texture gradient energy (Sobel on grayscale) = 14 bins
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag, _ = cv2.cartToPolar(gx, gy)
        mag_hist = cv2.calcHist([mag.astype(np.uint8)], [0], None, [14], [0, 256]).flatten()
        mag_hist = mag_hist / (np.linalg.norm(mag_hist) + 1e-6)
        features.extend(mag_hist)
        
        vec = np.array(features, dtype=np.float32)
        # L2 normalize entire 128D feature vector
        vec = vec / (np.linalg.norm(vec) + 1e-6)
        return vec
    except Exception as e:
        return None


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
                    # Ensure Main Hall exists as a fallback if not explicitly redefined by user
                    if not any(z.name == "Main Hall" for z in new_zones):
                        new_zones.append(Zone("Main Hall", [[10, 10], [630, 10], [630, 470], [10, 470]]))
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
        self.last_boxes = {} # track_id -> [x1, y1, x2, y2]
        self.velocities = {} # track_id -> (dx, dy)
        self.last_kps = {} # track_id -> keypoints array
        self.last_valid_raw_boxes = [] # Full list of boxes for skipped frames
        self.last_valid_raw_kps = []
        self.last_valid_track_ids = []
        
        self.recent_guest_embeddings = [] # Short-term memory for returning guests: [{"name": name, "db_id": db_id, "encs": list, "last_seen": timestamp}]
        self.reid_appearance_cache = {} # Person Re-ID Appearance Cache: identity_id -> {"name": name, "role": role, "reid_vec": vec, "last_seen": timestamp}
        self.staff_clothes_colors = {} # db_id -> (B, G, R) dominant color
        self.clothes_memory_date = datetime.now().date()
        self.activity_buffer = {} # track_id -> seconds_active
        self.last_activity_sync = time.time()
        self.visitor_logged = set() # track_ids that have been logged to visitor_log
        self.dwell_buffer = [] # (detection, timestamp) for persistence when YOLO briefly misses
        
        # Corridor Passage Counters (Left-to-Right and Right-to-Left)
        self.passage_counts = {"l_to_r": 0, "r_to_l": 0}
        self.track_trajectories = {} # track_id -> deque([(x, y, time)], maxlen=40)
        self.counted_passages = set() # track_ids already counted for their current crossing
        try:
            p_stats = database.get_passage_stats()
            self.passage_counts["l_to_r"] = p_stats.get("l_to_r", 0)
            self.passage_counts["r_to_l"] = p_stats.get("r_to_l", 0)
        except: pass
        
        self.frame_count = 0
        self.rec_throttle_frames = 2
        self.heartbeat_interval = 60
        
        self.role_work_zones = {
            "Co-Founder / AI Solutions Architect": ["Office", "Lab", "Workstation", "Main Hall", "Dining Area", "Kitchen"],
            "Co-Founder / Web Solutions Architect": ["Office", "Lab", "Workstation", "Main Hall", "Dining Area", "Kitchen"],
            "Head of Business Development": ["Office", "Workstation", "Main Hall", "Dining Area"],
            "Head of Quality Assurance": ["Office", "Lab", "Workstation", "Main Hall"],
            "AI Intern": ["Office", "Lab", "Workstation", "Main Hall"],
            "Electronics Engineer": ["Lab", "Workstation", "Office", "Main Hall"],
            "Manager": ["Office", "Lab", "Workstation", "Main Hall", "Kitchen", "Dining Area"],
            "Chef": ["Kitchen"],
            "Cook": ["Kitchen"],
            "Waitstaff": ["Dining Area", "Kitchen", "Main Hall"],
            "Server": ["Dining Area", "Kitchen", "Main Hall"],
            "Owner": ["Office", "Lab", "Workstation", "Main Hall", "Kitchen", "Dining Area"]
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
                        enc_list = [np.array(e, dtype=np.float32) for e in raw if e is not None]
                    else:
                        enc_list = [np.array(raw, dtype=np.float32)]
                    for enc in enc_list:
                        new_encodings.append(enc)
                        new_metadata.append({"id": s_id, "name": name, "role": role, "all_encs": enc_list})
            
            # Load Customers
            cust_data = database.get_known_customers()
            c_encodings = []
            c_metadata = []
            for row in cust_data:
                c_id, name, encoding_blob, visit_count, photo = row[:5]
                try: raw_c = pickle.loads(encoding_blob)
                except: raw_c = np.frombuffer(encoding_blob, dtype=np.float64)
                if isinstance(raw_c, list):
                    c_enc_list = [np.array(e, dtype=np.float32) for e in raw_c if e is not None]
                else:
                    c_enc_list = [np.array(raw_c, dtype=np.float32)]
                for enc in c_enc_list:
                    c_encodings.append(enc)
                    c_metadata.append({"id": c_id, "name": name, "visits": visit_count, "photo": photo, "all_encs": c_enc_list})
            
            with self.lock:
                self.known_face_encodings = new_encodings
                self.known_face_metadata = new_metadata
                self.known_customer_encodings = c_encodings
                self.known_customer_metadata = c_metadata
                
                # Purge deleted staff or customers from active live tracks immediately
                known_staff_ids = {m["id"] for m in new_metadata}
                known_cust_ids = {f"C_{m['id']}" for m in c_metadata}
                for tid, state in list(self.person_states.items()):
                    curr_db_id = state.get("db_id")
                    if curr_db_id:
                        if not str(curr_db_id).startswith("C_") and curr_db_id not in known_staff_ids:
                            # Staff was deleted! Reset live track immediately
                            print(f"[AI] Purging deleted staff {curr_db_id} from active track {tid}")
                            state["db_id"] = None
                            state["id"] = f"Track #{tid}"
                            state["name"] = "Guest"
                            state["role"] = "None"
                            state["last_label"] = "New Customer (1st visit)"
                            state["last_color"] = "#f97316"
                            state["best_staff_sim"] = 0.0
                        elif str(curr_db_id).startswith("C_") and curr_db_id not in known_cust_ids:
                            state["db_id"] = None
                            state["id"] = f"Track #{tid}"
                            state["name"] = "Guest"
                
                # Flush recognition consensus so existing tracks get re-evaluated
                self.recognition_consensus.clear()
                self.last_rec_attempt.clear()
                self.processing_tracks.clear()
            
            print(f"[AI] System Ready: {len(new_encodings)} Staff, {len(c_encodings)} Customers loaded.")
        except Exception as e: print(f"[AI Initialization Error] {e}")

    def _recognition_worker(self):
        while True:
            try:
                track_id, face_crop, body_crop, current_zone, current_time = self.recognition_queue.get()
                if (face_crop is None or face_crop.size == 0) and (body_crop is None or body_crop.size == 0):
                    self.recognition_queue.task_done()
                    with self.lock:
                        self.processing_tracks.discard(track_id)
                    continue

                face_encodings = []
                if face_crop is not None and face_crop.size > 0:
                    # Ensure the face crop is a valid 8-bit uint8 BGR array
                    if not isinstance(face_crop, np.ndarray):
                        face_crop = np.array(face_crop)
                    if face_crop.dtype != np.uint8:
                        face_crop = face_crop.astype(np.uint8)

                    if len(face_crop.shape) == 2:
                        face_crop = cv2.cvtColor(face_crop, cv2.COLOR_GRAY2BGR)
                    elif len(face_crop.shape) == 3 and face_crop.shape[2] == 4:
                        face_crop = cv2.cvtColor(face_crop, cv2.COLOR_BGRA2BGR)

                    h_f, w_f = face_crop.shape[:2]
                    # Encode the face (YuNet detect + SFace embed)
                    with face_rec_lock:
                        enc = _encode_face(face_crop)

                    # Try upscaling for small crops
                    if enc is None and (h_f < 160 or w_f < 160):
                        scale = min(4.0, max(160.0 / max(h_f, 1), 160.0 / max(w_f, 1), 1.0))
                        enlarged = cv2.resize(face_crop, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                        with face_rec_lock:
                            enc = _encode_face(enlarged)

                    if enc is not None:
                        face_encodings = [enc]

                # Extract Person Re-ID Appearance Embedding (Full Body)
                body_reid_vec = _extract_appearance_embedding(body_crop) if body_crop is not None else None

                match_id = "Unknown"
                match_source = None
                matched_staff_meta = None
                matched_cust_meta = None

                # TIER 1: Match by Face Recognition (Highest Confidence)
                if face_encodings:
                    with self.lock:
                        known_staff_enc = list(self.known_face_encodings)
                        known_staff_meta = list(self.known_face_metadata)
                        known_cust_enc = list(self.known_customer_encodings)
                        known_cust_meta = list(self.known_customer_metadata)
                    
                    best_staff_sim = -1.0
                    if known_staff_enc:
                        staff_sims = _cos_sims(known_staff_enc, face_encodings[0])
                        best_staff_idx = int(np.argmax(staff_sims))
                        best_staff_sim = float(staff_sims[best_staff_idx])
                        s_name = known_staff_meta[best_staff_idx]['name']
                        s_id = known_staff_meta[best_staff_idx]['id']
                        
                        if best_staff_sim >= FACE_STAFF_THRESHOLD:
                            print(f"[FACE SCORE] Track #{track_id} -> Staff '{s_name}' (ID {s_id}) Score={best_staff_sim:.4f} (Threshold={FACE_STAFF_THRESHOLD}) -> MATCH ACCEPTED")
                            match_id = s_id
                            match_source = "staff"
                            matched_staff_meta = known_staff_meta[best_staff_idx]
                            
                            # Extract and save daily clothing color memory
                            color = _extract_dominant_color(body_crop)
                            if color is not None:
                                with self.lock:
                                    if datetime.now().date() != self.clothes_memory_date:
                                        self.staff_clothes_colors.clear()
                                        self.clothes_memory_date = datetime.now().date()
                                    self.staff_clothes_colors[s_id] = (color, s_name, matched_staff_meta.get("role", "None"))
                                    
                            # Update Re-ID appearance cache for this staff member
                            if body_reid_vec is not None:
                                with self.lock:
                                    self.reid_appearance_cache[s_id] = {
                                        "name": s_name, "db_id": s_id, "role": matched_staff_meta.get("role", "None"),
                                        "reid_vec": body_reid_vec, "last_seen": current_time, "is_staff": True
                                    }
                            
                            # CRITICAL: Prevent 2 people from claiming the same staff member simultaneously
                            can_assign_staff = True
                            with self.lock:
                                for other_tid, other_st in list(self.person_states.items()):
                                    if other_tid != track_id and other_st.get("db_id") == match_id and (current_time - other_st.get("last_active", 0)) < 8:
                                        other_sim = other_st.get("best_staff_sim", 0.0)
                                        if best_staff_sim > other_sim:
                                            print(f"[AI] Reassigning {s_name} from track {other_tid} (sim={other_sim:.3f}) to track {track_id} (sim={best_staff_sim:.3f})")
                                            other_st["db_id"] = None
                                            other_st["id"] = f"Track #{other_tid}"
                                            other_st["name"] = "Guest"
                                            other_st["role"] = "None"
                                            other_st["best_staff_sim"] = 0.0
                                        else:
                                            print(f"[AI] Track {track_id} matched {s_name} (sim={best_staff_sim:.3f}), but track {other_tid} has higher sim ({other_sim:.3f}) — rejecting duplicate")
                                            can_assign_staff = False
                                            break
                            
                            if can_assign_staff:
                                # MULTI-ANGLE LEARNING: Store new distinct face angles over time (up to 5)
                                s_meta_matched = known_staff_meta[best_staff_idx]
                                stored_list = s_meta_matched.get("all_encs", [])
                                if stored_list and best_staff_sim >= 0.38:
                                    sims_to_self = _cos_sims(stored_list, face_encodings[0])
                                    if float(np.max(sims_to_self)) < 0.85:
                                        stored_list.append(face_encodings[0])
                                        if len(stored_list) > 5:
                                            pair_sims = []
                                            for i in range(len(stored_list)):
                                                for j in range(i + 1, len(stored_list)):
                                                    sim_ij = float(np.dot(stored_list[i], stored_list[j]) / (np.linalg.norm(stored_list[i]) * np.linalg.norm(stored_list[j]) + 1e-6))
                                                    pair_sims.append((sim_ij, i, j))
                                            if pair_sims:
                                                pair_sims.sort(key=lambda x: x[0], reverse=True)
                                                stored_list.pop(pair_sims[0][2])
                                        database.update_staff_encodings(match_id, pickle.dumps(stored_list))
                                        s_meta_matched["all_encs"] = stored_list
                                        print(f"[AI MULTI-ANGLE] Learned new distinct face angle for Staff {s_meta_matched['name']} (total stored: {len(stored_list)}/5)")
                                
                                with self.lock:
                                    if track_id in self.person_states:
                                        s = self.person_states[track_id]
                                        # If the identity is the same, preserve the highest ever similarity to prevent weak false-positive thefts
                                        if s.get("db_id") == match_id:
                                            s["best_staff_sim"] = max(s.get("best_staff_sim", 0.0), best_staff_sim)
                                        else:
                                            s["best_staff_sim"] = best_staff_sim
                                            
                                        s["db_id"] = match_id
                                        s["id"] = f"ID: {match_id}"
                                        s["name"] = known_staff_meta[best_staff_idx]["name"]
                                        s["role"] = known_staff_meta[best_staff_idx]["role"]
                                        s["last_sync"] = current_time
                                        if track_id in self.customer_timers:
                                            del self.customer_timers[track_id]
                                try:
                                    database.record_attendance(match_id)
                                except Exception as eat:
                                    print(f"[AI] Attendance record error: {eat}")
                            else:
                                match_id = "Unknown"
                                match_source = None
                        else:
                            print(f"[FACE SCORE] Track #{track_id} -> Best Staff '{s_name}' Score={best_staff_sim:.4f} (Threshold={FACE_STAFF_THRESHOLD}) -> REJECTED")

                    best_cust_sim = -1.0
                    if match_id == "Unknown" and known_cust_enc:
                        c_sims = _cos_sims(known_cust_enc, face_encodings[0])
                        best_cust_idx = int(np.argmax(c_sims))
                        best_cust_sim = float(c_sims[best_cust_idx])
                        c_name = known_cust_meta[best_cust_idx]['name']
                        c_id_matched = known_cust_meta[best_cust_idx]['id']
                        
                        if best_cust_sim >= FACE_CUSTOMER_THRESHOLD:
                            print(f"[FACE SCORE] Track #{track_id} -> Customer '{c_name}' (ID {c_id_matched}) Score={best_cust_sim:.4f} (Threshold={FACE_CUSTOMER_THRESHOLD}) -> MATCH ACCEPTED")
                            match_id = f"CUST:{c_id_matched}"
                            match_source = "customer"
                            matched_cust_idx = best_cust_idx
                            
                            # Update Re-ID appearance cache for this returning guest
                            if body_reid_vec is not None:
                                with self.lock:
                                    self.reid_appearance_cache[f"C_{c_id_matched}"] = {
                                        "name": c_name, "db_id": f"C_{c_id_matched}", "role": "None",
                                        "reid_vec": body_reid_vec, "last_seen": current_time, "is_staff": False
                                    }
                            
                            # MULTI-ANGLE LEARNING: Store new distinct face angles for customer (up to 5)
                            c_stored_list = known_cust_meta[matched_cust_idx].get("all_encs", [])
                            if c_stored_list and best_cust_sim >= 0.38:
                                c_sims_to_self = _cos_sims(c_stored_list, face_encodings[0])
                                if float(np.max(c_sims_to_self)) < 0.85:
                                    c_stored_list.append(face_encodings[0])
                                    if len(c_stored_list) > 5:
                                        pair_sims = []
                                        for i in range(len(c_stored_list)):
                                            for j in range(i + 1, len(c_stored_list)):
                                                sim_ij = float(np.dot(c_stored_list[i], c_stored_list[j]) / (np.linalg.norm(c_stored_list[i]) * np.linalg.norm(c_stored_list[j]) + 1e-6))
                                                pair_sims.append((sim_ij, i, j))
                                        if pair_sims:
                                            pair_sims.sort(key=lambda x: x[0], reverse=True)
                                            c_stored_list.pop(pair_sims[0][2])
                                    import base64
                                    _, buffer = cv2.imencode('.jpg', face_crop)
                                    b64_photo = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
                                    database.update_customer_encoding(c_id_matched, pickle.dumps(c_stored_list), photo=b64_photo)
                                    known_cust_meta[matched_cust_idx]["all_encs"] = c_stored_list
                                    print(f"[AI MULTI-ANGLE] Learned new distinct face angle for Customer #{c_id_matched} (total stored: {len(c_stored_list)}/5)")

                # TIER 2: Person Re-ID Appearance Matching (When Face is Occluded / Steep Ceiling Angle)
                if match_id == "Unknown" and body_reid_vec is not None:
                    with self.lock:
                        # Purge Re-ID cache entries older than 15 minutes (900s)
                        self.reid_appearance_cache = {k: v for k, v in self.reid_appearance_cache.items() if current_time - v.get("last_seen", 0) < 900}
                        best_reid_match = None
                        best_reid_score = -1.0
                        for k, v in self.reid_appearance_cache.items():
                            cached_vec = v.get("reid_vec")
                            if cached_vec is not None:
                                sim = float(np.dot(cached_vec, body_reid_vec))
                                if sim > best_reid_score:
                                    best_reid_score = sim
                                    best_reid_match = v
                        
                        # Strict Re-ID Threshold: 0.82 (prevents confusion between coworkers in similar shirts)
                        if best_reid_match is not None and best_reid_score >= 0.82:
                            cand_id = best_reid_match["db_id"]
                            # STRICT UNIQUENESS: Do not assign if another active track currently has this staff ID
                            is_claimed = False
                            for other_tid, other_st in list(self.person_states.items()):
                                if other_tid != track_id and other_st.get("db_id") == cand_id and (current_time - other_st.get("last_active", 0)) < 8:
                                    is_claimed = True
                                    print(f"[RE-ID DUPLICATE PREVENTED] '{best_reid_match['name']}' already claimed by track #{other_tid} — rejecting track #{track_id}")
                                    break
                            
                            if not is_claimed:
                                match_id = cand_id
                                match_source = "reid_appearance"
                                best_reid_match["last_seen"] = current_time
                                best_reid_match["reid_vec"] = body_reid_vec
                                print(f"[RE-ID MATCH] Track #{track_id} -> Re-identified as '{best_reid_match['name']}' via Person Appearance (Score={best_reid_score:.4f}, Face Occluded/Ceiling Angle)")

                # TIER 3: Check short-term recent guest face memory (15-min rolling window)
                if match_id == "Unknown" and face_encodings:
                    recent_matched = False
                    with self.lock:
                        self.recent_guest_embeddings = [g for g in self.recent_guest_embeddings if current_time - g.get("last_seen", 0) < 900]
                        for g_info in self.recent_guest_embeddings:
                            g_encs = g_info.get("encs", [])
                            if g_encs:
                                r_sims = _cos_sims(g_encs, face_encodings[0])
                                if float(np.max(r_sims)) >= 0.40:
                                    match_id = g_info["db_id"] if g_info.get("db_id") else f"GUEST_REMEM:{g_info['name']}"
                                    match_source = "recent_guest"
                                    g_info["last_seen"] = current_time
                                    if float(np.max(r_sims)) < 0.85 and len(g_encs) < 5:
                                        g_encs.append(face_encodings[0])
                                    recent_matched = True
                                    print(f"[AI GUEST RE-LINK] Track #{track_id} matched returning guest '{g_info['name']}' (sim={float(np.max(r_sims)):.4f})")
                                    break

                    if match_id == "Unknown":
                        # Attempt fallback to Daily Clothing Memory for Staff
                        curr_color = _extract_dominant_color(body_crop)
                        if curr_color is not None:
                            best_col_score = 9999
                            best_col_match = None
                            with self.lock:
                                if datetime.now().date() == self.clothes_memory_date:
                                    for sid, (c_bgr, c_name, c_role) in self.staff_clothes_colors.items():
                                        dist = sum((c1 - c2)**2 for c1, c2 in zip(curr_color, c_bgr))**0.5
                                        if dist < best_col_score:
                                            best_col_score = dist
                                            best_col_match = (sid, c_name, c_role)
                            
                            # Strict color distance threshold (e.g. Euclidean < 15 in BGR space)
                            if best_col_match is not None and best_col_score < 15:
                                is_claimed = False
                                with self.lock:
                                    for other_tid, other_st in list(self.person_states.items()):
                                        if other_tid != track_id and other_st.get("db_id") == best_col_match[0] and (current_time - other_st.get("last_active", 0)) < 8:
                                            is_claimed = True
                                            break
                                if not is_claimed:
                                    match_id = best_col_match[0]
                                    match_source = "staff"
                                    matched_staff_meta = {"name": best_col_match[1] + " (By Clothes)", "role": best_col_match[2]}
                                    print(f"[CLOTHING MATCH] Track #{track_id} -> Re-identified as '{best_col_match[1]}' via Daily Clothing (Dist={best_col_score:.1f})")
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
                            elif winner.startswith("GUEST_REMEM:"):
                                g_name = winner.split(":", 1)[1]
                                state["id"] = g_name
                                state["name"] = g_name
                                state["last_sync"] = current_time
                            elif winner != "Unknown":
                                meta = next((m for m in self.known_face_metadata if m["id"] == winner), None)
                                if meta:
                                    # STRICT UNIQUENESS: Reject assignment if another active track already possesses this staff ID
                                    is_dup = False
                                    for other_tid, other_st in list(self.person_states.items()):
                                        if other_tid != track_id and other_st.get("db_id") == winner and (current_time - other_st.get("last_active", 0)) < 8:
                                            is_dup = True
                                            print(f"[AI CONSENSUS DUPLICATE PREVENTED] Staff '{meta['name']}' already assigned to track #{other_tid} — rejecting duplicate on track #{track_id}")
                                            break
                                    if not is_dup:
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
                                        # Protect identity by setting max similarity
                                        if state.get("db_id") == s_meta_q["id"]:
                                            state["best_staff_sim"] = max(state.get("best_staff_sim", 0.0), best_s_sim_q)
                                        else:
                                            state["best_staff_sim"] = best_s_sim_q
                                            
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
                        
                        # Rapid Guest Recognition: recognize non-staff in 2 checks (~200ms)
                        min_unknown_votes = 2
                        
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
                                    
                                    c_id_matched = known_cust_meta[best_cust_idx]['id']
                                    c_stored_list = known_cust_meta[best_cust_idx].get("all_encs", [])
                                    if c_stored_list and best_cust_sim >= 0.38:
                                        c_sims_to_self = _cos_sims(c_stored_list, face_encodings[0])
                                        if float(np.max(c_sims_to_self)) < 0.85:
                                            c_stored_list.append(face_encodings[0])
                                            if len(c_stored_list) > 5:
                                                pair_sims = []
                                                for i in range(len(c_stored_list)):
                                                    for j in range(i + 1, len(c_stored_list)):
                                                        sim_ij = float(np.dot(c_stored_list[i], c_stored_list[j]) / (np.linalg.norm(c_stored_list[i]) * np.linalg.norm(c_stored_list[j]) + 1e-6))
                                                        pair_sims.append((sim_ij, i, j))
                                                if pair_sims:
                                                    pair_sims.sort(key=lambda x: x[0], reverse=True)
                                                    c_stored_list.pop(pair_sims[0][2])
                                    else:
                                        c_stored_list = [face_encodings[0]]
                                    database.update_customer_encoding(c_id_matched, pickle.dumps(c_stored_list), photo=b64_photo)
                                    known_cust_meta[best_cust_idx]["all_encs"] = c_stored_list
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
                                # Robust New Identity Gate:
                                # Require persistence (>=6 consensus samples), minimum face size (>=75px),
                                # natural face aspect ratio, and blur check to prevent spurious registrations from motion blur.
                                consensus_count = len(self.recognition_consensus.get(track_id, []))
                                face_h, face_w = face_crop.shape[:2]
                                aspect_ratio = face_h / float(max(1, face_w))
                                
                                is_sharp = True
                                try:
                                    gray_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
                                    lap_var = cv2.Laplacian(gray_face, cv2.CV_64F).var()
                                    if lap_var < 20.0:  # Below 20 is blurry/motion-blurred
                                        is_sharp = False
                                except: pass
                                
                                if consensus_count >= 6 and face_h >= 75 and face_w >= 75 and (0.75 <= aspect_ratio <= 1.45) and is_sharp:
                                    # Convert face_crop to base64 photo
                                    import base64
                                    _, buffer = cv2.imencode('.jpg', face_crop)
                                    b64_photo = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
                                    
                                    new_c_id = database.register_customer(pickle.dumps([face_encodings[0]]), photo=b64_photo)
                                    print(f"[AI NEW FACE] Confirmed stable new customer profile created: ID {new_c_id} (samples={consensus_count}, size={face_w}x{face_h}, sharpness={lap_var:.1f})")
                                    self.load_known_faces()
                                    with self.lock:
                                        if track_id in self.person_states:
                                            state = self.person_states[track_id]
                                            state["db_id"] = f"C_{new_c_id}"
                                            state["id"] = f"GUEST #{new_c_id}"
                                            state["name"] = f"Guest #{new_c_id}"
                                            state["last_sync"] = current_time
                                            state["visits"] = 1
                                            state["photo"] = b64_photo
                                            self.recent_guest_embeddings.append({
                                                "name": f"Guest #{new_c_id}",
                                                "db_id": f"C_{new_c_id}",
                                                "encs": [face_encodings[0]],
                                                "last_seen": current_time
                                            })
                                else:
                                    with self.lock:
                                        if track_id in self.recognition_consensus:
                                            self.recognition_consensus[track_id].append("Unknown")
                                    print(f"[AI STABILITY GATE] Holding off new identity for track {track_id} (samples={consensus_count}/6, size={face_w}x{face_h}, sharp={is_sharp})")
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
            
            # Run YOLO with ByteTrack on the native camera frame.
            # - tracker="bytetrack.yaml": Activates ByteTrack Kalman filter motion tracker
            # - classes=[0]: STRICTLY tracks humans (class 0: person) to prevent boxing non-living objects
            # - conf=0.50: Conservative confidence threshold eliminating false positives on chairs/screens
            DETECTION_WIDTH = w_orig
            DETECTION_HEIGHT = h_orig
            small_frame = frame
            
            raw_boxes = []
            raw_track_ids = None
            raw_kps = None
            
            self.frame_count += 1
            if self.frame_count % 3 == 1:
                try:
                    results = model.track(
                        small_frame, 
                        persist=True, 
                        conf=0.22, 
                        iou=0.45,
                        verbose=False,
                        classes=[0],
                        imgsz=480
                    )
                except Exception:
                    # Fallback to direct model inference if tracking subsystem encounters any issue
                    results = model(small_frame, conf=0.22, iou=0.45, verbose=False, classes=[0], imgsz=480)
                
                if results and len(results) > 0 and results[0].boxes is not None and len(results[0].boxes) > 0:
                    raw_boxes = results[0].boxes.xyxy.cpu().numpy()
                    try:
                        if hasattr(results[0].boxes, 'id') and results[0].boxes.id is not None:
                            raw_track_ids = results[0].boxes.id.int().cpu().numpy()
                    except Exception:
                        raw_track_ids = None
    
                    try:
                        if hasattr(results[0], 'keypoints') and results[0].keypoints is not None and results[0].keypoints.xy is not None:
                            raw_kps = results[0].keypoints.xy.cpu().numpy()
                    except Exception:
                        raw_kps = None
                        
                    with self.lock:
                        self.last_valid_raw_boxes = raw_boxes
                        self.last_valid_track_ids = raw_track_ids
                        self.last_valid_raw_kps = raw_kps
                        
                        # Calculate velocities
                        if raw_track_ids is not None:
                            for idx, tid in enumerate(raw_track_ids):
                                box = raw_boxes[idx]
                                if tid in self.last_boxes:
                                    last = self.last_boxes[tid]
                                    dx = box[0] - last[0]
                                    dy = box[1] - last[1]
                                    
                                    # Deadzone (ignore YOLO micro-jitter when standing still)
                                    if abs(dx) < 5: dx = 0
                                    if abs(dy) < 5: dy = 0
                                    
                                    # dx is movement over 3 frames. Get per-frame velocity
                                    per_frame_dx = dx / 3.0
                                    per_frame_dy = dy / 3.0
                                    
                                    # Exponential Moving Average for smoothing
                                    if tid in self.velocities:
                                        old_dx, old_dy = self.velocities[tid]
                                        self.velocities[tid] = (0.5 * per_frame_dx + 0.5 * old_dx, 0.5 * per_frame_dy + 0.5 * old_dy)
                                    else:
                                        self.velocities[tid] = (per_frame_dx, per_frame_dy)
                                else:
                                    self.velocities[tid] = (0, 0)
                                self.last_boxes[tid] = box.copy()
                                
            else:
                # FRAME SKIPPED: Extrapolate boxes using velocities
                with self.lock:
                    if self.last_valid_raw_boxes is not None and len(self.last_valid_raw_boxes) > 0:
                        raw_boxes = np.copy(self.last_valid_raw_boxes)
                        raw_track_ids = self.last_valid_track_ids
                        raw_kps = self.last_valid_raw_kps
                        if raw_track_ids is not None:
                            for idx, tid in enumerate(raw_track_ids):
                                if tid in self.velocities:
                                    dx, dy = self.velocities[tid]
                                    raw_boxes[idx][0] += dx
                                    raw_boxes[idx][1] += dy
                                    raw_boxes[idx][2] += dx
                                    raw_boxes[idx][3] += dy
                                    
                                    # Shift keypoints if available
                                    if raw_kps is not None and idx < len(raw_kps) and raw_kps[idx] is not None:
                                        raw_kps[idx][:, 0] += dx
                                        raw_kps[idx][:, 1] += dy
                        self.last_valid_raw_boxes = raw_boxes

            # Detection boxes stay in native pixel space (scale = 1.0).
            scale_x = 1.0
            scale_y = 1.0
            
            if len(raw_boxes) > 0:
                boxes = []
                valid_kps = []
                track_ids = []
                
                with self.lock:
                    for b_idx, r_box in enumerate(raw_boxes):
                        x1, y1, x2, y2 = map(int, r_box)
                        # Reject unreasonably tiny boxes (< 25px)
                        if (x2 - x1) < 25 or (y2 - y1) < 30:
                            continue
                        
                        boxes.append(r_box)
                        if raw_kps is not None and b_idx < len(raw_kps):
                            valid_kps.append(raw_kps[b_idx])
                        else:
                            valid_kps.append(None)
                            
                        # Use Track ID or deterministic index
                        if raw_track_ids is not None and b_idx < len(raw_track_ids):
                            t_id = int(raw_track_ids[b_idx])
                        else:
                            t_id = b_idx + 1
                            
                        track_ids.append(t_id)
                        self.last_boxes[t_id] = [x1, y1, x2, y2]
                        self.last_positions[t_id] = (int((x1+x2)/2), int((y1+y2)/2))
                
                boxes = np.array(boxes, dtype=np.float32) if boxes else np.empty((0, 4), dtype=np.float32)
                track_ids = np.array(track_ids, dtype=np.int32) if track_ids else np.empty((0,), dtype=np.int32)
                all_kps = valid_kps
                
                # Process active tracks
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
                                "first_seen": current_time,
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

                    # Bidirectional Corridor Passage Counting (Top Glass Hallway)
                    from collections import deque
                    if track_id not in self.track_trajectories:
                        self.track_trajectories[track_id] = deque(maxlen=40)
                    self.track_trajectories[track_id].append((center[0], center[1], current_time))

                    # Check if movement is in the upper corridor area (Y <= 50% of frame height)
                    if center[1] <= int(h_orig * 0.50):
                        pts = list(self.track_trajectories[track_id])
                        if len(pts) >= 8 and track_id not in self.counted_passages:
                            x_start, x_end = pts[0][0], pts[-1][0]
                            delta_x = x_end - x_start
                            # 65px horizontal displacement indicates clear deliberate passage
                            if delta_x >= 65:
                                self.passage_counts["l_to_r"] += 1
                                self.counted_passages.add(track_id)
                                database.log_passage("L_TO_R", track_id)
                                print(f"[CORRIDOR PASSAGE] Track #{track_id} moved LEFT ➔ RIGHT (L->R: {self.passage_counts['l_to_r']}, R->L: {self.passage_counts['r_to_l']})")
                            elif delta_x <= -65:
                                self.passage_counts["r_to_l"] += 1
                                self.counted_passages.add(track_id)
                                database.log_passage("R_TO_L", track_id)
                                print(f"[CORRIDOR PASSAGE] Track #{track_id} moved RIGHT ➔ LEFT (L->R: {self.passage_counts['l_to_r']}, R->L: {self.passage_counts['r_to_l']})")
                    
                    # Pose & Action Analysis
                    keypoints = all_kps[i] if (all_kps is not None and i < len(all_kps)) else None
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
                        db_id = state.get("db_id")
                        is_identified = (db_id is not None and db_id != "Unknown")
                        is_processing = track_id in self.processing_tracks
                    
                    last_attempt = self.last_rec_attempt.get(track_id, 0)
                    
                    # Temporal Optimization:
                    # - Already-identified tracks: periodic re-verification/learning every 2.5s (15-20 frames)
                    # - Unidentified tracks: rapid sub-second verification every 0.35s
                    check_interval = 2.5 if is_identified else 0.35
                    if not is_processing and (current_time - last_attempt > check_interval):
                        self.last_rec_attempt[track_id] = current_time

                        face_img = None

                        # Compute scale from DETECTION (640x480) to face_source (native camera res)
                        fs_scale_x = fw / DETECTION_WIDTH
                        fs_scale_y = fh / DETECTION_HEIGHT

                        # Try precise face crop using YOLO keypoints (nose)
                        if all_kps is not None and i < len(all_kps) and all_kps[i] is not None:
                            kp = all_kps[i]
                            nose = kp[0]
                            if nose[0] > 0 and nose[1] > 0:
                                nose_x = int(nose[0] * fs_scale_x)
                                nose_y = int(nose[1] * fs_scale_y)
                                det_box_h = y2 - y1
                                face_size = max(int(det_box_h * fs_scale_y * 0.35), 80)
                                shift_up = int(face_size * 0.15)
                                x1f = max(0, nose_x - face_size)
                                y1f = max(0, nose_y - face_size - shift_up)
                                x2f = min(fw, nose_x + face_size)
                                y2f = min(fh, nose_y + face_size - shift_up)
                                if x2f > x1f and y2f > y1f:
                                    face_img = face_source[y1f:y2f, x1f:x2f]

                        # Fallback face crop: top 30% of detection bounding box
                        if face_img is None:
                            y1f = int(y1 * fs_scale_y)
                            y2f = int(y1f + (y2 - y1) * fs_scale_y * 0.35)
                            x_margin = int((x2 - x1) * fs_scale_x * 0.10)
                            x1f = max(0, int(x1 * fs_scale_x) - x_margin)
                            x2f = min(fw, int(x2 * fs_scale_x) + x_margin)
                            if x2f > x1f and y2f > y1f:
                                face_img = face_source[y1f:y2f, x1f:x2f]

                        # Extract full body crop for Person Re-ID (appearance embedding)
                        x1b = max(0, int(x1 * fs_scale_x))
                        y1b = max(0, int(y1 * fs_scale_y))
                        x2b = min(fw, int(x2 * fs_scale_x))
                        y2b = min(fh, int(y2 * fs_scale_y))
                        body_crop = face_source[y1b:y2b, x1b:x2b] if (x2b > x1b and y2b > y1b) else None

                        has_valid_face = face_img is not None and face_img.shape[0] >= 64 and face_img.shape[1] >= 64
                        has_valid_body = body_crop is not None and body_crop.shape[0] >= 80 and body_crop.shape[1] >= 40

                        if has_valid_face or has_valid_body:
                            with self.lock:
                                self.processing_tracks.add(track_id)
                            self.recognition_queue.put((
                                track_id, 
                                face_img.copy() if has_valid_face else None, 
                                body_crop.copy() if has_valid_body else None, 
                                current_zone, 
                                current_time
                            ))
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
                    
                    # RESTRICTED / SAFE ZONE MONITORING
                    in_unauth_zone = False
                    is_staff = db_id and not str(db_id).startswith("C_")
                    for zone in self.zones:
                        if zone.unauthorized_roles and zone.is_inside(center):
                            is_unauth = False
                            if role and role in zone.unauthorized_roles:
                                is_unauth = True
                            elif not is_staff and ("Customer" in zone.unauthorized_roles or "Guest" in zone.unauthorized_roles or "None" in zone.unauthorized_roles or "Unknown" in zone.unauthorized_roles or "All" in zone.unauthorized_roles or len(zone.unauthorized_roles) > 0):
                                is_unauth = True
                                
                            if is_unauth:
                                in_unauth_zone = True
                                if (track_id, zone.name) not in self.alerted_tracks:
                                    person_label = state.get("name", "Unknown Person")
                                    database.log_activity(db_id or f"Track_{track_id}", zone.name, "Security Alert", f"Unauthorized entry ({person_label}) detected in {zone.name}.")
                                    with self.lock:
                                        state["needs_security_email"] = zone.name
                                    self.alerted_tracks.add((track_id, zone.name))
                                    print(f"[SECURITY ALERT] Unauthorized entry by {person_label} in {zone.name}!")
                                break
                    
                    if not in_unauth_zone:
                        # Clear alerts for zones this track is no longer in
                        self.alerted_tracks = {(tid, zname) for tid, zname in self.alerted_tracks if tid != track_id}

                    # CUSTOMER INTELLIGENCE (Track every non-staff person as a customer)
                    if not is_staff:
                        if track_id not in self.customer_timers:
                            c_id = int(str(db_id).split("_")[1]) if db_id and str(db_id).startswith("C_") else None
                            self.customer_timers[track_id] = {"start": current_time, "zone": current_zone, "c_id": c_id}
                        elif db_id and str(db_id).startswith("C_") and self.customer_timers[track_id].get("c_id") is None:
                            self.customer_timers[track_id]["c_id"] = int(str(db_id).split("_")[1])
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
                        track_age = current_time - state.get("first_seen", current_time)
                        
                    if not db_id:
                        color_hex = "#f97316"  # Amber for Unknown
                        cv2_color = (6, 119, 217)
                        label = "HUMAN"
                    elif str(db_id).startswith("C_"):
                        visits = state.get("visits", 1)
                        cv2_color = (0, 215, 255) # Gold for Guests
                        if visits <= 1:
                            color_hex = "#f97316"  # Orange for New Customer (first visit)
                            label = "New Customer (1st visit)"
                        else:
                            color_hex = "#eab308"  # Yellow for Regular Guest
                            suffix = "th" if visits >= 4 else ({1:"st",2:"nd",3:"rd"}.get(visits, "th"))
                            label = f"Regular Customer ({visits}{suffix} visit)"
                    else:
                        color_hex = "#3b82f6"  # Blue for Enrolled Staff (Type 3)
                        cv2_color = (229, 70, 79) # Indigo for Staff
                        role_tag = f" ({state_role})" if state_role and state_role != "None" else ""
                        status = state.get("pose_label", "NEUTRAL")
                        label = f"STAFF: {state_name} [{status}]"
                    
                    # Draw Box overlay directly onto video stream frame
                    cv2.rectangle(output_frame, (int(x1), int(y1)), (int(x2), int(y2)), cv2_color, 2)
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                    cv2.rectangle(output_frame, (int(x1), int(y1) - th - 10), (int(x1) + tw + 10, int(y1)), cv2_color, -1)
                    cv2.putText(output_frame, label, (int(x1) + 5, int(y1) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

                    # Store last box in state for carry-forward during brief YOLO misses
                    state["last_box"] = [float(x1), float(y1), float(x2), float(y2)]
                    state["last_label"] = label
                    state["last_color"] = color_hex
                    # Compile detection metadata for canvas rendering
                    detections.append({
                        "track_id": int(track_id),
                        "staff_id": db_id if (db_id and not str(db_id).startswith("C_")) else None,
                        "box": state["last_box"],
                        "label": label,
                        "color": color_hex
                    })

            # STRICT 1-TO-1 DEDUPLICATION: Ensure no two boxes display the same staff identity
            staff_tracker = {}
            for d in detections:
                st_id = d.get("staff_id")
                if st_id:
                    tid = d.get("track_id")
                    if st_id in staff_tracker:
                        # Conflict! Demote duplicate track to Guest
                        print(f"[AI DEDUP] Multiple boxes claimed Staff ID {st_id} — demoting duplicate track #{tid} to Guest")
                        with self.lock:
                            if tid in self.person_states:
                                self.person_states[tid]["db_id"] = None
                                self.person_states[tid]["name"] = "Guest"
                                self.person_states[tid]["role"] = "None"
                                self.person_states[tid]["last_label"] = f"Guest #{tid}"
                                self.person_states[tid]["last_color"] = "#f97316"
                        d["label"] = f"Guest #{tid}"
                        d["color"] = "#f97316"
                        d["staff_id"] = None
                    else:
                        staff_tracker[st_id] = tid

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

    def get_passage_counts(self):
        """Returns today's cumulative Left-to-Right and Right-to-Left passage counts."""
        return dict(self.passage_counts)

def draw_detections_on_frame(frame, detections, src_w, src_h):
    if frame is None or not detections:
        return frame
    import cv2
    out_frame = frame.copy()
    fh, fw = out_frame.shape[:2]
    
    # Scale coordinates from native cam_ai resolution to the target frame resolution
    scale_x = fw / max(1.0, float(src_w))
    scale_y = fh / max(1.0, float(src_h))
    
    for det in detections:
        box = det.get('box')
        if not box or len(box) < 4: 
            continue
            
        x1 = int(box[0] * scale_x)
        y1 = int(box[1] * scale_y)
        x2 = int(box[2] * scale_x)
        y2 = int(box[3] * scale_y)
        
        hex_col = str(det.get('color', '#38bdf8')).lstrip('#')
        if len(hex_col) == 6:
            r, g, b = int(hex_col[:2], 16), int(hex_col[2:4], 16), int(hex_col[4:6], 16)
            bgr_col = (b, g, r)
        else:
            bgr_col = (248, 189, 56)
            
        cv2.rectangle(out_frame, (x1, y1), (x2, y2), bgr_col, 2)
        
        label = str(det.get('label', 'Detecting...'))
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        
        ly = max(y1 - 10, th + 10)
        cv2.rectangle(out_frame, (x1, ly - th - 10), (x1 + tw + 10, ly), bgr_col, -1)
        cv2.putText(out_frame, label, (x1 + 5, ly - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        
    return out_frame

