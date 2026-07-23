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
        self.zones = [
            Zone("Main Hall", [[10, 10], [630, 10], [630, 470], [10, 470]]),
            Zone("Kitchen", [[50, 200], [250, 200], [250, 450], [50, 450]]),
            Zone("Dining Area", [[260, 50], [600, 50], [600, 450], [260, 450]])
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

    def load_known_faces(self):
        try:
            import face_recognition # Local import
            # Load Staff
            staff_data = database.get_all_staff()
            new_encodings = []
            new_metadata = []
            for s_id, name, role, shift_time, rate, encoding_blob, shift_name in staff_data:
                if encoding_blob:
                    try: encoding = pickle.loads(encoding_blob)
                    except: encoding = np.frombuffer(encoding_blob, dtype=np.float64)
                    new_encodings.append(encoding)
                    new_metadata.append({"id": s_id, "name": name, "role": role})
            
            # Load Customers
            cust_data = database.get_known_customers()
            c_encodings = []
            c_metadata = []
            for c_id, name, encoding_blob, visit_count in cust_data:
                try: encoding = pickle.loads(encoding_blob)
                except: encoding = np.frombuffer(encoding_blob, dtype=np.float64)
                c_encodings.append(encoding)
                c_metadata.append({"id": c_id, "name": name, "visits": visit_count})
            
            with self.lock:
                self.known_face_encodings = new_encodings
                self.known_face_metadata = new_metadata
                self.known_customer_encodings = c_encodings
                self.known_customer_metadata = c_metadata
            
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
                
                import face_recognition
                rgb_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
                face_encodings = face_recognition.face_encodings(rgb_face)
                
                match_id = "Unknown"
                if face_encodings:
                    with self.lock:
                        known_staff_enc = list(self.known_face_encodings)
                        known_staff_meta = list(self.known_face_metadata)
                        known_cust_enc = list(self.known_customer_encodings)
                        known_cust_meta = list(self.known_customer_metadata)
                    
                    if known_staff_enc:
                        matches = face_recognition.compare_faces(known_staff_enc, face_encodings[0], tolerance=0.55)
                        if True in matches:
                            match_id = known_staff_meta[matches.index(True)]["id"]
                    
                    if match_id == "Unknown" and known_cust_enc:
                        c_matches = face_recognition.compare_faces(known_cust_enc, face_encodings[0], tolerance=0.65)
                        if True in c_matches:
                            match_id = f"CUST:{known_cust_meta[c_matches.index(True)]['id']}"
                            matched_cust_idx = c_matches.index(True)
                            database.update_customer_encoding(known_cust_meta[matched_cust_idx]['id'], pickle.dumps(face_encodings[0]))
                
                # Update consensus and state under lock
                with self.lock:
                    if track_id not in self.recognition_consensus:
                        self.recognition_consensus[track_id] = []
                    self.recognition_consensus[track_id].append(match_id)
                    if len(self.recognition_consensus[track_id]) > 5:
                        self.recognition_consensus[track_id].pop(0)
                        
                    counts = {cid: self.recognition_consensus[track_id].count(cid) for cid in set(self.recognition_consensus[track_id])}
                    winner = max(counts, key=counts.get)
                    
                    # Update state if it still exists
                    if track_id in self.person_states:
                        state = self.person_states[track_id]
                        if counts[winner] >= 3:
                            if winner.startswith("CUST:"):
                                c_id = int(winner.split(":")[1])
                                meta = next((m for m in self.known_customer_metadata if m["id"] == c_id), None)
                                if meta:
                                    state["id"] = f"GUEST #{c_id}"
                                    state["db_id"] = f"C_{c_id}"
                                    state["name"] = meta["name"]
                                    state["visits"] = meta.get("visits", 1)
                                    state["last_sync"] = current_time
                            elif winner != "Unknown":
                                meta = next((m for m in self.known_face_metadata if m["id"] == winner), None)
                                if meta:
                                    state["id"] = f"ID: {meta['id']}"
                                    state["name"] = meta["name"]
                                    state["role"] = meta["role"]
                                    state["db_id"] = meta["id"]
                                    state["last_sync"] = current_time
                                    database.record_attendance(meta["id"])
                
                # Handle auto-registration outside lock
                if match_id == "Unknown" and face_encodings:
                    with self.lock:
                        consensus_len = len(self.recognition_consensus.get(track_id, []))
                        counts = {cid: self.recognition_consensus[track_id].count(cid) for cid in set(self.recognition_consensus[track_id])} if track_id in self.recognition_consensus else {}
                        winner = max(counts, key=counts.get) if counts else "Unknown"
                    
                    if consensus_len >= 5 and winner == "Unknown":
                        with self.lock:
                            known_cust_enc = list(self.known_customer_encodings)
                            known_cust_meta = list(self.known_customer_metadata)
                        fallback_match = False
                        if known_cust_enc:
                            c_matches = face_recognition.compare_faces(known_cust_enc, face_encodings[0], tolerance=0.7)
                            if True in c_matches:
                                match_id = f"CUST:{known_cust_meta[c_matches.index(True)]['id']}"
                                database.update_customer_encoding(known_cust_meta[c_matches.index(True)]['id'], pickle.dumps(face_encodings[0]))
                                fallback_match = True
                                with self.lock:
                                    if track_id in self.recognition_consensus:
                                        self.recognition_consensus[track_id].append(match_id)
                                    if track_id in self.person_states:
                                        state = self.person_states[track_id]
                                        c_id = int(known_cust_meta[c_matches.index(True)]['id'])
                                        state["db_id"] = f"C_{c_id}"
                                        state["id"] = f"GUEST #{c_id}"
                                        state["name"] = known_cust_meta[c_matches.index(True)]["name"]
                                        state["visits"] = known_cust_meta[c_matches.index(True)].get("visits", 1)
                                        state["last_sync"] = current_time
                        if not fallback_match:
                            new_c_id = database.register_customer(pickle.dumps(face_encodings[0]))
                            with self.lock:
                                if track_id in self.person_states:
                                    self.person_states[track_id]["visits"] = 1
                        self.load_known_faces() # Reloads inside its own lock
                        with self.lock:
                            if track_id in self.person_states:
                                state = self.person_states[track_id]
                                state["db_id"] = f"C_{new_c_id}"
                                state["id"] = f"GUEST #{new_c_id}"
                                state["name"] = "New Guest"
                                state["last_sync"] = current_time
                                
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

    def process_frame(self, frame, target_size=(640, 480)):
        try:
            global model, model_loading_active
            if model is None:
                if not model_loading_active:
                    model_loading_active = True
                    def load():
                        global model, model_loading_active
                        try:
                            from ultralytics import YOLO
                            base_dir = os.path.abspath(os.path.dirname(__file__))
                            model_path = os.path.join(base_dir, 'models', 'yolov8n-pose.pt')
                            print(f"[AI] Attempting to load YOLO model from: {model_path}")
                            if os.path.exists(model_path):
                                model = YOLO(model_path)
                                print("[AI] Background Model Load Complete.")
                            else:
                                print(f"[AI ERROR] YOLO model file does not exist at {model_path}!")
                        except Exception as e:
                            print(f"[AI ERROR] Lazy load failed: {e}")
                        finally:
                            model_loading_active = False
                    import threading
                    threading.Thread(target=load, daemon=True).start()
                return cv2.resize(frame, target_size)
                
            # Run YOLO on a lightweight 640x480 frame for CPU efficiency
            small_frame = cv2.resize(frame, (640, 480))
            results = model.track(small_frame, persist=True, verbose=False)
            current_time = time.time()
            
            # Prepare output frame at target resolution
            output_frame = cv2.resize(frame, target_size)
            h_out, w_out = output_frame.shape[:2]
            scale_x = target_size[0] / 640.0
            scale_y = target_size[1] / 480.0
            
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
                for box, track_id in zip(boxes, track_ids):
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
                        if not is_processing and (current_time - last_attempt > 2.0):
                            self.last_rec_attempt[track_id] = current_time
                            
                            # Optimize face crop: crop only upper 35% of the body box
                            y1_face = max(0, y1_out)
                            y2_face = min(h_out, y1_out + int((y2_out - y1_out) * 0.35))
                            face_img = output_frame[y1_face:y2_face, max(0, x1_out):min(w_out, x2_out)]
                            
                            if face_img.size > 0 and face_img.shape[0] >= 32 and face_img.shape[1] >= 32:
                                with self.lock:
                                    self.processing_tracks.add(track_id)
                                self.recognition_queue.put((track_id, face_img.copy(), current_zone, current_time))
                    else:
                        # Sync presence heartbeat
                        with self.lock:
                            last_sync = state["last_sync"]
                        if current_time - last_sync > self.heartbeat_interval:
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

                    # CUSTOMER INTELLIGENCE (Unknown or Guest in Dining Area)
                    is_staff = db_id and not str(db_id).startswith("C_")
                    if not is_staff and current_zone == "Dining Area":
                        if track_id not in self.customer_timers:
                            c_id = int(str(db_id).split("_")[1]) if db_id and str(db_id).startswith("C_") else None
                            self.customer_timers[track_id] = {"start": current_time, "zone": "Dining Area", "c_id": c_id}
                    elif track_id in self.customer_timers:
                        # If they move out of Dining Area or leave, finalize their customer session
                        duration = current_time - self.customer_timers[track_id]["start"]
                        if duration > 15: # Minimum 15 seconds
                            database.record_customer_session("Auto-Table", duration, self.customer_timers[track_id]["c_id"])
                        del self.customer_timers[track_id]

                    # Visuals (Bounding Boxes for EVERYONE)
                    with self.lock:
                        db_id = state.get("db_id")
                        state_id = state.get("id")
                        state_name = state.get("name", "Unknown")
                        state_role = state.get("role", "None")
                        status = state.get("pose_label", "NEUTRAL")
                        
                    if db_id:
                        if str(db_id).startswith("C_"):
                            color = (0, 215, 255)
                            visits = state.get("visits", 1)
                            label = f"REGULAR {state_id} ({visits}x)"
                        else:
                            color = (229, 70, 79) # Indigo for Staff
                            label = f"STAFF: {state_name} [{status}]"
                    else:
                        color = (6, 119, 217)
                        label = "NEW FACE"
                    
                    # Draw Box on the HD output frame
                    cv2.rectangle(output_frame, (x1_out, y1_out), (x2_out, y2_out), color, 2)
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                    cv2.rectangle(output_frame, (x1_out, y1_out - th - 10), (x1_out + tw + 10, y1_out), color, -1)
                    cv2.putText(output_frame, label, (x1_out + 5, y1_out - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

            # Cleanup expired tracks under lock
            with self.lock:
                expired = [tid for tid, s in self.person_states.items() if current_time - s["last_active"] > 5]
                for tid in expired:
                    if tid in self.customer_timers:
                        duration = current_time - self.customer_timers[tid]["start"]
                        if duration > 20: 
                            database.record_customer_session("Auto-Table", duration, self.customer_timers[tid]["c_id"])
                        del self.customer_timers[tid]
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

            return output_frame
        except Exception as e:
            print(f"[VISION ERROR] {e}")
            return cv2.resize(frame, target_size)

    def get_active_staff(self):
        active_dict = {}
        with self.lock:
            for tid, state in self.person_states.items():
                if time.time() - state["last_active"] < 2 and state["db_id"] is not None:
                    active_dict[state["db_id"]] = {"id": state["id"], "name": state.get("name", "Unknown"), "role": state.get("role", "None"), "zone": state["zone"]}
        return list(active_dict.values())
