import cv2
import numpy as np
import os
import time
import database
import pickle

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
            self.known_face_encodings = new_encodings
            self.known_face_metadata = new_metadata
            
            # Load Customers
            cust_data = database.get_known_customers()
            c_encodings = []
            c_metadata = []
            for c_id, name, encoding_blob in cust_data:
                try: encoding = pickle.loads(encoding_blob)
                except: encoding = np.frombuffer(encoding_blob, dtype=np.float64)
                c_encodings.append(encoding)
                c_metadata.append({"id": c_id, "name": name})
            self.known_customer_encodings = c_encodings
            self.known_customer_metadata = c_metadata
            
            print(f"[AI] System Ready: {len(self.known_face_encodings)} Staff, {len(self.known_customer_encodings)} Customers loaded.")
        except Exception as e: print(f"[AI Initialization Error] {e}")

    def process_frame(self, frame):
        try:
            global model, model_loading_active
            if model is None:
                if not model_loading_active:
                    model_loading_active = True
                    def load():
                        global model, model_loading_active
                        try:
                            from ultralytics import YOLO
                            model_path = os.path.join('models', 'yolov8n-pose.pt')
                            if os.path.exists(model_path):
                                model = YOLO(model_path)
                                print("[AI] Background Model Load Complete.")
                        except Exception as e:
                            print(f"[AI ERROR] Lazy load failed: {e}")
                        finally:
                            model_loading_active = False
                    import threading
                    threading.Thread(target=load, daemon=True).start()
                return cv2.resize(frame, (640, 480))
                
            small_frame = cv2.resize(frame, (640, 480))
            results = model.track(small_frame, persist=True, verbose=False)
            current_time = time.time()
            
            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().numpy() if results[0].boxes.id is not None else []
                
                for box, track_id in zip(boxes, track_ids):
                    x1, y1, x2, y2 = map(int, box)
                    center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                    
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
                    state["zone"] = current_zone
                    
                    # Pose & Action Analysis
                    keypoints = results[0].keypoints.xy.cpu().numpy()[0] if results[0].keypoints is not None else None
                    pose_label = "NEUTRAL"
                    pose_multiplier = 1.0
                    
                    if keypoints is not None and len(keypoints) > 10:
                        try:
                            # 5:L_Shoulder, 6:R_Shoulder, 9:L_Wrist, 10:R_Wrist, 11:L_Hip, 12:R_Hip
                            l_shoulder, r_shoulder = keypoints[5], keypoints[6]
                            l_wrist, r_wrist = keypoints[9], keypoints[10]
                            l_hip, r_hip = keypoints[11], keypoints[12]
                            
                            hip_y = (l_hip[1] + r_hip[1]) / 2
                            shoulder_y = (l_shoulder[1] + r_shoulder[1]) / 2
                            torso_height = abs(hip_y - shoulder_y)
                            
                            # Detection 1: Active Hands (Wrists above hip line - 20% of torso)
                            hands_active = l_wrist[1] < (hip_y - 0.1*torso_height) or r_wrist[1] < (hip_y - 0.1*torso_height)
                            
                            # Detection 2: Leaning (Working Posture)
                            is_leaning = abs(l_shoulder[0] - l_hip[0]) > (0.15 * torso_height)
                            
                            # Detection 3: Hands in Pockets / Relaxed (Wrists very close to hips and each other)
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
                            
                            state["pose_multiplier"] = pose_multiplier
                            state["pose_label"] = pose_label
                        except: pass

                    # Identification Logic
                    if state["db_id"] is None:
                        if self.frame_count % self.rec_throttle_frames == 0:
                            face_img = small_frame[max(0, y1):min(480, y2), max(0, x1):min(640, x2)]
                            if face_img.size > 0:
                                try:
                                    import face_recognition
                                    rgb_face = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
                                    face_encodings = face_recognition.face_encodings(rgb_face)
                                    match_id = "Unknown"
                                    if face_encodings:
                                        # Check Staff
                                        matches = face_recognition.compare_faces(self.known_face_encodings, face_encodings[0], tolerance=0.55)
                                        if True in matches: 
                                            match_id = self.known_face_metadata[matches.index(True)]["id"]
                                        else:
                                            # Check Customers (if in Dining Area)
                                            if current_zone == "Dining Area":
                                                c_matches = face_recognition.compare_faces(self.known_customer_encodings, face_encodings[0], tolerance=0.6)
                                                if True in c_matches:
                                                    match_id = f"CUST:{self.known_customer_metadata[c_matches.index(True)]['id']}"

                                    if track_id not in self.recognition_consensus: self.recognition_consensus[track_id] = []
                                    self.recognition_consensus[track_id].append(match_id)
                                    if len(self.recognition_consensus[track_id]) > 5: self.recognition_consensus[track_id].pop(0)
                                    counts = {cid: self.recognition_consensus[track_id].count(cid) for cid in set(self.recognition_consensus[track_id])}
                                    winner = max(counts, key=counts.get)
                                    
                                    if counts[winner] >= 3:
                                        if winner.startswith("CUST:"):
                                            c_id = int(winner.split(":")[1])
                                            meta = next((m for m in self.known_customer_metadata if m["id"] == c_id), None)
                                            if meta:
                                                state["id"] = f"GUEST #{c_id}"; state["db_id"] = f"C_{c_id}"; state["name"] = meta["name"]
                                                state["last_sync"] = current_time
                                        elif winner != "Unknown":
                                            meta = next((m for m in self.known_face_metadata if m["id"] == winner), None)
                                            if meta:
                                                state["id"] = f"ID: {meta['id']}"; state["name"] = meta["name"]
                                                state["role"] = meta["role"]; state["db_id"] = meta["id"]
                                                state["last_sync"] = current_time
                                                database.record_attendance(meta["id"])
                                    
                                    # Auto-Register New Customer if seen enough in Dining Area
                                    if current_zone == "Dining Area" and winner == "Unknown" and len(self.recognition_consensus[track_id]) >= 5:
                                        if face_encodings:
                                            new_c_id = database.register_customer(pickle.dumps(face_encodings[0]))
                                            self.load_known_faces() # Refresh
                                            state["db_id"] = f"C_{new_c_id}"; state["id"] = f"GUEST #{new_c_id}"
                                            state["last_sync"] = current_time
                                except: pass
                    else:
                        # Sync presence heartbeat
                        if current_time - state["last_sync"] > self.heartbeat_interval:
                            database.record_attendance(state["db_id"])
                            state["last_sync"] = current_time
                        
                    # Path Context & Exact Efficiency Logic
                    if state["db_id"] and not str(state["db_id"]).startswith("C_"):
                        prev_pos = self.last_positions.get(track_id)
                        if prev_pos:
                            dist = np.sqrt((center[0]-prev_pos[0])**2 + (center[1]-prev_pos[1])**2)
                            
                            # 1. Base Multiplier (Idle check)
                            multiplier = 0.0
                            if dist > 3: # Some movement detected
                                multiplier = 1.0
                            
                            # 2. Zone Precision check (Anti-Fake)
                            authorized_zones = self.role_work_zones.get(state["role"], ["Main Hall"])
                            if current_zone not in authorized_zones:
                                multiplier *= 0.1 # Severe penalty for being in unauthorized areas
                            elif current_zone == "Main Hall":
                                multiplier *= 0.3 # Low value for walking in halls
                            
                            # 3. Service Engagement (Customer Proximity)
                            is_near_customer = False
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
                            
                            # 4. Pose-Based Action Refinement (NEW)
                            p_mult = state.get("pose_multiplier", 1.0)
                            multiplier *= p_mult
                            
                            # 5. Stationary Work Check
                            # If they are in their CORE work zone (Kitchen for Chef) but moving slowly, 
                            # they might be cooking/prepping. Give partial credit.
                            if dist <= 3 and current_zone in authorized_zones and current_zone != "Main Hall":
                                # Give 30% credit for standing in a work zone
                                multiplier = 0.3
                            
                            self.activity_buffer[state["db_id"]] = self.activity_buffer.get(state["db_id"], 0) + multiplier
                        
                    self.last_positions[track_id] = center
                    
                    # RESTRICTED ZONE MONITORING
                    if state["db_id"]:
                        in_unauth_zone = False
                        for zone in self.zones:
                            if zone.is_inside(center) and state["role"] in zone.unauthorized_roles:
                                in_unauth_zone = True
                                if (track_id, zone.name) not in self.alerted_tracks:
                                    database.log_activity(state["db_id"], zone.name, "Security Alert", f"Unauthorized role ({state['role']}) detected in restricted zone.")
                                    # Signal for immediate email (this will be handled by app.py via callback or polling)
                                    state["needs_security_email"] = zone.name
                                    self.alerted_tracks.add((track_id, zone.name))
                                break
                        
                        if not in_unauth_zone:
                            # Clear alerts for zones this track is no longer in
                            self.alerted_tracks = {(tid, zname) for tid, zname in self.alerted_tracks if tid != track_id}

                    # CUSTOMER INTELLIGENCE (Unknown or Guest in Dining Area)
                    is_staff = state["db_id"] and not str(state["db_id"]).startswith("C_")
                    if not is_staff and current_zone == "Dining Area":
                        if track_id not in self.customer_timers:
                            c_id = int(str(state["db_id"]).split("_")[1]) if str(state["db_id"]).startswith("C_") else None
                            self.customer_timers[track_id] = {"start": current_time, "zone": "Dining Area", "c_id": c_id}
                    elif track_id in self.customer_timers:
                        # If they move out of Dining Area or leave, finalize their customer session
                        duration = current_time - self.customer_timers[track_id]["start"]
                        if duration > 15: # Minimum 15 seconds
                            database.record_customer_session("Auto-Table", duration, self.customer_timers[track_id]["c_id"])
                        del self.customer_timers[track_id]

                    # Visuals (Bounding Boxes for EVERYONE)
                    if state["db_id"]:
                        if str(state["db_id"]).startswith("C_"):
                            color = (0, 215, 255) # Gold/Yellow for Recognized Guest
                            label = f"REGULAR {state['id']}"
                        else:
                            color = (229, 70, 79) # Indigo for Staff
                            status = state.get("pose_label", "NEUTRAL")
                            label = f"STAFF: {state['name']} [{status}]"
                    else:
                        color = (6, 119, 217) # Amber for Unknown
                        label = f"CUSTOMER #{track_id}"
                    
                    # Draw Box
                    cv2.rectangle(small_frame, (x1, y1), (x2, y2), color, 2)
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                    cv2.rectangle(small_frame, (x1, y1 - th - 10), (x1 + tw + 10, y1), color, -1)
                    cv2.putText(small_frame, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

            # Cleanup expired tracks
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

            return small_frame
        except Exception as e:
            print(f"[VISION ERROR] {e}")
            return cv2.resize(frame, (640, 480))

    def get_active_staff(self):
        active_dict = {}
        for tid, state in self.person_states.items():
            if time.time() - state["last_active"] < 2 and state["db_id"] is not None:
                active_dict[state["db_id"]] = {"id": state["id"], "name": state.get("name", "Unknown"), "role": state.get("role", "None"), "zone": state["zone"]}
        return list(active_dict.values())
