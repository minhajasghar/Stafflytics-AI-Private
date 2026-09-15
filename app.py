import threading
import os
# Suppress FFmpeg/HEVC decoder noise before any OpenCV/FFmpeg init
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|max_delay;2000000"
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
os.environ["FFREPORT"] = "level=quiet"
from dotenv import load_dotenv
load_dotenv()
# Also load from the app's own directory so the Imou/DB config is found even
# when the process is launched from a different working directory.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
from flask import Flask, render_template, Response, jsonify, request, session, redirect, url_for
from flask_sock import Sock
import json
import cv2
import database
# Heavy imports moved to background thread
# from vision_engine import VisionEngine
# import face_recognition
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
import imou_client

# Stafflytics AI Configuration
app = Flask(__name__)
app.secret_key = 'signature_secret_key_stafflytics_2026'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
sock = Sock(app)

# Imou Open Platform client — credentials always come from .env (never hardcoded).
imou = imou_client.ImouClient()

# Redirect werkzeug request logger to stdout — avoids '--- Logging error ---' on Windows
# when stderr is in a broken/inconsistent state after FFmpeg fd manipulation.
import logging as _logging, sys as _sys
_wz_logger = _logging.getLogger('werkzeug')
_wz_logger.handlers.clear()
_wz_logger.addHandler(_logging.StreamHandler(_sys.stdout))
_wz_logger.setLevel(_logging.INFO)


websocket_clients = set()
websocket_lock = threading.Lock()
last_detection_payload = json.dumps({"detections": [], "frame_w": 640, "frame_h": 480, "passage": {"l_to_r": 0, "r_to_l": 0}})

def broadcast_detections(detections, frame_w=640, frame_h=360, passage=None):
    global last_detection_payload
    if passage is None and engine is not None:
        try:
            passage = engine.get_passage_counts()
        except:
            passage = {"l_to_r": 0, "r_to_l": 0}
    def _json_serial(obj):
        if isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return str(obj)

    payload = json.dumps({
        "detections": detections, 
        "frame_w": frame_w, 
        "frame_h": frame_h,
        "passage": passage or {"l_to_r": 0, "r_to_l": 0}
    }, default=_json_serial)
    last_detection_payload = payload
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

@app.route('/api/detection_poll', methods=['GET'])
def detection_poll():
    # Fallback polling endpoint if WebSocket Upgrade is stripped by reverse proxy (like Apache)
    global last_detection_payload
    return Response(last_detection_payload, mimetype='application/json')


# Initialize database & Mailer
engine = None         # Initialized asynchronously
camera_stream = None  # AI stream: cam_ai (H.264 640x480) — used by YOLO/vision engine
display_stream = None # Display stream: cam (full HD relay) — used by video_feed

# RTSP Camera Configuration
_DEFAULT_PHYSICAL_RTSP_URL = "rtsp://admin:L2DD2594@192.168.50.251:554/cam/realmonitor?channel=1&subtype=0"
PHYSICAL_RTSP_URL = _DEFAULT_PHYSICAL_RTSP_URL
RTSP_URL = "rtsp://127.0.0.1:8554/cam"   # AI stream: using /cam directly since WebRTC confirms it works
DISPLAY_RTSP_URL = "rtsp://127.0.0.1:8554/cam"  # Display stream: full HD relay

def sync_camera_config():
    global RTSP_URL, PHYSICAL_RTSP_URL
    import stream_manager

    # --- REMOTE RTSP MODE (default, env-var driven). ---
    # When CAMERA_SOURCE_MODE=remote_rtsp, MediaMTX pulls directly from
    # REMOTE_RTSP_URL (e.g. a Tailscale peer). No local camera or Imou bridge
    # is used. Must be checked BEFORE the legacy local-RTSP block so that
    # set_stream_mode("rtsp") and setup_mediamtx() are never called in this mode.
    if stream_manager.CAMERA_SOURCE_MODE == "remote_rtsp":
        # Always read from the database first — this is what the user saved in Settings.
        conf = database.get_system_settings()
        saved_url = conf.get('rtsp_url', '').strip()
        if saved_url:
            # Pass it explicitly so the stream manager uses the latest saved URL.
            stream_manager.setup_remote_rtsp_stream(remote_url=saved_url)
            PHYSICAL_RTSP_URL = saved_url
        else:
            stream_manager.setup_remote_rtsp_stream()
            if stream_manager.REMOTE_RTSP_URL:
                PHYSICAL_RTSP_URL = stream_manager.REMOTE_RTSP_URL
        RTSP_URL = "rtsp://127.0.0.1:8554/cam"  # Read directly from H.264 cam path
        print(f"[SYSTEM] REMOTE RTSP MODE active — pulling from {stream_manager.REMOTE_RTSP_URL}")
        return


    # --- LEGACY LOCAL-RTSP MODE (deactivated when Imou is configured). ---
    stream_manager.set_stream_mode("rtsp")
    conf = database.get_system_settings()
    saved = conf.get('rtsp_url', '')
    if saved and saved.strip():
        url = saved.strip()
        # Ensure we always use subtype=0 (main stream, full HD) for display.
        # The HEVC errors are fixed by the dual-stream architecture below:
        # MediaMTX relays it over TCP, and cam_ai transcodes to H.264 for AI.
        if 'subtype=1' in url and 'subtype=10' not in url:
            url = url.replace('subtype=1', 'subtype=0')
            database.update_system_settings({'rtsp_url': url})
            print(f"[SYSTEM] Restored RTSP subtype=0 (full HD) — dual-stream handles HEVC stability.")
        PHYSICAL_RTSP_URL = url
        print(f"[SYSTEM] PHYSICAL_RTSP_URL updated to: '{PHYSICAL_RTSP_URL}'")
    
    # Configure and restart local MediaMTX proxy with the physical camera URL.
    # MediaMTX creates two paths:
    #   cam     — raw relay of the physical camera (full HD, for display)
    #   cam_ai  — H.264 640x480 transcode (for OpenCV/YOLO, eliminates HEVC errors)
    stream_manager.setup_mediamtx(PHYSICAL_RTSP_URL)

    # AI processing reads from the H.264 transcoded path — stable, no HEVC decode errors
    RTSP_URL = "rtsp://127.0.0.1:8554/cam"
    print(f"[SYSTEM] RTSP_URL for AI set to: '{RTSP_URL}' (H.264 transcoded)")
QUALITY_PRESETS = {
    "480p": {"size": (640, 480), "jpeg": 85, "label": "Standard (480p)"},
    "720p": {"size": (1280, 720), "jpeg": 90, "label": "Enhanced (720p)"},
    "1080p": {"size": (1920, 1080), "jpeg": 95, "label": "HD (1080p)"}
}

def sync_camera_preset():
    global camera_preset, camera_quality, camera_width, camera_height
    conf = database.get_system_settings()
    preset = conf.get('camera_preset', '720p')
    if preset not in QUALITY_PRESETS:
        preset = '720p'
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
camera_preset = "720p"
camera_quality = 90
camera_width = 1280
camera_height = 720

latest_processed_frame = None
processed_frame_lock = threading.Lock()

import atexit

def cleanup_streams():
    print("[SYSTEM] Cleaning up streaming subprocesses...")
    try:
        import stream_manager
        stream_manager.stop_imou_bridge()
        stream_manager.stop_mediamtx()
    except:
        pass

atexit.register(cleanup_streams)

class CameraStream:
    def __init__(self, rtsp_override=None):
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
        self.actual_width = 640
        self.actual_height = 480
        self.rtsp_override = rtsp_override  # If set, use this URL instead of global RTSP_URL
        
    def start(self):
        # Start the background update thread immediately
        if not any(t.name == "CameraUpdateThread" for t in threading.enumerate()):
            threading.Thread(target=self.update, daemon=True, name="CameraUpdateThread").start()
        return self

    def _attempt_connection(self):
        global camera_online
        import stream_manager
        # Use override URL if specified (display_stream uses cam, camera_stream uses cam_ai)
        active_url = self.rtsp_override if self.rtsp_override else RTSP_URL
        
        # [Fallback logic]: No fallback to raw camera. We MUST read from mediamtx /cam path.
        # If it's offline, OpenCV will keep trying until it comes online.
        if active_url == RTSP_URL:
            pass

        print(f"[SYSTEM] Starting Camera Synchronization Loop... (URL='{active_url}')")
        if self.stream is not None:
            try: self.stream.release()
            except: pass
            self.stream = None

        # Try RTSP URL with multiple common stream paths
        if active_url:
            rtsp_variants = []

            # 1) ALWAYS try the user's exact URL first (most important!)
            rtsp_variants.append(active_url)

            # Only try camera-specific fallbacks if connecting to a remote camera directly
            if "localhost" not in active_url and "127.0.0.1" not in active_url:
                # 2) Try with TCP transport on the exact URL
                if '?' in active_url:
                    rtsp_variants.append(active_url + "&tcp")
                else:
                    rtsp_variants.append(active_url + "?tcp")

                # 3) Extract base and try Imou/Dahua-specific paths
                m = re.match(r'(rtsp://[^@]+@[^/]+|rtsp://[^/]+)', active_url)
                base = m.group(1) if m else active_url

                paths = [
                    '/cam/realmonitor?channel=1&subtype=1',
                    '/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif',
                    '/cam/realmonitor?channel=1&subtype=0',
                    '/cam/realmonitor?channel=1&subtype=0&unicast=true&proto=Onvif',
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
                                self.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                                self.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                                print(f"[SYSTEM] Camera native resolution: {self.actual_width}x{self.actual_height}")
                                self.online = True
                                camera_online = True
                                return True
                        if cap: cap.release()
                    except Exception as e:
                        print(f"[RTSP PROBE ERROR] {e}")
                        continue

        # Fallback to local camera indices — legacy RTSP-mode behaviour only.
        # In Imou mode the source is the Imou HLS -> cam_ai relay; we must NOT
        # silently switch to a webcam, otherwise camera_online would be a lie.
        if stream_manager.STREAM_MODE != "imou":
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
                                preset_cfg = QUALITY_PRESETS.get(camera_preset, QUALITY_PRESETS['480p'])
                                cap.set(cv2.CAP_PROP_FRAME_WIDTH, preset_cfg["size"][0])
                                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, preset_cfg["size"][1])
                                cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
                                self.actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                                self.actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                                print(f"[SYSTEM] Camera native resolution: {self.actual_width}x{self.actual_height}")
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
                if self.stream is not None:
                    try: self.stream.release()
                    except: pass
                    self.stream = None
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
                # Drop stale frames so only the freshest frame is passed to inference
                if hasattr(self, 'stream') and self.stream is not None and self.stream.isOpened():
                    self.stream.grab()
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1
                    self.frame_buffer.append((frame.copy(), self.frame_id))
                # Heartbeat for the Imou bridge watchdog (HLS stall detection).
                try:
                    import stream_manager
                    if stream_manager.STREAM_MODE == "imou":
                        stream_manager.mark_imou_frame_received()
                except Exception:
                    pass
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
            
            # Use user-selected resolution — honor the setting rather than capping to camera native
            tw = camera_width or 640
            th = camera_height or 480
            raw_frame, detections = engine.process_frame(frame, target_size=(tw, th), original_frame=frame)
            
            with processed_frame_lock:
                latest_processed_frame = raw_frame.copy() if raw_frame is not None else None
            
            # Broadcast detection coordinates to all websocket clients.
            # frame_w/frame_h = the native detection space (cam_ai res, 16:9),
            # so the browser canvas can scale boxes to the video exactly.
            broadcast_detections(detections, frame_w=frame.shape[1], frame_h=frame.shape[0])
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
        print("[SYSTEM] Database Ready.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Database init failed: {e}")

    # Each subsystem is independent — a failure in one must not prevent the
    # camera/Imou stream from starting (e.g. DB unavailable).
    try:
        sync_mailer_config()
    except Exception as e:
        print(f"[SYSTEM ERROR] Mailer config sync failed: {e}")

    try:
        sync_camera_config()
    except Exception as e:
        print(f"[SYSTEM ERROR] Camera config sync failed: {e}")

    try:
        sync_camera_preset()
    except Exception as e:
        print(f"[SYSTEM ERROR] Camera preset sync failed: {e}")

    # Check and download streaming binaries in background
    try:
        init_status = "Checking streaming binaries..."
        import stream_manager
        stream_manager.ensure_binaries_async()
    except Exception as e:
        print(f"[SYSTEM ERROR] Streaming binary setup failed: {e}")

    # Release the UI early
    system_initializing = False
    init_status = "Dashboard Ready. AI & Camera loading in background..."
    
    # 2. Init Vision Engine (Lazy Loading starts inside)
    try:
        init_status = "Warmup Vision Engine..."
        from vision_engine import VisionEngine
        engine = VisionEngine()
        engine.warmup()  # Preload the YOLO model so detection is ready immediately
        print("[SYSTEM] Vision Engine loaded successfully.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Vision Engine failed: {e}")
        
    # 3. Init Camera Streams (dual-stream architecture)
    try:
        init_status = "Connecting AI Camera Stream..."
        # cam_ai: H.264 640x480 transcoded by MediaMTX — used by YOLO, no HEVC errors
        camera_stream = CameraStream().start()
        print("[SYSTEM] AI camera stream (cam_ai) started.")
        # Start background vision analytics loop thread
        threading.Thread(target=vision_engine_loop, daemon=True, name="VisionEngineLoopThread").start()
    except Exception as e:
        print(f"[SYSTEM ERROR] AI camera stream failed: {e}")

    try:
        init_status = "Connecting Display Camera Stream..."
        # cam: full HD relay — used by /video_feed for crystal-clear display.
        # In Imou HLS mode cam carries the raw HEVC relay (which OpenCV may not
        # decode reliably), so the MJPEG fallback feed reads cam_ai (H.264)
        # instead. The browser plays the Imou HLS directly for the main view.
        import stream_manager
        display_url = RTSP_URL if stream_manager.STREAM_MODE == "imou" else DISPLAY_RTSP_URL
        display_stream = CameraStream(rtsp_override=display_url).start()
        print(f"[SYSTEM] Display camera stream ({display_url}) started.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Display camera stream failed (non-critical): {e}")

    # 4. Pre-connect ONVIF for PTZ (saves ~18s on first click). Skipped in Imou
    # HLS mode: PTZ is handled by the Imou API, and we must NOT dial out to the
    # physical camera over ONVIF/RTSP when the source is Imou HLS only.
    try:
        import stream_manager
        if stream_manager.STREAM_MODE != "imou":
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
    global camera_stream, display_stream, engine, system_initializing, camera_quality, camera_width, camera_height, latest_processed_frame

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

            # If all camera streams are offline, return CAM OFFLINE.
            # In Imou mode only cam_ai is consumed (cam may be HEVC); never show
            # OFFLINE while at least one stream is producing frames.
            streams = [s for s in (display_stream, camera_stream) if s is not None]
            if not any(s.online for s in streams):
                err = np.zeros((camera_height or 480, camera_width or 640, 3), np.uint8)
                cv2.putText(err, "CAMERA OFFLINE", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (50, 50, 255), 3)
                ret, buf = cv2.imencode('.jpg', err)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(1); continue


            # Prefer the full-res display_stream frame for a sharp MJPEG feed.
            # latest_processed_frame comes from cam_ai (640x480) and is blurry
            # when upscaled — only use it if display_stream is unavailable.
            display_frame = None
            buf_frame_id = -1

            if display_stream is not None and display_stream.online:
                res, fid = display_stream.read_buffered()
                if res is not None:
                    if fid == last_sent_frame_id:
                        time.sleep(0.01)
                        continue
                    display_frame = res
                    buf_frame_id = fid

            if display_frame is None:
                # Fall back to processed frame (may be low-res) if display stream not ready
                with processed_frame_lock:
                    display_frame = latest_processed_frame.copy() if latest_processed_frame is not None else None

            # Last resort: read from any online stream
            if display_frame is None:
                src = next((s for s in streams if s.online), None)
                if src:
                    res, fid = src.read_buffered()
                    if res is not None:
                        if fid == last_sent_frame_id:
                            time.sleep(0.01)
                            continue
                        display_frame = res
                        buf_frame_id = fid
                    else:
                        time.sleep(0.05)
                        continue
                else:
                    time.sleep(0.05)
                    continue
            
            # Overlay Bounding Boxes on the raw display feed
            if engine and hasattr(engine, 'latest_detections') and engine.latest_detections:
                try:
                    from vision_engine import draw_detections_on_frame
                    # Ensure camera_stream is defined; use its dims for scaling detection coordinates
                    if 'camera_stream' in globals() and camera_stream.actual_width and camera_stream.actual_height:
                        src_w, src_h = camera_stream.actual_width, camera_stream.actual_height
                    else:
                        src_w, src_h = 640, 480 # Fallback
                    display_frame = draw_detections_on_frame(display_frame, engine.latest_detections, src_w, src_h)
                except Exception as e:
                    pass

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
    # Legacy WebRTC/MediaMTX path — kept but deactivated when Imou HLS is active.
    import stream_manager
    return jsonify({
        "complete": stream_manager.download_complete,
        "status": stream_manager.download_status,
        "error": stream_manager.download_error
    })

@app.route('/api/webrtc/whep', methods=['POST', 'OPTIONS'])
@login_required
def webrtc_whep_proxy():
    """Proxy the WHEP SDP offer/answer exchange to MediaMTX.

    Tries in order:
    1) 127.0.0.1:8889 — VPS-local MediaMTX (stream_manager manages this)
    2) <remote_tailscale_host>:8889 — the Tailscale peer running MediaMTX
       (parsed from REMOTE_RTSP_URL / the saved DB camera URL)

    This avoids exposing port 8889 publicly and fixes mixed-content blocks
    when the site is served over HTTPS.
    """
    if request.method == 'OPTIONS':
        resp = Response('', status=204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    sdp_offer = request.get_data(as_text=True)
    if not sdp_offer:
        return jsonify({"error": "No SDP offer provided"}), 400

    # Build list of MediaMTX hosts to try: local first, then the Tailscale peer
    mediamtx_hosts = ['127.0.0.1']
    try:
        import stream_manager
        remote_url = stream_manager.REMOTE_RTSP_URL
        if not remote_url:
            # Fall back to the RTSP URL saved in the database
            remote_url = database.get_system_settings().get('rtsp_url', '')
        if remote_url:
            # Parse host out of rtsp://[user:pass@]host[:port]/path
            m = re.match(r'rtsp://(?:[^@]+@)?([^:/]+)', remote_url)
            if m:
                tailscale_host = m.group(1)
                if tailscale_host not in mediamtx_hosts:
                    mediamtx_hosts.append(tailscale_host)
    except Exception as e:
        print(f"[WHEP PROXY] Could not resolve remote host: {e}")

    last_err = None
    for host in mediamtx_hosts:
        whep_url = f'http://{host}:8889/cam/whep'
        try:
            r = requests.post(
                whep_url,
                data=sdp_offer,
                headers={'Content-Type': 'application/sdp'},
                timeout=8
            )
            if r.ok:
                print(f"[WHEP PROXY] Success via {host}")
                resp = Response(r.text, status=r.status_code, mimetype='application/sdp')
                resp.headers['Access-Control-Allow-Origin'] = '*'
                return resp
            print(f"[WHEP PROXY] {host} returned {r.status_code}: {r.text[:100]}")
            last_err = f"HTTP {r.status_code} from {host}"
        except Exception as e:
            print(f"[WHEP PROXY] {host} unreachable: {e}")
            last_err = str(e)

    print(f"[WHEP PROXY] All hosts failed. Last error: {last_err}")
    return jsonify({"error": last_err or "MediaMTX unreachable"}), 502

# ---------------------------------------------------------------------------
# Stream status endpoints
# ---------------------------------------------------------------------------

def _stream_mode_json():
    import stream_manager
    return {
        "mode": stream_manager.STREAM_MODE,
        "enabled": False,   # Imou is disabled — this software does not use Imou.
        "camera_online": camera_online,
    }

@app.route('/api/stream/status')
@login_required
def stream_status():
    return jsonify(_stream_mode_json())

@app.route('/api/stream/playlist')
def stream_playlist():
    """Proxied Imou m3u8. Re-fetched from Imou on every request (never cached)
    and every segment URI is rewritten to go through our /segment proxy. If the
    cached live URL is stale, this auto-regenerates it before serving.
    Unauthenticated on purpose: consumed by the browser via hls.js AND by the
    backend ffmpeg bridge (which has no session cookie)."""
    if not imou_client.imou_enabled():
        return jsonify({"status": "error", "message": "Imou not enabled"}), 503
    try:
        base = request.host_url
        playlist, used = imou.fetch_playlist(base)
        body = imou_client.rewrite_playlist(playlist, used, base)
        resp = Response(body, mimetype='application/vnd.apple.mpegurl')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        print(f"[STREAM] playlist error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 502

@app.route('/api/stream/segment')
def stream_segment():
    """Proxy a single Imou .ts segment (handles CORS + signed/expiring URLs)."""
    seg_url = request.args.get('u', '')
    if not seg_url:
        return jsonify({"status": "error", "message": "missing u param"}), 400
    try:
        r = requests.get(seg_url, timeout=30, stream=True)
        if r.status_code != 200:
            return Response("segment unavailable", status=502)
        def generate():
            try:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            except Exception:
                # CDN closed the connection prematurely — stop the generator
                # cleanly rather than letting the exception propagate to WSGI.
                return
            finally:
                r.close()
        resp = Response(generate(), mimetype='video/mp2t')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        print(f"[STREAM] segment error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 502

@app.route('/api/stream/refresh', methods=['POST'])
@login_required
def stream_refresh():
    """Force-regenerate the Imou live URL + restart the HLS->RTSP bridge.
    Called by the frontend when it detects a frozen/stalled stream."""
    import stream_manager
    if not imou_client.imou_enabled():
        return jsonify({"status": "error", "message": "Imou not enabled"}), 503
    try:
        url = imou.get_live_url(force=True)
        stream_manager._restart_imou_bridge()
        return jsonify({"status": "success", "source": url})
    except Exception as e:
        print(f"[STREAM] refresh error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 502

def generate_recording_frames():
    """Yields processed frames with bounding boxes for the 24/7 recorder."""
    global latest_processed_frame, engine, camera_stream
    while True:
        with processed_frame_lock:
            frame = latest_processed_frame.copy() if latest_processed_frame is not None else None
        
        if frame is None:
            time.sleep(0.1)
            continue
            
        if engine and hasattr(engine, 'latest_detections') and engine.latest_detections:
            try:
                from vision_engine import draw_detections_on_frame
                if 'camera_stream' in globals() and camera_stream is not None and camera_stream.actual_width and camera_stream.actual_height:
                    src_w, src_h = camera_stream.actual_width, camera_stream.actual_height
                else:
                    src_w, src_h = 640, 480
                frame = draw_detections_on_frame(frame, engine.latest_detections, src_w, src_h)
            except Exception:
                pass
            
        ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if ret:
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
        time.sleep(0.1)  # ~10 FPS matching vision_engine_loop

@app.route('/api/recording_feed')
def recording_feed():
    return Response(generate_recording_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

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
    data = database.get_shift_optimization_data()
    suggestions = chatbot.generate_shift_suggestions(data)
    return jsonify({"data": data, "suggestions": suggestions})

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

    # Process pending security emails — snapshot person_states under lock to avoid
    # RuntimeError: dictionary changed size during iteration (vision loop writes concurrently)
    new_alert = False
    alert_name = ""
    alert_zone = ""
    if engine:
        with engine.lock:
            pending_alerts = {tid: state.pop("needs_security_email")
                              for tid, state in engine.person_states.items()
                              if "needs_security_email" in state}
            alert_names = {tid: state.get("name", "Unknown")
                           for tid, state in engine.person_states.items()
                           if tid in pending_alerts}
        for tid, zone_name in pending_alerts.items():
            new_alert = True
            alert_name = alert_names.get(tid, "Unknown")
            alert_zone = zone_name
            html = mailer.get_security_alert_template(alert_name, alert_zone)
            mailer.send_email_async(mailer.OWNER_EMAIL, f"SECURITY ALERT: Unauthorized Entry in {alert_zone}", html)

    # Get active staff AFTER processing alerts so the list is up-to-date
    stf = engine.get_active_staff() if engine else []

    p_stats = database.get_passage_stats()
    if engine:
        try:
            live = engine.get_passage_counts()
            p_stats["l_to_r"] = max(p_stats.get("l_to_r", 0), live.get("l_to_r", 0))
            p_stats["r_to_l"] = max(p_stats.get("r_to_l", 0), live.get("r_to_l", 0))
        except: pass

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
        "today_customer_minutes": today_cst.get("today_minutes", 0),
        "passage": p_stats
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

def _parse_rtsp_url(url):
    """Parse an RTSP URL into (ip, user, password, rtsp_port)."""
    m = re.match(r'rtsp://(?:(.+?):(.+?)@)?([^:/]+)(?::(\d+))?(?:/|$)', url)
    if m:
        return m.group(3), m.group(1), m.group(2), int(m.group(4) or 554)
    return None, None, None, None

def _camera_targets():
    """Candidate PTZ targets ordered by priority:
    1) the remote tailscale bridge (if remote_rtsp mode is used),
    2) the default physical camera,
    3) the active camera source fallback."""
    import stream_manager
    targets = []
    default = _parse_rtsp_url(_DEFAULT_PHYSICAL_RTSP_URL)
    
    # 1. If remote_rtsp is active, use the remote URL host (Tailscale IP)
    if stream_manager.CAMERA_SOURCE_MODE == "remote_rtsp" and stream_manager.REMOTE_RTSP_URL:
        remote = _parse_rtsp_url(stream_manager.REMOTE_RTSP_URL)
        if remote[0]:
            if not remote[1]: # Inherit credentials from default camera if none provided
                remote = (remote[0], default[1], default[2], remote[3])
            targets.append(remote)

    # 2. Always try the hardcoded physical camera (local network fallback)
    if default[0]:
        targets.append(default)
        
    # 3. Also try the active relay host in case it's different
    t = _parse_rtsp_url(PHYSICAL_RTSP_URL)
    if t[0] and t[0] != default[0] and (not targets or t[0] != targets[0][0]):
        if not t[1]:
            t = (t[0], default[1], default[2], t[3])
        targets.append(t)
        
    return targets

def _get_onvif_connection():
    """Get cached ONVIF connection or create a new one."""
    if _onvif_cache["ptz"] is not None:
        return _onvif_cache["ptz"], _onvif_cache["profile"]

    onvif_ports = [80, 8080, 8899, 8000, 8081]
    for ip, user, pwd, _ in _camera_targets():
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
                print(f"[PTZ-ONVIF] Connected on {ip}:{port}, profile={profile.token}")
                return ptz, profile
            except Exception as e:
                print(f"[PTZ-ONVIF] {ip}:{port} failed: {e}")
                continue
    return None, None

def _ptz_send(direction, action):
    """Send a PTZ command via ONVIF with a CGI fallback, targeting the active
    camera source (the remote RTSP host on the VPS, not a hardcoded local IP).
    The Imou Open Platform API is NOT used."""
    # --- ONVIF with CGI fallback ---
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

    last_err = ""
    for ip, user, pwd, _ in _camera_targets():
        for http_port in ['5003', '80', '8080']:
            base = f"http://{ip}:{http_port}"
            for channel in ['1', '0']:
                if http_port == '5003':
                    url = f"{base}/ptz?action={action}&channel={channel}&code={direction}&arg1=0&arg2=5"
                else:
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
    print(f"[PTZ] FAILED {direction}/{action} against hosts "
          f"{[t[0] for t in _camera_targets()]}: {msg}")
    return jsonify({"status": "error", "message": msg}), 502

def _tcp_reachable(ip, port, timeout=2):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

@app.route('/api/camera/ptz/diagnose')
@login_required
def camera_ptz_diagnose():
    """Browser-visible PTZ diagnosis: which camera hosts are TCP-reachable from
    this server, and whether Dahua CGI authentication succeeds on them. Lets the
    user see exactly why camera movement fails without SSH access."""
    report = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "targets": []}
    for ip, user, pwd, _ in _camera_targets():
        entry = {
            "host": ip,
            "user": user or "(none)",
            "tcp80": _tcp_reachable(ip, 80),
            "tcp8080": _tcp_reachable(ip, 8080),
            "cgi_auth": {},
        }
        probe_port = "80" if entry["tcp80"] else "8080" if entry["tcp8080"] else None
        if probe_port:
            url = f"http://{ip}:{probe_port}/cgi-bin/magicBox.cgi?action=getSystemInfo"
            for name, a in (("no-auth", None), ("basic", (user, pwd)), ("digest", HTTPDigestAuth(user, pwd))):
                try:
                    r = requests.get(url, timeout=3, auth=a)
                    entry["cgi_auth"][name] = str(r.status_code)
                except Exception as e:
                    entry["cgi_auth"][name] = f"err: {str(e)[:50]}"
        report["targets"].append(entry)
@app.route('/api/passage/stats')
@login_required
def passage_stats():
    """Returns today's bidirectional passage statistics (Left-to-Right and Right-to-Left)."""
    stats = database.get_passage_stats()
    if engine:
        try:
            live = engine.get_passage_counts()
            stats["l_to_r"] = max(stats.get("l_to_r", 0), live.get("l_to_r", 0))
            stats["r_to_l"] = max(stats.get("r_to_l", 0), live.get("r_to_l", 0))
            stats["total"] = stats["l_to_r"] + stats["r_to_l"]
        except: pass
    return jsonify(stats)

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
    date_param = request.args.get('date')
    month_param = request.args.get('month')
    year_param = request.args.get('year')
    if date_param:
        data = database.get_daily_attendance(date_param)
    elif month_param and year_param:
        data = database.get_monthly_attendance(month_param, year_param)
    else:
        date_param = datetime.now().strftime("%Y-%m-%d")
        data = database.get_daily_attendance(date_param)
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
    return jsonify([{"id":r[0], "name":r[1], "role":r[2], "shift_time":r[3], "rate":r[4], "shift":r[6], "salary_type": r[7], "photo": r[8]} for r in database.get_all_staff()])

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

@app.route('/api/staff/enroll', methods=['POST'])
@login_required
def enroll_staff():
    data = request.json
    try:
        from vision_engine import face_rec_lock, _encode_face, _get_best_face
        header, encoded = data['image'].split(",", 1)
        img = Image.open(io.BytesIO(base64.b64decode(encoded)))
        bgr = np.ascontiguousarray(cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR))
        # --- DEBUG: Verify frame is valid before detection ---
        print(f"[DEBUG ENROLL] shape={bgr.shape} mean={bgr.mean():.2f} dtype={bgr.dtype}")
        cv2.imwrite('/tmp/debug_enroll_single.jpg', bgr)
        with face_rec_lock:
            enc = _encode_face(bgr, strict=False)
            face = _get_best_face(bgr)
        if enc is None or face is None:
            return jsonify({"status": "error", "message": "No valid face detected (ensure good lighting and distance)"}), 400
        
        # Crop the face for the thumbnail
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        margin = 80
        h_rgb, w_rgb = bgr.shape[:2]
        y1_c = max(0, y1 - margin)
        y2_c = min(h_rgb, y2 + margin)
        x1_c = max(0, x1 - margin)
        x2_c = min(w_rgb, x2 + margin)
        rgb = np.array(img.convert('RGB'))
        face_pil = Image.fromarray(rgb[y1_c:y2_c, x1_c:x2_c])
        buf = io.BytesIO()
        face_pil.save(buf, format='JPEG', quality=90)
        b64_face = base64.b64encode(buf.getvalue()).decode('utf-8')
        photo_b64 = f"data:image/jpeg;base64,{b64_face}"
        
        database.add_staff(data['id'], data['name'], data['role'], pickle.dumps([enc]),
                          data.get('shift_time', '10:00'), data.get('shift', 'Morning'), data.get('rate', 500), data.get('salary_type', 'Monthly'), photo_b64)
        engine.load_known_faces()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/staff/enroll-with-faces', methods=['POST'])
@login_required
def enroll_staff_with_faces():
    data = request.json
    try:
        from vision_engine import face_rec_lock, _encode_face, _get_best_face
        images = data.get('images', [])
        if len(images) < 1:
            return jsonify({"status": "error", "message": "Need at least 1 face capture"}), 400
        
        encodings = []
        first_photo = None
        for idx, b64_img in enumerate(images):
            try:
                header, encoded = b64_img.split(",", 1)
                img_bytes = base64.b64decode(encoded)
                pil_img = Image.open(io.BytesIO(img_bytes))
                rgb = np.array(pil_img.convert('RGB'))
                bgr = np.ascontiguousarray(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

                # --- DEBUG: Dump received frame to verify it's not empty/black ---
                cv2.imwrite('/tmp/debug_enroll_%d.jpg' % idx, bgr)
                print(f"[DEBUG ENROLL] Capt idx={idx} shape={bgr.shape} mean={bgr.mean():.2f} dtype={bgr.dtype}")
                if bgr.mean() < 1.0:
                    print(f"[DEBUG ENROLL] WARNING: Frame {idx} is BLACK/EMPTY! mean={bgr.mean():.2f}")

                # Verify BGR format (not RGB) - InsightFace expects OpenCV BGR arrays
                if len(bgr.shape) != 3 or bgr.shape[2] != 3:
                    print(f"[DEBUG ENROLL] ERROR: Invalid BGR shape {bgr.shape} at idx={idx}")
                    continue

                # Detect face location first, then crop to face for encoding
                with face_rec_lock:
                    face = _get_best_face(bgr)
                    # Use strict=False for enrollment so webcam photos don't fail FIQA
                    enc = _encode_face(bgr, strict=False) if face is not None else None
                    print(f"[DEBUG ENROLL] Capt idx={idx} shape={bgr.shape} face_found={face is not None} enc_found={enc is not None}")
                if enc is None:
                    continue
                encodings.append(enc)
                if idx == 0 or first_photo is None:
                    x1, y1, x2, y2 = [int(v) for v in face.bbox]
                    x, y, w_b, h_b = x1, y1, x2 - x1, y2 - y1
                    margin = 80
                    h_rgb, w_rgb = rgb.shape[:2]
                    y1 = max(0, y - margin)
                    y2 = min(h_rgb, y + h_b + margin)
                    x1 = max(0, x - margin)
                    x2 = min(w_rgb, x + w_b + margin)
                    face_pil = Image.fromarray(rgb[y1:y2, x1:x2])
                    buf = io.BytesIO()
                    face_pil.save(buf, format='JPEG', quality=90)
                    b64_face = base64.b64encode(buf.getvalue()).decode('utf-8')
                    first_photo = f"data:image/jpeg;base64,{b64_face}"
            except Exception as e:
                import traceback
                print(f"[ENROLL ERROR] Capture {idx} failed: {e}")
                traceback.print_exc()
                continue
        
        if not encodings:
            from vision_engine import _face_models_loaded, _last_ai_error
            if not _face_models_loaded:
                return jsonify({"status": "error", "message": f"CRITICAL: AI Models failed to load on this server (VPS). Error: {_last_ai_error}"}), 500
            elif _last_ai_error:
                return jsonify({"status": "error", "message": f"CRITICAL: Face detection crashed on this server. Error: {_last_ai_error}"}), 500
            return jsonify({"status": "error", "message": "No valid face detected in any capture"}), 400
        
        # Store ALL individual encodings from different angles for robust multi-angle matching
        # Each encoding remains separate so face_distance can pick the best angle match
        database.add_staff(
            data['id'], data['name'], data['role'],
            pickle.dumps(encodings),
            data.get('shift_time', '10:00'),
            data.get('shift', 'Morning'),
            data.get('rate', 500),
            data.get('salary_type', 'Monthly'),
            first_photo
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

@app.route('/api/zones', methods=['GET'])
@login_required
def get_zones():
    zones = database.get_zones_config()
    return jsonify([{"name": z[0], "points": z[1], "unauthorized": z[2].split(",") if z[2] else []} for z in zones])

@app.route('/api/zones/delete/<name>', methods=['DELETE'])
@login_required
def delete_zone(name):
    database.delete_zone_config(name)
    engine.reload_zones()
    return jsonify({"status": "success"})

@app.route('/api/settings/emails', methods=['GET', 'POST'])
@login_required
def email_settings():
    if request.method == 'POST':
        # This endpoint historically received BOTH email and camera settings payload
        # I'll let it keep the database.update_system_settings() logic because
        # we will extract camera specific settings into a dedicated endpoint.
        database.update_system_settings(request.json)
        sync_mailer_config()
        return jsonify({"status": "success"})
    return jsonify(database.get_system_settings())

@app.route('/api/settings/camera', methods=['POST'])
@login_required
def camera_settings():
    database.update_system_settings(request.json)
    sync_camera_config()
    sync_camera_preset()
    global camera_stream
    if camera_stream:
        print("[SYSTEM] Reconnecting camera to apply new settings...")
        camera_stream.online = False
    return jsonify({"status": "success"})

@app.route('/api/analytics/customers/history')
@login_required
def get_customer_history():
    return jsonify(database.get_customer_history())


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
        '/cam/realmonitor?channel=1&subtype=1',
        '/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif',
        '/cam/realmonitor?channel=1&subtype=0',
        '/cam/realmonitor?channel=1&subtype=0&unicast=true&proto=Onvif',
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

if __name__ == '__main__':
    raw_port = str(os.environ.get('STAFFLYTICS_PORT', '5000')).strip().split()[0]
    try:
        port = int(raw_port)
    except ValueError:
        port = 5000
    app.run(host='0.0.0.0', debug=False, port=port, threaded=True, use_reloader=False)
