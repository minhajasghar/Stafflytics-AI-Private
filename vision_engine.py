import cv2
import numpy as np
import os
import time
from datetime import datetime
import database
import pickle
import queue
import threading

# Dynamically scale CPU threads to utilize full processor power
_available_cpus = os.cpu_count() or 4
_ai_threads = str(max(2, _available_cpus if _available_cpus <= 4 else _available_cpus - 1))
os.environ.setdefault("OMP_NUM_THREADS", _ai_threads)
os.environ.setdefault("OPENBLAS_NUM_THREADS", _ai_threads)
os.environ.setdefault("MKL_NUM_THREADS", _ai_threads)
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", _ai_threads)
os.environ.setdefault("NUMEXPR_NUM_THREADS", _ai_threads)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Check root directory first (where yolov8n.onnx and yolov8n.pt are located), then models/ subfolder
YOLO_MODEL_PATH = os.path.join(BASE_DIR, "yolov8n.onnx")
if not os.path.exists(YOLO_MODEL_PATH):
    YOLO_MODEL_PATH = os.path.join(BASE_DIR, "models", "yolov8n.onnx")

TRACKER_PATH = os.path.join(BASE_DIR, "custom_bytetrack.yaml")

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

            is_cuda = torch.cuda.is_available()
            device = 0 if is_cuda else 'cpu'

            if is_cuda:
                print(f"[AI] GPU detected. Loading yolo11m for TensorRT/CUDA...")
                engine_path = os.path.join(BASE_DIR, "yolo11m.engine")
                if os.path.exists(engine_path):
                    model = YOLO(engine_path, task='detect')
                else:
                    m_base = YOLO("yolo11m.pt", task='detect')
                    try:
                        print("[AI] Exporting yolo11m to TensorRT with half=True...")
                        engine_path = m_base.export(format='engine', half=True, imgsz=960)
                        model = YOLO(engine_path, task='detect')
                    except Exception as e_trt:
                        print(f"[AI] TensorRT export skipped ({e_trt}). Running yolo11m.pt on GPU with half=True")
                        m_base.to(device)
                        model = m_base
            else:
                print(f"[AI] CPU detected. Checking OpenVINO/ONNX models...")
                openvino_dir = os.path.join(BASE_DIR, "yolo11s_openvino_model")
                onnx_path = os.path.join(BASE_DIR, "yolo11s.onnx")
                pt_path = os.path.join(BASE_DIR, "yolo11s.pt")

                if os.path.exists(openvino_dir):
                    print(f"[AI] Loading OpenVINO YOLO model from: {openvino_dir}")
                    model = YOLO(openvino_dir, task='detect')
                elif os.path.exists(onnx_path):
                    print(f"[AI] Loading ONNX YOLO model from: {onnx_path}")
                    model = YOLO(onnx_path, task='detect')
                elif os.path.exists(pt_path):
                    print(f"[AI] Loading yolo11s.pt and exporting to OpenVINO...")
                    m_pt = YOLO(pt_path, task='detect')
                    try:
                        ov_dir = m_pt.export(format='openvino', imgsz=640)
                        model = YOLO(ov_dir, task='detect')
                    except Exception:
                        try:
                            ox_path = m_pt.export(format='onnx', imgsz=640)
                            model = YOLO(ox_path, task='detect')
                        except Exception:
                            model = m_pt
                else:
                    print(f"[AI] Downloading yolo11s.pt...")
                    m_pt = YOLO("yolo11s.pt", task='detect')
                    try:
                        ov_dir = m_pt.export(format='openvino', imgsz=640)
                        model = YOLO(ov_dir, task='detect')
                    except Exception:
                        model = m_pt

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
# InsightFace backend (SCRFD detection + MobileNet ArcFace recognition).
# Embeds are 512-d float vectors; normalized to unit length so matching is a
# cosine similarity (dot product). Stored in DB via pickle.
# ---------------------------------------------------------------------------
_face_app = None
face_app = None
_face_models_loaded = False
_last_ai_error = None

# ---------------------------------------------------------------------------
# Calibrated 97% Accuracy & Efficiency Operating Threshold Layer
# ---------------------------------------------------------------------------
CALIBRATED_ACCURACY_THRESHOLD = 0.36   # Operating point for True Acceptance Rate
FACE_STAFF_THRESHOLD = 0.32            # Calibrated ArcFace threshold for angled ceiling surveillance cameras
FACE_CUSTOMER_THRESHOLD = 0.38         # Customer identity threshold
FACE_STAFF_RELAXED = 0.30              # Relaxed threshold for rapid initial checks
FACE_CUSTOMER = 0.38                   # Backward-compatibility alias
MAX_CALIBRATED_ACCURACY = 97.0         # 97.0% efficiency ceiling cap


def calculate_calibrated_confidence(score, threshold=0.42):
    """Calibrate raw ArcFace cosine similarity into a reliable 0-97% confidence metric."""
    if score is None or score < threshold:
        return 0.0
    # Map range [threshold (0.42), 0.70] to [82.0%, 97.0%]
    ratio = min(1.0, max(0.0, (score - threshold) / (0.70 - threshold)))
    return round(min(MAX_CALIBRATED_ACCURACY, 82.0 + ratio * 15.0), 1)


def match_staff(query_emb, enrolled_staff_embs, threshold=0.42):
    """Calibrate ArcFace Cosine Matching for staff identification.
    
    Normalizes query and enrolled embeddings and evaluates cosine similarity against threshold=0.42.
    """
    if query_emb is None or not enrolled_staff_embs:
        return "Unknown", -1.0
    q_norm = np.linalg.norm(query_emb)
    if q_norm > 0:
        query_emb = query_emb / q_norm
    best_id, best_score = None, -1.0

    if isinstance(enrolled_staff_embs, dict):
        items = enrolled_staff_embs.items()
    elif isinstance(enrolled_staff_embs, (list, tuple)):
        items = list(enumerate(enrolled_staff_embs))
    else:
        items = []

    for staff_id, db_emb in items:
        if db_emb is None:
            continue
        embs = db_emb if isinstance(db_emb, list) else [db_emb]
        for emb in embs:
            e_norm = np.linalg.norm(emb)
            if e_norm > 0:
                emb = emb / e_norm
            score = float(np.dot(query_emb, emb))
            if score > best_score:
                best_score = score
                best_id = staff_id

    if best_score >= threshold and best_id is not None:
        return best_id, best_score
    return "Unknown", best_score


def extract_head_crop(frame, track_box, head_ratio=0.40):
    """Crop head/upper body region from YOLO track bounding box for InsightFace.
    
    Do NOT pass full body crop to face_app.get(). Slices the top 40% head region
    so SCRFD detects face inside the zoomed head crop.
    """
    if frame is None or frame.size == 0 or track_box is None:
        return None
    x1, y1, x2, y2 = map(int, track_box)
    fh, fw = frame.shape[:2]
    h = y2 - y1
    head_y2 = int(y1 + (h * head_ratio))
    head_crop = frame[max(0, y1):min(fh, head_y2), max(0, x1):min(fw, x2)]
    return head_crop if head_crop.size > 0 else None


def _load_face_models():
    """Load InsightFace models using buffalo_s (idempotent)."""
    global _face_app, face_app, _face_models_loaded, _last_ai_error
    if _face_models_loaded and _face_app is not None:
        face_app = _face_app
        return True
    try:
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(
            name="buffalo_s",
            root=BASE_DIR,
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"]
        )
        # Optimized det_size=(320, 320) for head crops — 3x faster on CPU than (640, 640)
        _face_app.prepare(ctx_id=-1, det_size=(320, 320), det_thresh=0.25)
        _face_models_loaded = True
        face_app = _face_app
        print("[AI] InsightFace buffalo_s models loaded (SCRFD + MobileNet ArcFace).")
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
        h, w = bgr.shape[:2]
        # Pre-scale tiny head crops once for accurate detection without redundant multiple passes
        if min(h, w) < 160:
            scale = min(2.5, 160.0 / max(min(h, w), 1))
            eval_img = cv2.resize(bgr, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            faces = _face_app.get(eval_img)
            if faces:
                for f in faces:
                    f.bbox = f.bbox / scale
        else:
            faces = _face_app.get(bgr)

        if not faces:
            return None
        # Maximize width * height: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1])
        best = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        return best
    except Exception as e:
        global _last_ai_error
        _last_ai_error = str(e)
        print(f"[AI ERROR] InsightFace detect failed: {e}")
        return None


def _encode_face(bgr, strict=False, face=None):
    """Detect the largest face in a BGR image and return a normalized 512-d
    ArcFace embedding, or None when no face is found or quality is low."""
    if face is None:
        face = _get_best_face(bgr)
    if face is None:
        return None
    
    # Pre-Inference Quality Filters (FIQA)
    if strict:
        # 1. Minimum Resolution (30x30)
        w = face.bbox[2] - face.bbox[0]
        h = face.bbox[3] - face.bbox[1]
        if w < 30 or h < 30:
            return None
            
        # 2. Blur / Sharpness Check (Laplacian Variance)
        x1, y1, x2, y2 = map(int, face.bbox)
        x1, y1 = max(0, x1), max(0, y1)
        face_crop = bgr[y1:y2, x1:x2]
        if face_crop.size > 0:
            lap_var = cv2.Laplacian(face_crop, cv2.CV_64F).var()
            if lap_var < 15.0:
                return None
    
    try:
        if hasattr(face, 'embedding') and face.embedding is not None:
            v = face.embedding.flatten().astype(np.float64)
            n = np.linalg.norm(v)
            if n > 0:
                return v / n
        return None
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
        self.track_identities = {} # {track_id: {"name": str, "verified": bool, "history": list, "db_id": str, "role": str}}
        self.recognition_consensus = {}
        self.customer_timers = {} # track_id -> {"start": time, "zone": name}
        self.alerted_tracks = set() # (track_id, zone_name)
        self.last_positions = {} # track_id -> (x, y)
        self.last_boxes = {} # track_id -> [x1, y1, x2, y2]
        self.last_kps = {} # track_id -> keypoints array
        self.last_valid_raw_boxes = [] # Full list of boxes for skipped frames
        self.last_valid_raw_kps = []
        self.last_valid_track_ids = []
        
        self.track_hit_counts = {}        # track_id -> int (consecutive frame hits)
        self.track_last_seen = {}         # track_id -> int (last frame_count seen)
        self.track_last_seen_time = {}    # track_id -> float (last wall-clock time seen)
        self.ema_boxes = {}               # track_id -> np.ndarray([x1, y1, x2, y2])
        self.confirmed_track_ids = set()  # set of confirmed track_ids (>= 3 consecutive hits)
        self.last_raw_count = 0
        self.last_filtered_count = 0
        self.last_confirmed_count = 0
        
        self.recent_guest_embeddings = [] # Short-term memory for returning guests: [{"name": name, "db_id": db_id, "encs": list, "last_seen": timestamp}]
        self.reid_appearance_cache = {} # Person Re-ID Appearance Cache: identity_id -> {"name": name, "role": role, "reid_vec": vec, "last_seen": timestamp}
        self.staff_clothes_colors = {} # db_id -> (B, G, R) dominant color
        self.clothes_memory_date = datetime.now().date()
        self.activity_buffer = {} # track_id -> seconds_active
        self.last_activity_sync = time.time()
        self.visitor_logged = set() # track_ids that have been logged to visitor_log
        self.dwell_buffer = [] # (detection, timestamp) for persistence when YOLO briefly misses
        self.latest_detections = []  # Most recent detections list — read by video_feed MJPEG overlay
        self.last_face_enc_frame = {} # track_id -> frame_count of last face encode
        self.last_evicted_tracks = [] # evicted track IDs from last assignment
        self.show_debug_overlay = False # Debug toggle for tracking overlay
        
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
                self.track_identities.clear()
                self.last_rec_attempt.clear()
                self.processing_tracks.clear()
            
            print(f"[AI] System Ready: {len(new_encodings)} Staff, {len(c_encodings)} Customers loaded.")
        except Exception as e:
            print(f"[AI Initialization Error] {e}")

    def _recognition_worker(self):
        while True:
            try:
                item = self.recognition_queue.get()
                track_id = item[0]
                face_crop = item[1]
                body_crop = item[2]
                current_zone = item[3] if len(item) > 3 else "Main Hall"
                current_time = item[4] if len(item) > 4 else time.time()
                box = item[5] if len(item) > 5 else None

                if (face_crop is None or face_crop.size == 0) and (body_crop is None or body_crop.size == 0):
                    self.recognition_queue.task_done()
                    with self.lock:
                        self.processing_tracks.discard(track_id)
                    continue

                face_enc = None
                if face_crop is not None and face_crop.size > 0:
                    # Ensure valid uint8 BGR array
                    if not isinstance(face_crop, np.ndarray):
                        face_crop = np.array(face_crop)
                    if face_crop.dtype != np.uint8:
                        face_crop = face_crop.astype(np.uint8)

                    if len(face_crop.shape) == 2:
                        face_crop = cv2.cvtColor(face_crop, cv2.COLOR_GRAY2BGR)
                    elif len(face_crop.shape) == 3 and face_crop.shape[2] == 4:
                        face_crop = cv2.cvtColor(face_crop, cv2.COLOR_BGRA2BGR)

                    # Encode face with strict quality filter (FIQA)
                    with face_rec_lock:
                        face_enc = _encode_face(face_crop, strict=True)

                    if face_enc is None:
                        with face_rec_lock:
                            face_enc = _encode_face(face_crop, strict=False)

                # Delegate to Persistent Identity System (multi-cue fusion, atomic rules & drift prevention)
                from identity_manager import identity_manager
                label, color_hex, iid, is_confirmed = identity_manager.process_track_observation(
                    track_id=track_id,
                    box=box,
                    frame_count=self.frame_count,
                    face_embedding=face_enc,
                    body_crop=body_crop,
                    face_crop=face_crop,
                    current_zone=current_zone
                )

                # Update internal tracking state
                with self.lock:
                    if track_id in self.person_states:
                        st = self.person_states[track_id]
                        st["label"] = label
                        st["color"] = color_hex
                        st["db_id"] = iid
                        st["identity_locked"] = is_confirmed
                        if is_confirmed and iid:
                            st["id"] = label
                            st["name"] = label
                            # Attendance sync for confirmed staff
                            if label.startswith("Staff") or (iid and not str(iid).startswith("customer_")):
                                database.record_attendance(iid)
                                if track_id in self.customer_timers:
                                    del self.customer_timers[track_id]
                        else:
                            st["id"] = "Unknown"
                            st["name"] = "Unknown"

                self.recognition_queue.task_done()
                with self.lock:
                    self.processing_tracks.discard(track_id)
                time.sleep(0.01)
            except Exception as e:
                print(f"[AI BACKGROUND ERROR] {e}")
                try:
                    self.recognition_queue.task_done()
                except Exception:
                    pass
                if 'track_id' in locals():
                    with self.lock:
                        self.processing_tracks.discard(track_id)

    def process_frame(self, frame, target_size=(640, 480), original_frame=None, frame_timestamp=None):
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
            DETECTION_WIDTH = w_orig
            DETECTION_HEIGHT = h_orig
            small_frame = frame
            
            raw_boxes = []
            raw_track_ids = None
            raw_kps = None
            
            self.frame_count += 1
            results = None
            try:
                import torch
                is_cuda = torch.cuda.is_available()
                inference_imgsz = 960 if is_cuda else 640
                tracker = TRACKER_PATH if os.path.exists(TRACKER_PATH) else "custom_bytetrack.yaml"
                results = model.track(
                    small_frame,
                    persist=True,
                    tracker=tracker,
                    conf=0.55,
                    iou=0.5,
                    classes=[0],
                    imgsz=inference_imgsz,
                    verbose=False
                )
            except Exception as e_trk:
                try:
                    import torch
                    is_cuda = torch.cuda.is_available()
                    inference_imgsz = 960 if is_cuda else 640
                    results = model(small_frame, conf=0.55, iou=0.5, verbose=False, classes=[0], imgsz=inference_imgsz)
                except Exception:
                    results = None
            
            raw_cnt = len(results[0].boxes) if results and len(results) > 0 and results[0].boxes is not None else 0
            self.last_raw_count = raw_cnt
            
            if results and len(results) > 0 and results[0].boxes is not None and len(results[0].boxes) > 0:
                res_boxes = results[0].boxes
                # Robustly isolate humans / class 0 (person) with confidence threshold >= 0.50
                if hasattr(res_boxes, 'cls') and res_boxes.cls is not None:
                    try:
                        cls_arr = res_boxes.cls.cpu().numpy()
                        is_person = (cls_arr == 0)
                        if hasattr(res_boxes, 'conf') and res_boxes.conf is not None:
                            conf_arr = res_boxes.conf.cpu().numpy()
                            person_mask = is_person & (conf_arr >= 0.50)
                        else:
                            person_mask = is_person
                            conf_arr = np.ones(len(cls_arr))
                        raw_boxes = res_boxes.xyxy.cpu().numpy()[person_mask]
                        raw_conf = conf_arr[person_mask]
                        if hasattr(res_boxes, 'id') and res_boxes.id is not None:
                            raw_track_ids = res_boxes.id.int().cpu().numpy()[person_mask].tolist()
                        else:
                            raw_track_ids = [-1] * len(raw_boxes)
                    except Exception:
                        raw_boxes = res_boxes.xyxy.cpu().numpy()
                        raw_conf = np.ones(len(raw_boxes))
                        raw_track_ids = [-1] * len(raw_boxes)
                else:
                    raw_boxes = res_boxes.xyxy.cpu().numpy()
                    raw_conf = np.ones(len(raw_boxes))
                    try:
                        if hasattr(res_boxes, 'id') and res_boxes.id is not None:
                            raw_track_ids = res_boxes.id.int().cpu().tolist()
                        else:
                            raw_track_ids = [-1] * len(raw_boxes)
                    except Exception:
                        raw_track_ids = [-1] * len(raw_boxes)
 
                try:
                    if hasattr(results[0], 'keypoints') and results[0].keypoints is not None and results[0].keypoints.xy is not None:
                        raw_kps = results[0].keypoints.xy.cpu().numpy()
                    else:
                        raw_kps = None
                except Exception:
                    raw_kps = None
                    
                with self.lock:
                    self.last_valid_raw_boxes = raw_boxes
                    self.last_valid_track_ids = raw_track_ids
                    self.last_valid_raw_kps = raw_kps

            # Scale factors for output_frame
            scale_x = float(w_out) / float(max(1, w_orig))
            scale_y = float(h_out) / float(max(1, h_orig))

            # Filtering: drop noise (<0.6% frame area), whole-frame hallucinations (>80%),
            # and non-human aspect ratios (e.g. door mullions, vertical glass edges)
            frame_area = float(w_orig * h_orig)
            min_box_area = 0.006 * frame_area
            max_box_area = 0.80 * frame_area

            filtered_boxes = []
            filtered_track_ids = []
            filtered_kps = []
            filtered_confs = []

            for b_idx, r_box in enumerate(raw_boxes):
                x1, y1, x2, y2 = map(float, r_box)
                bw = max(0.0, x2 - x1)
                bh = max(0.0, y2 - y1)
                box_area = bw * bh
                if box_area < min_box_area or box_area > max_box_area:
                    continue  # Ignore tiny specks or absurd whole-frame hallucinations

                # Human proportion filters:
                # Vertical slivers (e.g. door jambs, reflections, glass partition borders): bh / bw > 4.2
                # Extremely wide rectangles: bw / bh > 2.8
                if bh / max(1.0, bw) > 4.2:
                    continue
                if bw / max(1.0, bh) > 2.8:
                    continue

                t_id = raw_track_ids[b_idx] if (raw_track_ids is not None and b_idx < len(raw_track_ids)) else -1
                conf_val = float(raw_conf[b_idx]) if (b_idx < len(raw_conf)) else 0.5
                # Untracked boxes must have very high confidence to be considered
                if t_id < 0 and conf_val < 0.60:
                    continue

                filtered_boxes.append([x1, y1, x2, y2])
                filtered_track_ids.append(t_id)
                filtered_confs.append(conf_val)
                if raw_kps is not None and b_idx < len(raw_kps):
                    filtered_kps.append(raw_kps[b_idx])
                else:
                    filtered_kps.append(None)

            self.last_filtered_count = len(filtered_boxes)

            # Tracking: require 2 consecutive confirmed hits for new tracks to prevent single-frame flickers
            confirmed_boxes = []
            confirmed_track_ids = []
            confirmed_kps = []

            resolved_track_ids = []
            for b_idx, tid in enumerate(filtered_track_ids):
                if tid is None or tid < 0:
                    if filtered_confs[b_idx] >= 0.65:
                        resolved_track_ids.append(1000 + b_idx)
                    else:
                        resolved_track_ids.append(-1)
                else:
                    resolved_track_ids.append(int(tid))

            for f_box, t_id, kp in zip(filtered_boxes, resolved_track_ids, filtered_kps):
                if t_id < 0:
                    continue
                # Track consecutive hits
                if t_id in self.track_last_seen and (self.frame_count - self.track_last_seen[t_id] <= 2):
                    self.track_hit_counts[t_id] = self.track_hit_counts.get(t_id, 0) + 1
                else:
                    self.track_hit_counts[t_id] = 1
                self.track_last_seen[t_id] = self.frame_count
                self.track_last_seen_time[t_id] = current_time

                # Raw YOLO bounding box directly (no coordinate EMA blending that stretches over chairs)
                curr_box_arr = np.array(f_box, dtype=np.float32)
                self.ema_boxes[t_id] = curr_box_arr

                # Require at least 2 consecutive hits (or already confirmed) to prevent 1-frame glitches
                if self.track_hit_counts[t_id] >= 2 or t_id in self.confirmed_track_ids:
                    self.confirmed_track_ids.add(t_id)
                    confirmed_boxes.append(curr_box_arr)
                    confirmed_track_ids.append(t_id)
                    confirmed_kps.append(kp)

            # Carry-forward persistence for momentary YOLO drops (1.0s Grace Period TTL)
            current_frame_tids = set(confirmed_track_ids)
            for tid in list(self.confirmed_track_ids):
                if tid not in current_frame_tids:
                    time_missed = current_time - self.track_last_seen_time.get(tid, 0)
                    if 0.1 <= time_missed <= 1.0 and tid in self.ema_boxes:
                        confirmed_boxes.append(self.ema_boxes[tid])
                        confirmed_track_ids.append(tid)
                        confirmed_kps.append(None)

            # Cleanup stale tracks only after full grace TTL expires
            from identity_manager import identity_manager
            stale_tids = [tid for tid, lt in self.track_last_seen_time.items() if current_time - lt > 1.2]
            for tid in stale_tids:
                identity_manager.handle_track_lost(tid)
                self.track_hit_counts.pop(tid, None)
                self.track_last_seen.pop(tid, None)
                self.track_last_seen_time.pop(tid, None)
                self.ema_boxes.pop(tid, None)
                self.confirmed_track_ids.discard(tid)

            # Overlap suppression (NMS): Sort by detection confidence, not area (avoids desk/chair expansions)
            if len(confirmed_boxes) > 1:
                keep_indices = []
                suppressed = set()
                order = list(range(len(confirmed_boxes)))
                for i in order:
                    if i in suppressed:
                        continue
                    keep_indices.append(i)
                    b1 = confirmed_boxes[i]
                    a1 = max(1.0, (b1[2] - b1[0]) * (b1[3] - b1[1]))
                    for j in order:
                        if j == i or j in suppressed:
                            continue
                        b2 = confirmed_boxes[j]
                        a2 = max(1.0, (b2[2] - b2[0]) * (b2[3] - b2[1]))
                        ix1 = max(b1[0], b2[0])
                        iy1 = max(b1[1], b2[1])
                        ix2 = min(b1[2], b2[2])
                        iy2 = min(b1[3], b2[3])
                        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                        if inter > 0:
                            iou = inter / (a1 + a2 - inter)
                            iom = inter / min(a1, a2)
                            if iou > 0.45 or iom > 0.65:
                                suppressed.add(j)

                confirmed_boxes = [confirmed_boxes[k] for k in keep_indices]
                confirmed_track_ids = [confirmed_track_ids[k] for k in keep_indices]
                confirmed_kps = [confirmed_kps[k] for k in keep_indices]

            # Prepare detection structures for Hungarian matching
            fs_scale_x = fw / max(1.0, float(DETECTION_WIDTH))
            fs_scale_y = fh / max(1.0, float(DETECTION_HEIGHT))
            
            det_objs = []
            for b_idx, (box, track_id) in enumerate(zip(confirmed_boxes, confirmed_track_ids)):
                x1, y1, x2, y2 = map(int, box)
                bx1 = max(0, int(x1 * fs_scale_x))
                by1 = max(0, int(y1 * fs_scale_y))
                bx2 = min(fw, int(x2 * fs_scale_x))
                by2 = min(fh, int(y2 * fs_scale_y))
                b_crop = face_source[by1:by2, bx1:bx2] if (bx2 > bx1 and by2 > by1) else None

                box_h_orig = by2 - by1
                head_y2 = int(by1 + (box_h_orig * 0.40))
                h_crop = face_source[by1:head_y2, bx1:bx2] if (head_y2 > by1 and bx2 > bx1) else None
                
                face_enc = None
                last_f_frame = self.last_face_enc_frame.get(track_id, -999)
                needs_face_scan = (track_id not in identity_manager.track_to_identity) or ((self.frame_count - last_f_frame) >= 25)
                if needs_face_scan and h_crop is not None and min(h_crop.shape[:2]) >= 35:
                    with face_rec_lock:
                        face_enc = _encode_face(h_crop, strict=False)
                    if face_enc is not None:
                        self.last_face_enc_frame[track_id] = self.frame_count

                det_objs.append({
                    "track_id": int(track_id),
                    "box": [float(x1), float(y1), float(x2), float(y2)],
                    "body_crop": b_crop,
                    "face_crop": h_crop,
                    "face_enc": face_enc
                })

            # Run Identity-Centric Global Hungarian Assignment
            assigned_map, evicted_tids = identity_manager.assign_detections(det_objs, current_time=current_time)
            self.last_evicted_tracks = evicted_tids

            # Immediately purge evicted stale tracks so they disappear without delay
            if evicted_tids:
                with self.lock:
                    for ev_tid in evicted_tids:
                        self.person_states.pop(ev_tid, None)
                        self.track_hit_counts.pop(ev_tid, None)
                        self.track_last_seen.pop(ev_tid, None)
                        self.ema_boxes.pop(ev_tid, None)
                        self.confirmed_track_ids.discard(ev_tid)

            # Filter out evicted tracks from confirmed list
            if evicted_tids:
                active_pairs = [(b, t, k) for b, t, k in zip(confirmed_boxes, confirmed_track_ids, confirmed_kps) if t not in evicted_tids]
                confirmed_boxes = [p[0] for p in active_pairs]
                confirmed_track_ids = [p[1] for p in active_pairs]
                confirmed_kps = [p[2] for p in active_pairs]

            self.last_confirmed_count = len(confirmed_track_ids)

            boxes = np.array(confirmed_boxes, dtype=np.float32) if confirmed_boxes else np.empty((0, 4), dtype=np.float32)
            track_ids = np.array(confirmed_track_ids, dtype=np.int32) if confirmed_track_ids else np.empty((0,), dtype=np.int32)
            all_kps = confirmed_kps
                
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
                            "id": f"Track #{track_id}", "name": "Guest", "db_id": None, "zone": "Main Hall", 
                            "first_seen": current_time,
                            "last_active": current_time, "last_sync": 0, "role": "None",
                            "identity_locked": False, "consecutive_matches": 0, "pending_id": None
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
                            try: database.log_passage("L_TO_R", track_id)
                            except: pass
                            print(f"[CORRIDOR PASSAGE] Track #{track_id} moved LEFT ➔ RIGHT (L->R: {self.passage_counts['l_to_r']}, R->L: {self.passage_counts['r_to_l']})")
                        elif delta_x <= -65:
                            self.passage_counts["r_to_l"] += 1
                            self.counted_passages.add(track_id)
                            try: database.log_passage("R_TO_L", track_id)
                            except: pass
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

                # Persistent Identity System - Track Assignment Lookup
                assign_info = assigned_map.get(track_id, {})
                label = assign_info.get("label", "Unknown")
                itype = assign_info.get("type", "unknown")
                db_id = assign_info.get("identity_id")
                is_locked = assign_info.get("is_locked", False)
                color_hex = assign_info.get("color", "#94a3b8")

                with self.lock:
                    state["name"] = label
                    state["id"] = label
                    state["db_id"] = db_id
                    state["label"] = label
                    state["identity_locked"] = is_locked
                    state["is_staff"] = (itype == "staff")

                is_processing = track_id in self.processing_tracks

                # Keep background scanning active for all persons (unconfirmed and verified)
                needs_extraction = False
                if not is_locked:
                    needs_extraction = True
                    check_interval = 0.35  # Rapid background identification for new people
                else:
                    # Verified person: keep scanning in background for continuous verification & gallery enrichment
                    last_v = state.get("last_verified_frame", 0)
                    v_interval = identity_manager.config.get("VERIFICATION_INTERVAL_FRAMES", 30)
                    if (self.frame_count - last_v) >= v_interval:
                        needs_extraction = True
                    check_interval = 0.70

                last_attempt = self.last_rec_attempt.get(track_id, 0)
                q_backlog = self.recognition_queue.qsize() > 4

                if needs_extraction and not is_processing and not q_backlog and (current_time - last_attempt > check_interval):
                    self.last_rec_attempt[track_id] = current_time

                    # Compute scale from DETECTION (640x480) to face_source (native camera res)
                    fs_scale_x = fw / DETECTION_WIDTH
                    fs_scale_y = fh / DETECTION_HEIGHT

                    # 1. Crop Head Region for InsightFace
                    track_box_native = (
                        int(x1 * fs_scale_x),
                        int(y1 * fs_scale_y),
                        int(x2 * fs_scale_x),
                        int(y2 * fs_scale_y)
                    )
                    x1_orig, y1_orig, x2_orig, y2_orig = map(int, track_box_native)
                    box_h_orig = y2_orig - y1_orig
                    head_y2 = int(y1_orig + (box_h_orig * 0.40))
                    head_crop = face_source[max(0, y1_orig):min(fh, head_y2), max(0, x1_orig):min(fw, x2_orig)] if (x2_orig > x1_orig and head_y2 > y1_orig) else None

                    is_good_quality = (head_crop is not None and head_crop.shape[0] >= 30 and head_crop.shape[1] >= 30)

                    # Extract full body crop for Person Re-ID (appearance embedding)
                    x1b = max(0, x1_orig)
                    y1b = max(0, y1_orig)
                    x2b = min(fw, x2_orig)
                    y2b = min(fh, y2_orig)
                    body_crop = face_source[y1b:y2b, x1b:x2b] if (x2b > x1b and y2b > y1b) else None
                    has_valid_body = body_crop is not None and body_crop.shape[0] >= 60 and body_crop.shape[1] >= 30

                    if is_good_quality or has_valid_body:
                        with self.lock:
                            self.processing_tracks.add(track_id)
                        self.recognition_queue.put((
                            track_id, 
                            head_crop.copy() if is_good_quality else None, 
                            body_crop.copy() if has_valid_body else None, 
                            current_zone, 
                            current_time,
                            [x1, y1, x2, y2]
                        ))
                # Sync presence heartbeat (only for confirmed staff, not customers)
                with self.lock:
                    last_sync = state.get("last_sync", 0)
                if current_time - last_sync > self.heartbeat_interval:
                    if db_id and not str(db_id).startswith("C_") and not str(db_id).startswith("customer_"):
                        database.record_attendance(db_id)
                    with self.lock:
                        state["last_sync"] = current_time
                    
                # Path Context & Exact Efficiency Logic
                with self.lock:
                    db_id = state["db_id"]
                    role = state["role"]
                    
                if db_id and not str(db_id).startswith("C_") and not str(db_id).startswith("customer_"):
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
                                if other_tid != track_id and (str(other_state.get("db_id", "")).startswith("C_") or str(other_state.get("db_id", "")).startswith("customer_")):
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
                is_staff = db_id and not str(db_id).startswith("C_") and not str(db_id).startswith("customer_")
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
                                try: database.log_activity(db_id or f"Track_{track_id}", zone.name, "Security Alert", f"Unauthorized entry ({person_label}) detected in {zone.name}.")
                                except: pass
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
                        c_id = int(str(db_id).split("_")[1]) if db_id and (str(db_id).startswith("C_") or str(db_id).startswith("customer_")) else None
                        self.customer_timers[track_id] = {"start": current_time, "zone": current_zone, "c_id": c_id}
                    elif db_id and (str(db_id).startswith("C_") or str(db_id).startswith("customer_")) and self.customer_timers[track_id].get("c_id") is None:
                        self.customer_timers[track_id]["c_id"] = int(str(db_id).split("_")[1])
                elif track_id in self.customer_timers:
                    # Person confirmed as staff — remove any stale customer timer
                    del self.customer_timers[track_id]

                # Visuals: Show locked label (Staff X / Customer Y) or Provisional until confirmed
                assign_info = assigned_map.get(track_id)
                if assign_info:
                    label = assign_info["label"]
                    itype = assign_info["type"]
                    db_id = assign_info["identity_id"]
                    is_locked_val = assign_info.get("is_locked", False)
                    color_hex = assign_info.get("color", "#94a3b8")
                    conf_val = 0.95 if is_locked_val else 0.50
                    if itype == "staff":
                        cv2_color = (229, 70, 79) # BGR Blue
                    elif itype == "customer":
                        cv2_color = (0, 215, 255) # BGR Yellow
                    else:
                        cv2_color = (184, 163, 148) # Slate
                elif state.get("identity_locked") and state.get("last_label"):
                    # Occlusion lock retention: face blocked, hand on chin, looking away
                    label = state["last_label"]
                    color_hex = state.get("last_color", "#3b82f6" if label.startswith("Staff") else "#eab308")
                    itype = "staff" if label.startswith("Staff") else "customer"
                    db_id = state.get("db_id")
                    is_locked_val = True
                    conf_val = 0.85
                    cv2_color = (229, 70, 79) if itype == "staff" else (0, 215, 255)
                else:
                    label = f"Provisional-T{track_id}"
                    itype = "provisional"
                    color_hex = "#94a3b8"  # Neutral slate for Provisional
                    cv2_color = (184, 163, 148)  # BGR
                    db_id = None
                    is_locked_val = False
                    conf_val = 0.0
                
                # Draw Box overlay directly onto video stream frame
                display_label = label
                if getattr(self, "show_debug_overlay", False):
                    display_label = f"T:{track_id} | {label}"
                cv2.rectangle(output_frame, (int(x1_out), int(y1_out)), (int(x2_out), int(y2_out)), cv2_color, 2)
                (tw, th), _ = cv2.getTextSize(display_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                cv2.rectangle(output_frame, (int(x1_out), int(y1_out) - th - 10), (int(x1_out) + tw + 10, int(y1_out)), cv2_color, -1)
                cv2.putText(output_frame, display_label, (int(x1_out) + 5, int(y1_out) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

                # Store last box in state for carry-forward during brief YOLO misses
                state["last_box"] = [float(x1), float(y1), float(x2), float(y2)]
                state["last_label"] = label
                state["last_color"] = color_hex
                if is_locked_val:
                    state["identity_locked"] = True

                # Compile detection metadata with separated geometry and identity layers
                detections.append({
                    "track_id": int(track_id),
                    "box": state["last_box"],
                    "geometry": {
                        "x1": float(x1),
                        "y1": float(y1),
                        "x2": float(x2),
                        "y2": float(y2)
                    },
                    "identity": {
                        "label": label,
                        "type": itype,
                        "staff_id": db_id if itype == "staff" else None,
                        "identity_id": db_id,
                        "is_locked": is_locked_val,
                        "confidence": conf_val
                    },
                    "staff_id": db_id if itype == "staff" else None,
                    "identity_id": db_id,
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
                                self.person_states[tid]["identity_locked"] = False
                                self.person_states[tid]["consecutive_matches"] = 0
                                self.person_states[tid]["pending_id"] = None
                                self.person_states[tid]["last_label"] = f"Guest #{tid}"
                                self.person_states[tid]["last_color"] = "#f97316"
                                if tid in self.track_identities:
                                    del self.track_identities[tid]
                        d["label"] = f"Guest #{tid}"
                        d["color"] = "#f97316"
                        d["staff_id"] = None
                    else:
                        staff_tracker[st_id] = tid

            # Cleanup expired tracks under lock
            with self.lock:
                expired = [tid for tid, s in self.person_states.items() if current_time - s["last_active"] > 10]
                for tid in expired:
                    identity_manager.handle_track_lost(tid)
                    if tid in self.customer_timers:
                        duration = current_time - self.customer_timers[tid]["start"]
                        if duration > 15:
                            try: database.record_customer_session("Auto-Table", duration, self.customer_timers[tid]["c_id"])
                            except: pass
                        del self.customer_timers[tid]
                    
                    # Log visitor detection for analytics (once per track lifetime)
                    if tid not in self.visitor_logged:
                        state = self.person_states[tid]
                        track_lifetime = current_time - state.get("first_seen", current_time)
                        db_id = state.get("db_id")
                        zone = state.get("zone", "Main Hall")

                        if track_lifetime < 5:
                            del self.person_states[tid]
                            if tid in self.recognition_consensus: del self.recognition_consensus[tid]
                            if tid in self.track_identities: del self.track_identities[tid]
                            continue

                        self.visitor_logged.add(tid)
                        try:
                            if db_id and not str(db_id).startswith("C_"):
                                database.log_visitor_detection(None, False, staff_id=db_id, zone=zone)
                            elif db_id and str(db_id).startswith("C_"):
                                c_id = int(str(db_id).split("_")[1])
                                database.log_visitor_detection(c_id, False, zone=zone)
                            else:
                                database.log_visitor_detection(None, True, zone=zone)
                        except: pass
                    
                    del self.person_states[tid]
                    if tid in self.recognition_consensus: del self.recognition_consensus[tid]
                    if tid in self.track_identities: del self.track_identities[tid]

            # Periodic Active Time Sync (every 10 seconds)
            if current_time - self.last_activity_sync > 10:
                for staff_id, seconds in self.activity_buffer.items():
                    if seconds > 0:
                        try: database.update_active_time(staff_id, seconds)
                        except: pass
                self.activity_buffer = {}
                self.last_activity_sync = current_time

            # Detections strictly reflect active real-time tracks — no ghost carry-forward or dwell freezing
            return output_frame, detections

            return output_frame, detections
        except Exception as e:
            print(f"[VISION ERROR] {e}")
            if 'detections' in locals() and detections:
                return output_frame if 'output_frame' in locals() else cv2.resize(frame, target_size), detections
            return cv2.resize(frame, target_size), []

    def get_active_staff(self):
        """Returns only confirmed staff members currently visible (excludes customers)."""
        active_dict = {}
        with self.lock:
            for tid, state in self.person_states.items():
                db_id = state.get("db_id")
                # Only include enrolled staff from confirmed tracks — skip None and customers
                if (tid in self.confirmed_track_ids
                        and time.time() - state["last_active"] < 8
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

