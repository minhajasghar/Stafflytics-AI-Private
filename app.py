from flask import Flask, render_template, Response, jsonify, request, session, redirect, url_for
from flask_sock import Sock
import json
import cv2
import database
# Heavy imports moved to background thread
# from vision_engine import VisionEngine
# import face_recognition
import threading
import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|max_delay;2000000|fflags;+genpts+igndts"
import time
import pickle
import numpy as np
import base64
import io
from collections import deque
from PIL import Image
from functools import wraps
from datetime import datetime, timedelta
import mailer
from chatbot_engine import chatbot
import requests
import re
from export_engine import export_engine
from flask import send_file

# Stafflytics AI Configuration
app = Flask(__name__)
app.secret_key = 'signature_secret_key_stafflytics_2026'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
sock = Sock(app)

websocket_clients = set()
websocket_lock = threading.Lock()

def broadcast_detections(detections):
    payload = json.dumps({"detections": detections})
    with websocket_lock:
        inactive = set()
        for client in websocket_clients:
            try:
                client.send(payload)
            except Exception:
                inactive.add(client)
        for client in inactive:
            websocket_clients.discard(client)

@sock.route('/api/detection')
def detection_ws(ws):
    with websocket_lock:
        websocket_clients.add(ws)
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
    except Exception:
        pass
    finally:
        with websocket_lock:
            websocket_clients.discard(ws)


# Initialize database & Mailer
engine = None        # Initialized asynchronously
camera_stream = None # Initialized asynchronously

# RTSP Camera Configuration
PHYSICAL_RTSP_URL = "rtsp://admin:L2DD2594@192.168.50.251:554/cam/realmonitor?channel=1&subtype=0"
RTSP_URL = "rtsp://127.0.0.1:8554/cam"

def sync_camera_config():
    global RTSP_URL, PHYSICAL_RTSP_URL
    conf = database.get_system_settings()
    saved = conf.get('rtsp_url', '')
    if saved and saved.strip():
        PHYSICAL_RTSP_URL = saved.strip()
        print(f"[SYSTEM] PHYSICAL_RTSP_URL updated to: '{PHYSICAL_RTSP_URL}'")
    # Route through local MediaMTX proxy to multiplex camera connections and save CPU/bandwidth
    RTSP_URL = "rtsp://127.0.0.1:8554/cam"
    print(f"[SYSTEM] sync_camera_config: Redirected RTSP_URL to local proxy: '{RTSP_URL}'")
QUALITY_PRESETS = {
    "480p": {"size": (640, 480), "jpeg": 65, "label": "Standard (480p)"},
    "720p": {"size": (1280, 720), "jpeg": 75, "label": "Enhanced (720p)"},
    "1080p": {"size": (1920, 1080), "jpeg": 85, "label": "HD (1080p)"}
}

def sync_camera_preset():
    global camera_preset, camera_quality, camera_width, camera_height
    conf = database.get_system_settings()
    preset = conf.get('camera_preset', '480p')
    if preset not in QUALITY_PRESETS:
        preset = '480p'
    camera_preset = preset
    cfg = QUALITY_PRESETS[preset]
    camera_width, camera_height = cfg["size"]
    camera_quality = cfg["jpeg"]


system_initializing = True
init_status = "System Awakening..."

def sync_mailer_config():
    conf = database.get_system_settings()
    mailer.SENDER_EMAIL = conf.get('sender_email', '')
    mailer.SENDER_PASSWORD = conf.get('sender_password', '')
    mailer.OWNER_EMAIL = conf.get('owner_email', 'admin@stafflytics.ai')
# sync_mailer_config() # Moved to background
camera_online = False # Global status for dashboard
camera_preset = "480p"
camera_quality = 65
camera_width = 640
camera_height = 480

latest_processed_frame = None
processed_frame_lock = threading.Lock()

# RTSP/WebRTC streaming writer
rtsp_writer = None
import atexit

def get_rtsp_writer():
    global rtsp_writer
    # Use configured camera resolution for streaming, capped at 720p to balance quality/CPU
    preset_cfg = QUALITY_PRESETS.get(camera_preset, QUALITY_PRESETS['480p'])
    w = min(preset_cfg["size"][0], 1280)
    h = min(preset_cfg["size"][1], 720)
    if rtsp_writer is None or rtsp_writer.width != w or rtsp_writer.height != h:
        if rtsp_writer is not None:
            try: rtsp_writer.stop()
            except: pass
        import stream_manager
        rtsp_writer = stream_manager.RTSPStreamWriter(
            rtsp_url="rtsp://127.0.0.1:8554/mystream",
            width=w,
            height=h,
            fps=10
        )
    return rtsp_writer

def cleanup_streams():
    print("[SYSTEM] Cleaning up streaming subprocesses...")
    global rtsp_writer
    if rtsp_writer is not None:
        try: rtsp_writer.stop()
        except: pass
    try:
        import stream_manager
        stream_manager.stop_mediamtx()
    except:
        pass

atexit.register(cleanup_streams)

class CameraStream:
    def __init__(self):
        self.stream = None
        self.frame = None
        self.frame_id = 0
        self.stopped = False
        self.online = False
        self.lock = threading.Lock()
        self.frame_buffer = deque(maxlen=5)
        self.latest_frame_time = 0
        self.indices = [0, 1, 2] # Try multiple camera indices
        self.backeneds = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        
    def start(self):
        # Start the background update thread immediately
        if not any(t.name == "CameraUpdateThread" for t in threading.enumerate()):
            threading.Thread(target=self.update, daemon=True, name="CameraUpdateThread").start()
        return self

    def _attempt_connection(self):
        global camera_online
        print(f"[SYSTEM] Starting Camera Synchronization Loop... (RTSP_URL='{RTSP_URL}')")

        # Try RTSP URL with multiple common stream paths
        if RTSP_URL:
            rtsp_variants = []

            # 1) ALWAYS try the user's exact URL first (most important!)
            rtsp_variants.append(RTSP_URL)

            # Only try camera-specific fallbacks if connecting to a remote camera directly
            if "localhost" not in RTSP_URL and "127.0.0.1" not in RTSP_URL:
                # 2) Try with TCP transport on the exact URL
                if '?' in RTSP_URL:
                    rtsp_variants.append(RTSP_URL + "&tcp")
                else:
                    rtsp_variants.append(RTSP_URL + "?tcp")

                # 3) Extract base and try Imou/Dahua-specific paths
                m = re.match(r'(rtsp://[^@]+@[^/]+|rtsp://[^/]+)', RTSP_URL)
                base = m.group(1) if m else RTSP_URL

                paths = [
                    '/cam/realmonitor?channel=1&subtype=0',
                    '/cam/realmonitor?channel=1&subtype=1',
                    '/cam/realmonitor?channel=1&subtype=0&unicast=true&proto=Onvif',
                    '/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif',
                    '/cam/realmonitor?channel=1&subtype=00',
                    '/cam/realmonitor?channel=1&subtype=00&authbasic=YWRtaW46',
                    '/stream1',
                    '/Streaming/Channels/101',
                    '/h264/ch1/main/av_stream',
                    '/h264_stream',
                    '/onvif1',
                    '/onvif/stream2',
                    '/live',
                    '/video',
                    '/video1',
                    '/videoMain',
                    '/h264',
                ]
                for p in paths:
                    variant = f"{base}{p}"
                    if variant not in rtsp_variants:
                        rtsp_variants.append(variant)
                    tcp_suffix = "&tcp" if "?" in p else "?tcp"
                    tcp_variant = f"{base}{p}{tcp_suffix}"
                    if tcp_variant not in rtsp_variants:
                        rtsp_variants.append(tcp_variant)

            print(f"[SYSTEM] Trying {len(rtsp_variants)} RTSP variants...")
            for url in rtsp_variants:
                if self.stopped: return False
                backends_to_try = [cv2.CAP_FFMPEG, cv2.CAP_ANY]
                for be in backends_to_try:
                    if self.stopped: return False
                    try:
                        display_url = url.split('://')[0] + '://[credentials]@' + url.split('@')[1] if '@' in url else url
                        print(f"[SYSTEM] Probing RTSP: {display_url} (backend: {be})")
                        cap = cv2.VideoCapture(url, be)
                        if cap:
                            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
                            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)
                        if cap and cap.isOpened():
                            ret, f = cap.read()
                            if ret and f is not None:
                                print(f"[SYSTEM] Camera successfully synchronized via RTSP: {display_url}")
                                cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
                                self.stream = cap
                                self.online = True
                                camera_online = True
                                return True
                        if cap: cap.release()
                    except Exception as e:
                        print(f"[RTSP PROBE ERROR] {e}")
                        continue

        # Fallback to local camera indices
        for idx in self.indices:
            for be in self.backeneds:
                if self.stopped: return False
                try:
                    print(f"[SYSTEM] Probing Index {idx} with Backend {be}...")
                    cap = cv2.VideoCapture(idx, be)
                    if cap and cap.isOpened():
                        ret, f = cap.read()
                        if ret and f is not None:
                            print(f"[SYSTEM] Camera successfully synchronized at Index {idx}.")
                            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                            cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
                            self.stream = cap
                            self.online = True
                            camera_online = True
                            return True
                    if cap: cap.release()
                except Exception as e:
                    print(f"[CAMERA PROBE ERROR] {e}")
        return False

    def update(self):
        global camera_online
        retry_count = 0
        while not self.stopped:
            if not self.online:
                if self._attempt_connection():
                    print("[SYSTEM] Camera Signal Established.")
                    retry_count = 0
                else:
                    retry_count += 1
                    wait = min(5 * retry_count, 30)
                    print(f"[SYSTEM] Camera hardware not found. Retrying in {wait}s...")
                    time.sleep(wait)
                    continue

            try:
                grabbed, frame = self.stream.read()
                if not grabbed or frame is None:
                    print("[SYSTEM] Camera Signal Lost. Attempting Reconnection...")
                    self.online = False
                    camera_online = False
                    if self.stream:
                        try: self.stream.release()
                        except: pass
                        self.stream = None
                    retry_count += 1
                    time.sleep(min(retry_count, 10))
                    continue
                
                retry_count = 0
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1
                    self.frame_buffer.append((frame.copy(), self.frame_id))
            except Exception as e:
                print(f"[CAMERA STREAM ERROR] {e}")
                self.online = False
                camera_online = False
                if self.stream:
                    try: self.stream.release()
                    except: pass
                    self.stream = None
                time.sleep(5)

    def read(self):
        with self.lock:
            return (self.frame.copy(), self.frame_id) if self.frame is not None else (None, 0)

    def read_buffered(self):
        with self.lock:
            if self.frame_buffer:
                f, fid = self.frame_buffer[-1]
                return (f.copy(), fid)
            return (self.frame.copy(), self.frame_id) if self.frame is not None else (None, 0)

    def get_buffer_fill(self):
        with self.lock:
            return len(self.frame_buffer)

    def stop(self):
        self.stopped = True
        if self.stream: self.stream.release()

def vision_engine_loop():
    global camera_stream, engine, latest_processed_frame, camera_width, camera_height
    last_processed_frame_id = -1
    print("[SYSTEM] Vision Engine background loop started.")
    while True:
        try:
            if camera_stream is None or not camera_stream.online or engine is None:
                time.sleep(0.5)
                continue
            
            res = camera_stream.read()
            if res[0] is None:
                time.sleep(0.1)
                continue
                
            frame, frame_id = res
            if frame_id == last_processed_frame_id:
                time.sleep(0.01)
                continue
                
            last_processed_frame_id = frame_id
            
            # Process frame for analytics (YOLOv8 + Face recognition + metrics)
            raw_frame, detections = engine.process_frame(frame, target_size=(camera_width or 640, camera_height or 480))
            
            with processed_frame_lock:
                latest_processed_frame = raw_frame.copy() if raw_frame is not None else None
            
            # Broadcast detection coordinates to all websocket clients
            broadcast_detections(detections)
            # Throttle to max ~10 FPS to conserve CPU resources while retaining real-time analytics
            time.sleep(0.1)
        except Exception as e:
            print(f"[VISION LOOP ERROR] {e}")
            time.sleep(1)

# --- ASYNCHRONOUS INITIALIZATION ---
def background_system_init():
    global engine, camera_stream, system_initializing, init_status
    start_time = time.time()
    print("[SYSTEM] Instant Launch Sequence Started...")
    
    # 1. Init Database First (Essential)
    try:
        init_status = "Synchronizing Database..."
        database.init_db()
        sync_mailer_config()
        sync_camera_config()
        sync_camera_preset()
        print("[SYSTEM] Database Ready.")
        
        # Check and download streaming binaries in background
        init_status = "Checking streaming binaries..."
        import stream_manager
        stream_manager.ensure_binaries_async()
    except Exception as e:
        print(f"[SYSTEM ERROR] Database init failed: {e}")

    # Release the UI early
    system_initializing = False
    init_status = "Dashboard Ready. AI & Camera loading in background..."
    
    # 2. Init Vision Engine (Lazy Loading starts inside)
    try:
        init_status = "Warmup Vision Engine..."
        from vision_engine import VisionEngine
        engine = VisionEngine()
        print("[SYSTEM] Vision Engine Placeholder Loaded.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Vision Engine failed: {e}")
        
    # 3. Init Camera Stream
    try:
        init_status = "Connecting Camera..."
        camera_stream = CameraStream().start()
        print("[SYSTEM] Camera Background Sync Done.")
        # Start background vision analytics loop thread
        threading.Thread(target=vision_engine_loop, daemon=True, name="VisionEngineLoopThread").start()
    except Exception as e:
        print(f"[SYSTEM ERROR] Camera initialization failed: {e}")

    # 4. Pre-connect ONVIF for PTZ (saves ~18s on first click)
    try:
        init_status = "Connecting PTZ..."
        _get_onvif_connection()
    except Exception as e:
        print(f"[PTZ] Pre-connect skipped: {e}")
        
    init_status = "Ready"
    elapsed = time.time() - start_time
    print(f"[SYSTEM] Background Initialization Finished in {elapsed:.2f} seconds.")

# Start initialization in background
threading.Thread(target=background_system_init, daemon=True, name="SystemInitThread").start()

def generate_frames():
    global camera_stream, engine, system_initializing, camera_quality, camera_width, camera_height, latest_processed_frame
    refresh_counter = 0
    last_yield_time = 0
    min_frame_interval = 0.067
    last_sent_frame_id = -1
    
    while True:
        try:
            current_time = time.time()
            
            if system_initializing or camera_stream is None:
                loading = np.zeros((480, 640, 3), np.uint8)
                cv2.putText(loading, "INITIALIZING AI...", (150, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                cv2.putText(loading, "Please wait...", (240, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                ret, buf = cv2.imencode('.jpg', loading)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(0.5); continue

            refresh_counter += 1
            if refresh_counter >= 300:
                sync_camera_preset()
                refresh_counter = 0

            # If camera stream is offline, return CAM OFFLINE
            if not camera_stream.online:
                err = np.zeros((camera_height or 480, camera_width or 640, 3), np.uint8)
                cv2.putText(err, "CAMERA OFFLINE", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (50, 50, 255), 3)
                ret, buf = cv2.imencode('.jpg', err)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(1); continue

            # Fetch the pre-processed frame from background analytics thread
            with processed_frame_lock:
                display_frame = latest_processed_frame.copy() if latest_processed_frame is not None else None
                buf_frame_id = -1

            # Fallback if no frame has been processed by analytics loop yet
            if display_frame is None:
                res, fid = camera_stream.read_buffered()
                if res is not None:
                    if fid == last_sent_frame_id:
                        time.sleep(0.01)
                        continue
                    display_frame = cv2.resize(res, (camera_width or 640, camera_height or 480))
                    buf_frame_id = fid
                else:
                    time.sleep(0.05)
                    continue
            
            elapsed = time.time() - last_yield_time
            if elapsed < min_frame_interval:
                time.sleep(min_frame_interval - elapsed)
            
            ret, buf = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, camera_quality])
            if ret:
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                last_yield_time = time.time()
                if buf_frame_id >= 0:
                    last_sent_frame_id = buf_frame_id
            del buf
            
        except GeneratorExit:
            print("[STREAM] Client disconnected, cleaning up.")
            break
        except Exception as e:
            print(f"[STREAM ERROR] {e}")
            time.sleep(0.5)

# Auth
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return jsonify({"status": "error", "message": "Auth required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- SCHEDULER: Nightly Business Report (11 PM) ---
def nightly_scheduler():
    sent_today = False
    while True:
        now = datetime.now()
        if now.hour == 23 and now.minute == 0 and not sent_today:
            summary = database.get_comprehensive_summary()
            html = mailer.get_daily_report_template(summary)
            # Fetch admin email
            email = database.get_admin_email()
            if email:
                mailer.send_email_async(email, f"Stafflytics Daily Report - {now.strftime('%d %b')}", html)
            sent_today = True
        if now.hour == 0: sent_today = False
        time.sleep(30)

threading.Thread(target=nightly_scheduler, daemon=True).start()

# --- ROUTES ---

@app.route('/')
def index():
    # Force fresh login check
    if 'logged_in' not in session or not session.get('logged_in'):
        return render_template('login.html')
    return render_template('index.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    if database.validate_admin(data.get('username'), data.get('password')):
        session.permanent = False; session['logged_in'] = True; session['username'] = data.get('username')
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 401

@app.route('/api/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    resp = chatbot.process_query(request.json.get('query', ''))
    return jsonify({"response": resp})

@app.route('/api/webrtc/status')
@login_required
def webrtc_status():
    import stream_manager
    return jsonify({
        "complete": stream_manager.download_complete,
        "status": stream_manager.download_status,
        "error": stream_manager.download_error
    })

@app.route('/video_feed')
def video_feed():
    resp = Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp

@app.route('/api/analytics/engagement')
@login_required
def get_engagement_analytics():
    return jsonify(database.get_service_engagement_analytics())
@app.route('/api/analytics/wellbeing')
@login_required
def get_wellbeing_analytics():
    return jsonify(database.get_wellbeing_data())

@app.route('/api/analytics/loyalty')
@login_required
def get_loyalty_analytics():
    return jsonify(database.get_loyalty_analytics())

@app.route('/api/analytics/visitors')
@login_required
def get_visitor_analytics():
    scope = request.args.get('scope', 'day')
    return jsonify(database.get_visitor_analytics(scope))

@app.route('/api/analytics/performance')
@login_required
def get_performance_analytics():
    return jsonify(database.get_performance_rankings())

@app.route('/api/analytics/optimization')
@login_required
def get_optimization_analytics():
    return jsonify(database.get_shift_optimization_data())

@app.route('/api/analytics/synergy')
@login_required
def get_synergy_analytics():
    return jsonify(database.get_synergy_metrics())

@app.route('/api/sales/add', methods=['POST'])
@login_required
def record_sale_transaction():
    data = request.json
    database.record_sale(data.get('staff_id'), data.get('amount'))
    return jsonify({"status": "success"})

@app.route('/api/status')
@login_required
def get_status():
    global camera_online, system_initializing
    
    # Always fetch DB stats even if AI/Camera is still starting
    try:
        summ = database.get_dashboard_summary()
        cst = database.get_monthly_customer_stats()
        today_cst = database.get_today_customer_stats()
        roster = database.get_todays_shift_roster()
    except Exception as e:
        print(f"[DB STATUS ERROR] {e}")
        summ = {"payroll_monthly": 0, "late_today": 0, "incidents_today": 0, "avg_efficiency": 0.0}
        cst = {"avg_visit": 0, "monthly_total": 0}
        today_cst = {"today_count": 0, "today_minutes": 0}
        roster = []

    # If AI is still loading or failed, return partial data
    if engine is None or system_initializing:
        return jsonify({
            "initializing": system_initializing,
            "init_status": init_status,
            "count": 0, "camera_online": camera_online,
            "avg_efficiency": summ.get("avg_efficiency", 0), "late_today": summ.get("late_today", 0),
            "incidents_today": summ.get("incidents_today", 0), "customer_avg": cst.get("avg_visit", 0),
            "repeat_customers": cst.get("repeat_customers", 0),
            "roster": roster, "active_list": [], "monthly_customers": cst.get("monthly_total", 0),
            "today_customers": today_cst.get("today_count", 0),
            "today_customer_minutes": today_cst.get("today_minutes", 0)
        })

    stf = engine.get_active_staff() if engine else []
    
    # Process pending security emails and telegrams
    new_alert = False
    alert_name = ""
    alert_zone = ""
    for tid, state in engine.person_states.items():
        if "needs_security_email" in state:
            zone_name = state.pop("needs_security_email")
            new_alert = True
            alert_name = state.get('name', 'Unknown')
            alert_zone = zone_name
            
            # 1. Email
            html = mailer.get_security_alert_template(alert_name, alert_zone)
            mailer.send_email_async(mailer.OWNER_EMAIL, f"SECURITY ALERT: Unauthorized Entry in {alert_zone}", html)
            
    return jsonify({
        "initializing": False,
        "count": len(stf), "camera_online": camera_online,
        "avg_efficiency": summ.get("avg_efficiency", 0), "late_today": summ.get("late_today", 0),
        "incidents_today": summ.get("incidents_today", 0), "customer_avg": cst.get("avg_visit", 0),
        "repeat_customers": cst.get("repeat_customers", 0),
        "new_alert": new_alert,
        "roster": database.get_todays_shift_roster(),
        "active_list": stf,
        "alert_details": {"name": alert_name, "zone": alert_zone} if new_alert else None,
        "monthly_customers": cst.get("monthly_total", 0),
        "today_customers": today_cst.get("today_count", 0),
        "today_customer_minutes": today_cst.get("today_minutes", 0)
    })

@app.route('/api/camera/refresh')
@login_required
def refresh_camera():
    global camera_stream
    sync_camera_config()
    _onvif_cache["cam"] = None
    _onvif_cache["ptz"] = None
    _onvif_cache["profile"] = None
    _onvif_cache["port"] = None
    if camera_stream:
        print(f"[SYSTEM] Manual camera refresh triggered. RTSP_URL='{RTSP_URL}'")
        camera_stream.online = False # Forces update loop to re-probe
        return jsonify({"status": "success", "message": "Camera re-synchronization triggered."})
    return jsonify({"status": "error", "message": "Camera stream not initialized."}), 500

from requests.auth import HTTPDigestAuth
from onvif import ONVIFCamera
import zeep
import socket
import xml.etree.ElementTree as ET

_DIRECTION_VECTORS = {
    'Up':        (0,  1, 0),
    'Down':      (0, -1, 0),
    'Left':      (-1, 0, 0),
    'Right':     (1,  0, 0),
    'UpLeft':    (-1, 1, 0),
    'UpRight':   (1,  1, 0),
    'DownLeft':  (-1,-1, 0),
    'DownRight': (1, -1, 0),
    'ZoomIn':    (0, 0, 1),
    'ZoomOut':   (0, 0,-1),
}

_onvif_cache = {"cam": None, "ptz": None, "profile": None, "port": None}

def _parse_rtsp():
    """Parse PHYSICAL_RTSP_URL into (ip, user, password, rtsp_port)."""
    m = re.match(r'rtsp://(.+?):(.+?)@(.+?)(?::(\d+))?(?:/|$)', PHYSICAL_RTSP_URL)
    if m:
        return m.group(3), m.group(1), m.group(2), int(m.group(4) or 554)
    return None, None, None, None

def _get_onvif_connection():
    """Get cached ONVIF connection or create a new one."""
    if _onvif_cache["ptz"] is not None:
        return _onvif_cache["ptz"], _onvif_cache["profile"]

    ip, user, pwd, _ = _parse_rtsp()
    if not ip:
        return None, None

    onvif_ports = [80, 8080, 8899, 8000, 8081]
    for port in onvif_ports:
        try:
            cam = ONVIFCamera(ip, port, user, pwd)
            media = cam.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                continue
            profile = profiles[0]
            ptz = cam.create_ptz_service()
            _onvif_cache["cam"] = cam
            _onvif_cache["ptz"] = ptz
            _onvif_cache["profile"] = profile
            _onvif_cache["port"] = port
            print(f"[PTZ-ONVIF] Connected on port {port}, profile={profile.token}")
            return ptz, profile
        except Exception as e:
            print(f"[PTZ-ONVIF] Port {port} failed: {e}")
            continue
    return None, None

def _ptz_send(direction, action):
    """Send PTZ command via ONVIF with cached connection, fallback to CGI."""
    ptz, profile = _get_onvif_connection()
    if ptz and profile:
        try:
            if action == 'stop':
                ptz.Stop({'ProfileToken': profile.token})
                print(f"[PTZ-ONVIF] Stopped")
                return True, ""
            x, y, z = _DIRECTION_VECTORS.get(direction, (0, 0, 0))
            ptz.ContinuousMove({
                'ProfileToken': profile.token,
                'Velocity': {
                    'PanTilt': {
                        'x': float(x), 
                        'y': float(y),
                        'space': 'http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace'
                    },
                    'Zoom': {
                        'x': float(z),
                        'space': 'http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace'
                    }
                }
            })
            print(f"[PTZ-ONVIF] Moved {direction}")
            return True, ""
        except Exception as e:
            print(f"[PTZ-ONVIF] Command failed: {e}")
            _onvif_cache["ptz"] = None
            _onvif_cache["profile"] = None

    ip, user, pwd, _ = _parse_rtsp()
    if not ip:
        return False, "Could not parse camera URL"

    last_err = ""
    for http_port in ['80', '8080']:
        base = f"http://{ip}:{http_port}"
        for channel in ['1', '0']:
            url = f"{base}/cgi-bin/ptz.cgi?action={action}&channel={channel}&code={direction}&arg1=0&arg2=5"
            for auth in [None, (user, pwd), HTTPDigestAuth(user, pwd)]:
                try:
                    r = requests.get(url, timeout=3, auth=auth)
                    print(f"[PTZ-CGI] {url[:90]} -> status={r.status_code}")
                    if r.ok or 'OK' in r.text:
                        return True, ""
                    if r.status_code == 401:
                        continue
                    last_err = f"HTTP {r.status_code}: {r.text[:80]}"
                    break
                except Exception as e:
                    last_err = str(e)[:100]
                    continue

    return False, f"ONVIF unavailable, CGI failed: {last_err}"

@app.route('/api/camera/ptz', methods=['POST'])
@login_required
def camera_ptz():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Invalid JSON body"}), 400
    direction = data.get('direction', '')
    action = data.get('action', 'start')

    valid = {'Up', 'Down', 'Left', 'Right', 'UpLeft', 'UpRight', 'DownLeft', 'DownRight', 'ZoomIn', 'ZoomOut'}
    if direction not in valid:
        return jsonify({"status": "error", "message": "Invalid direction"}), 400

    ok, msg = _ptz_send(direction, action)
    if ok:
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": msg}), 502

@app.route('/api/export/attendance/<format>')
@login_required
def export_attendance(format):
    month = request.args.get('month')
    year = request.args.get('year')
    data = database.get_monthly_attendance(month, year)
    summary = database.get_comprehensive_summary()
    
    if format == 'excel':
        
        buf = export_engine.generate_attendance_excel(data)
        return send_file(buf, as_attachment=True, download_name=f"Stafflytics_Report_{datetime.now().strftime('%Y%m%d')}.xlsx")
    elif format == 'pdf':
        pdf_content = export_engine.generate_classy_pdf(summary, data)
        buf = io.BytesIO(pdf_content)
        return send_file(buf, as_attachment=True, download_name=f"Stafflytics_Executive_Report.pdf", mimetype='application/pdf')
    return "Invalid format", 400

@app.route('/api/reports/attendance')
@login_required
def get_attendance_report():
    data = database.get_monthly_attendance(request.args.get('month'), request.args.get('year'))
    report = []
    for row in data:
        entry, exit_t, name, role, hours, sal_type, is_late, active_sec = row
        eff = round((active_sec / (hours * 3600) * 100), 1) if hours > 0 else 0
        report.append({"date":str(entry)[:10], "in":str(entry)[11:16], "out":str(exit_t)[11:16] if exit_t else "--:--", 
                       "name":name, "role":role, "hours":round(hours,1), "efficiency": f"{eff}%", "status": "Late" if is_late else ("Completed" if exit_t else "Active")})
    return jsonify(report)

@app.route('/api/staff/stats/<staff_id>')
@login_required
def get_staff_stats(staff_id):
    return jsonify(database.get_staff_stats(staff_id))

@app.route('/api/analytics/customers')
@login_required
def get_customer_analytics():
    return jsonify(database.get_monthly_customer_stats())

@app.route('/api/export/custom')
@login_required
def export_custom_report():
    period = request.args.get('period', 'daily') # daily, weekly
    fmt = request.args.get('format', 'pdf') # pdf, excel
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    if period == 'weekly':
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        title = "Weekly Business Intelligence"
    else:
        start_date = end_date
        title = "Daily Operations"
        
    data = database.get_period_report_data(start_date, end_date)
    alerts = database.get_period_alerts(start_date, end_date)
    
    if fmt == 'excel':
        output = export_engine.generate_comprehensive_excel(data)
        return send_file(output, as_attachment=True, download_name=f"Stafflytics_{period}_Report.xlsx")
    else:
        output = export_engine.generate_comprehensive_pdf(title, data['summary'], data['details'], alerts)
        buf = io.BytesIO(output)
        return send_file(buf, as_attachment=True, download_name=f"Stafflytics_{period}_Report.pdf", mimetype='application/pdf')

@app.route('/api/staff/all')
@login_required
def get_all_registered_staff():
    # id, name, role, shift_start, hourly_rate, face_encoding, shift, salary_type
    return jsonify([{"id":r[0], "name":r[1], "role":r[2], "shift_time":r[3], "rate":r[4], "shift":r[6], "salary_type": r[7]} for r in database.get_all_staff()])

@app.route('/api/staff/update/<staff_id>', methods=['POST'])
@login_required
def update_staff_detail(staff_id):
    data = request.json
    database.update_staff(staff_id, data['name'], data['role'], data['shift_time'], data['shift'], data['rate'], data.get('salary_type', 'Monthly'))
    engine.load_known_faces()
    return jsonify({"status": "success"})

@app.route('/api/staff/delete/<staff_id>', methods=['DELETE'])
@login_required
def delete_staff(staff_id):
    database.delete_staff(staff_id)
    engine.load_known_faces()
    return jsonify({"status": "success"})

@app.route('/api/register', methods=['POST'])
@login_required
def register_staff():
    data = request.json
    try:
        import face_recognition # Local import
        header, encoded = data['image'].split(",", 1)
        img = Image.open(io.BytesIO(base64.b64decode(encoded)))
        enc = face_recognition.face_encodings(np.array(img.convert('RGB')))
        if not enc: return jsonify({"status": "error", "message": "No face detected"}), 400
        database.add_staff(data['id'], data['name'], data['role'], pickle.dumps(enc[0]), 
                          data.get('shift_time', '10:00'), data.get('shift', 'Morning'), data.get('rate', 500), data.get('salary_type', 'Monthly'))
        engine.load_known_faces()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/staff/enroll-with-faces', methods=['POST'])
@login_required
def enroll_staff_with_faces():
    data = request.json
    try:
        import face_recognition
        images = data.get('images', [])
        if len(images) < 2:
            return jsonify({"status": "error", "message": "Need at least 2 face captures"}), 400
        
        encodings = []
        for b64_img in images:
            try:
                header, encoded = b64_img.split(",", 1)
                img = Image.open(io.BytesIO(base64.b64decode(encoded)))
                rgb = np.array(img.convert('RGB'))
                encs = face_recognition.face_encodings(rgb)
                if encs:
                    encodings.append(encs[0])
            except Exception:
                continue
        
        if not encodings:
            return jsonify({"status": "error", "message": "No valid face detected in any capture"}), 400
        
        # Average multiple encodings for robustness
        avg_encoding = np.mean(encodings, axis=0)
        avg_encoding = avg_encoding / np.linalg.norm(avg_encoding)
        
        database.add_staff(
            data['id'], data['name'], data['role'],
            pickle.dumps(avg_encoding),
            data.get('shift_time', '10:00'),
            data.get('shift', 'Morning'),
            data.get('rate', 500),
            data.get('salary_type', 'Monthly')
        )
        engine.load_known_faces()
        return jsonify({"status": "success", "message": f"Enrolled {len(encodings)}/{len(images)} captures"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/events/all')
@login_required
def get_events():
    return jsonify([{"date":r[0], "type":r[1], "intensity":r[2]} for r in database.get_events()])

@app.route('/api/events/add', methods=['POST'])
@login_required
def add_event():
    data = request.json
    database.add_event(data['date'], data.get('type', 'Peak Day'), data.get('intensity', 'High'))
    return jsonify({"status": "success"})

@app.route('/api/events/delete/<date>', methods=['DELETE'])
@login_required
def delete_event(date):
    database.delete_event(date)
    return jsonify({"status": "success"})

@app.route('/api/zones/update', methods=['POST'])
@login_required
def update_zones():
    data = request.json
    database.save_zone_config(data['name'], str(data['points']), ",".join(data.get('unauthorized', [])))
    engine.reload_zones()
    return jsonify({"status": "success"})

@app.route('/api/settings/emails', methods=['GET', 'POST'])
@login_required
def email_settings():
    if request.method == 'POST':
        database.update_system_settings(request.json)
        sync_mailer_config()
        sync_camera_config()
        sync_camera_preset()
        return jsonify({"status": "success"})
    return jsonify(database.get_system_settings())

@app.route('/api/camera/test', methods=['POST'])
@login_required
def test_camera():
    data = request.json
    url = data.get('url', '')
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"})

    backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]
    result = {"status": "error", "message": "Could not connect"}

    def try_connect(test_url, be, results):
        try:
            cap = cv2.VideoCapture(test_url, be)
            if cap:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
            if cap and cap.isOpened():
                ret, f = cap.read()
                if ret and f is not None:
                    display = test_url.split('://')[0] + '://[credentials]@' + test_url.split('@')[1] if '@' in url else test_url
                    results.append({"status": "success", "message": f"Connected: {display}"})
            if cap: cap.release()
        except:
            pass

    # 1) Try user's exact URL first
    for be in backends:
        thread_results = []
        t = threading.Thread(target=try_connect, args=(url, be, thread_results))
        t.daemon = True
        t.start()
        t.join(timeout=10)
        if thread_results:
            return jsonify(thread_results[0])

    # 2) Try user's exact URL with TCP
    tcp_url = url + ("&tcp" if "?" in url else "?tcp")
    for be in backends:
        thread_results = []
        t = threading.Thread(target=try_connect, args=(tcp_url, be, thread_results))
        t.daemon = True
        t.start()
        t.join(timeout=10)
        if thread_results:
            return jsonify(thread_results[0])

    # 3) Try with path variants
    m = re.match(r'(rtsp://[^@]+@[^/]+|rtsp://[^/]+)', url)
    base = m.group(1) if m else url
    paths = [
        '/cam/realmonitor?channel=1&subtype=0',
        '/cam/realmonitor?channel=1&subtype=1',
        '/cam/realmonitor?channel=1&subtype=0&unicast=true&proto=Onvif',
        '/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif',
        '/cam/realmonitor?channel=1&subtype=00',
        '/stream1', '/Streaming/Channels/101',
        '/h264/ch1/main/av_stream', '/h264_stream',
        '/onvif1', '/onvif/stream2',
        '/live', '/video', '/video1', '/videoMain', '/h264',
    ]
    for p in paths:
        tcp_suffix = "&tcp" if "?" in p else "?tcp"
        for suffix in ['', tcp_suffix]:
            test_url = f"{base}{p}{suffix}"
            for be in backends:
                thread_results = []
                t = threading.Thread(target=try_connect, args=(test_url, be, thread_results))
                t.daemon = True
                t.start()
                t.join(timeout=10)
                if thread_results:
                    return jsonify(thread_results[0])

    return jsonify({"status": "error", "message": "Camera not reachable. Check: 1) Camera powered on  2) IP correct  3) RTSP enabled in Imou app  4) No firewall blocking port 554  5) Try subtype=1 for H.264 sub-stream"})

import sqlite3
if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True, use_reloader=False)
