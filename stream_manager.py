import os
import sys
import time
import zipfile
import platform
import requests
import subprocess
import threading
import cv2

BIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "bin"))
_IS_WINDOWS = platform.system() == "Windows"
MEDIAMTX_BINARY_NAME = "mediamtx.exe" if _IS_WINDOWS else "mediamtx"
MEDIAMTX_EXE = os.path.join(BIN_DIR, MEDIAMTX_BINARY_NAME)
FFMPEG_EXE = os.path.join(BIN_DIR, "ffmpeg.exe")

current_physical_rtsp_url = None

# Stream source mode:
#   "rtsp" -> original local-RTSP + MediaMTX/WebRTC flow (feature-flagged legacy path)
#   "imou" -> Imou Open Platform HLS -> local RTSP relay (browser plays HLS directly)
STREAM_MODE = "rtsp"

# Imou HLS -> RTSP bridge (one ffmpeg process publishing the Imou HEVC relay to
# MediaMTX path "cam"; MediaMTX's existing runOnInit transcodes cam -> cam_ai for AI).
_imou_bridge_process = None
_imou_bridge_lock = threading.Lock()
_imou_supervisor_thread = None
_imou_last_ai_frame_time = 0.0
IMOU_STALL_SECONDS = 15

# Resolution presets matching app.py QUALITY_PRESETS
RESOLUTION_PRESETS = {
    "480p": (640, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080)
}

def set_stream_mode(mode):
    global STREAM_MODE
    STREAM_MODE = mode

def get_hls_proxy_url():
    """Local Flask HLS proxy endpoint that the ffmpeg bridge pulls from.
    The proxy re-fetches the Imou playlist on every request and auto-regenerates
    the live URL when it goes stale, which prevents the ~10s freeze issue."""
    port = os.environ.get("STAFFLYTICS_PORT", "5000")
    return "http://127.0.0.1:%s/api/stream/playlist" % port

def get_stream_resolution():
    """Read the configured camera_preset from DB and return (width, height) for streaming."""
    try:
        import database
        settings = database.get_system_settings()
        preset = settings.get('camera_preset', '720p')
        if preset not in RESOLUTION_PRESETS:
            preset = '720p'
        print(f"[STREAM MANAGER] Using camera_preset '{preset}' for FFmpeg stream scale")
        return RESOLUTION_PRESETS[preset]
    except Exception as e:
        print(f"[STREAM MANAGER] Error reading camera_preset, defaulting to 720p: {e}")
        return 1280, 720

def write_mediamtx_config():
    global current_physical_rtsp_url
    if STREAM_MODE == "imou":
        _write_mediamtx_config_imou()
        return
    if not current_physical_rtsp_url:
        return
    
    config_path = os.path.join(BIN_DIR, "mediamtx.yml")
    ffmpeg_path = os.path.join(BIN_DIR, "ffmpeg.exe")
    stream_w, stream_h = get_stream_resolution()
    
    config_content = f"""# MediaMTX configuration for Stafflytics (auto-generated)
rtspAddress: :8554
rtpAddress: :8556
rtcpAddress: :8557

webrtc: yes
webrtcAddress: :8889
webrtcAllowOrigin: '*'
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: :8189
webrtcHandshakeTimeout: 30s

readTimeout: 30s

rtmp: no
hls: no
srt: no

paths:
  cam:
    # Full-quality relay from physical camera — used for the display video feed.
    # TCP transport prevents UDP packet loss that causes HEVC decode errors.
    source: {current_physical_rtsp_url}
    rtspTransport: tcp

  cam_ai:
    # H.264 transcoded stream for OpenCV / YOLO AI processing.
    # FFmpeg pulls from the local cam relay (already over TCP), re-encodes to H.264
    # at 640x480 for lightweight, error-free AI reads. ultrafast+zerolatency keeps
    # latency under 200ms while eliminating all HEVC decode failures that caused
    # frame drops and bounding box disappearances.
    runOnInit: '"{ffmpeg_path}" -loglevel quiet -rtsp_transport tcp -i rtsp://localhost:8554/cam -vf "scale=640:480" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://localhost:8554/cam_ai'
    runOnInitRestart: yes

  mystream:
    runOnDemand: '"{ffmpeg_path}" -rtsp_transport tcp -i rtsp://localhost:8554/cam -vf \"scale={stream_w}:{stream_h}\" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://localhost:8554/mystream'
    runOnDemandRestart: yes
"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        print(f"[STREAM MANAGER] Dynamically wrote mediamtx.yml with physical source: {current_physical_rtsp_url}")
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to write custom mediamtx.yml: {e}")

def _write_mediamtx_config_imou():
    """Imou HLS mode config.

    MediaMTX is kept as the local RTSP hub so YOLO/vision and the MJPEG display
    fallback keep working unchanged. Differences from legacy mode:
      * cam path accepts a publisher (ffmpeg HLS bridge) instead of a static
        physical RTSP source.
      * webrtc is disabled (the browser now plays the Imou HLS directly, so the
        MediaMTX/WebRTC conversion step is no longer needed for this flow).
      * the on-demand "mystream" (WHEP) path is removed.
      * cam_ai H.264 transcode (used by AI) is preserved as-is.
    """
    config_path = os.path.join(BIN_DIR, "mediamtx.yml")
    ffmpeg_path = os.path.join(BIN_DIR, "ffmpeg.exe")

    config_content = f"""# MediaMTX configuration for Stafflytics - IMOU HLS MODE (auto-generated)
# Local RTSP relay for the AI pipeline. Browser plays Imou HLS directly.
rtspAddress: :8554
rtpAddress: :8556
rtcpAddress: :8557

webrtc: no

readTimeout: 30s

rtmp: no
hls: no
srt: no

paths:
  cam:
    # Imou HLS -> RTSP relay. ffmpeg (imou bridge) publishes the Imou HEVC stream
    # here; this path accepts external publishers only.
    source: publisher

  cam_ai:
    # H.264 transcoded stream for OpenCV / YOLO AI processing (unchanged).
    runOnInit: '"{ffmpeg_path}" -loglevel quiet -rtsp_transport tcp -i rtsp://localhost:8554/cam -vf "scale=640:480" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://localhost:8554/cam_ai'
    runOnInitRestart: yes
"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        print("[STREAM MANAGER] Wrote Imou-mode mediamtx.yml (HLS->RTSP relay, WebRTC disabled).")
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to write Imou mediamtx.yml: {e}")

def setup_imou_stream():
    """Switch the whole streaming pipeline to Imou HLS mode."""
    global STREAM_MODE
    print("[STREAM MANAGER] Switching to IMOU HLS stream mode (WebRTC/RTSP source deactivated).")
    STREAM_MODE = "imou"
    write_mediamtx_config()
    stop_mediamtx()
    start_mediamtx()
    _ensure_imou_supervisor()
    return True

def setup_mediamtx(physical_rtsp_url):
    global current_physical_rtsp_url
    current_physical_rtsp_url = physical_rtsp_url
    write_mediamtx_config()
    stop_mediamtx()
    start_mediamtx()


MEDIAMTX_URL = "https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_windows_amd64.zip"
# GyanD essentials zip containing ffmpeg.exe
FFMPEG_URL = "https://github.com/GyanD/codexffmpeg/releases/download/7.0.1/ffmpeg-7.0.1-essentials_build.zip"

mediamtx_process = None
downloader_thread = None
download_status = "Not started"
download_error = None
download_complete = False

def extract_file_from_zip(zip_path, file_suffix, dest_path):
    print(f"[STREAM MANAGER] Searching zip {zip_path} for files ending with {file_suffix}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            if file_info.filename.endswith(file_suffix):
                print(f"[STREAM MANAGER] Extracting {file_info.filename} to {dest_path}...")
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                data = zip_ref.read(file_info.filename)
                with open(dest_path, 'wb') as f:
                    f.write(data)
                return True
    return False

def _downloader_worker():
    global download_status, download_complete, download_error
    os.makedirs(BIN_DIR, exist_ok=True)
    
    # 1. Download MediaMTX if missing
    if not os.path.exists(MEDIAMTX_EXE):
        try:
            download_status = "Downloading MediaMTX..."
            print(f"[STREAM MANAGER] {download_status}")
            zip_path = os.path.join(BIN_DIR, "mediamtx.zip")
            
            # Download with progress log
            r = requests.get(MEDIAMTX_URL, stream=True)
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            download_status = "Extracting MediaMTX..."
            print(f"[STREAM MANAGER] {download_status}")
            success = extract_file_from_zip(zip_path, MEDIAMTX_BINARY_NAME, MEDIAMTX_EXE)
            
            # Also extract the yml config if present
            extract_file_from_zip(zip_path, "mediamtx.yml", os.path.join(BIN_DIR, "mediamtx.yml"))
            
            # Apply dynamic config if available
            if current_physical_rtsp_url:
                write_mediamtx_config()
            
            # Cleanup zip
            try: os.remove(zip_path)
            except: pass
            
            if not success:
                raise Exception(f"{MEDIAMTX_BINARY_NAME} not found in downloaded zip file")
            print("[STREAM MANAGER] MediaMTX extracted successfully.")
        except Exception as e:
            download_error = f"MediaMTX download failed: {str(e)}"
            download_status = "Error"
            print(f"[STREAM MANAGER] {download_error}")
            return

    # 2. Download FFmpeg if missing
    if not os.path.exists(FFMPEG_EXE):
        try:
            download_status = "Downloading FFmpeg (~60MB)..."
            print(f"[STREAM MANAGER] {download_status}")
            zip_path = os.path.join(BIN_DIR, "ffmpeg.zip")
            
            r = requests.get(FFMPEG_URL, stream=True)
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            download_status = "Extracting FFmpeg..."
            print(f"[STREAM MANAGER] {download_status}")
            success = extract_file_from_zip(zip_path, "ffmpeg.exe", FFMPEG_EXE)
            
            # Cleanup zip
            try: os.remove(zip_path)
            except: pass
            
            if not success:
                raise Exception("ffmpeg.exe not found in downloaded zip file")
            print("[STREAM MANAGER] FFmpeg extracted successfully.")
        except Exception as e:
            download_error = f"FFmpeg download failed: {str(e)}"
            download_status = "Error"
            print(f"[STREAM MANAGER] {download_error}")
            return
            
    download_status = "Complete"
    download_complete = True
    print("[STREAM MANAGER] All binaries are ready.")
    
    # Auto-start MediaMTX since binaries are ready
    start_mediamtx()

def ensure_binaries_async():
    global downloader_thread
    if os.path.exists(MEDIAMTX_EXE) and os.path.exists(FFMPEG_EXE):
        global download_status, download_complete
        download_status = "Complete"
        download_complete = True
        print("[STREAM MANAGER] Binaries already exist in bin/ folder.")
        if current_physical_rtsp_url:
            write_mediamtx_config()
        start_mediamtx()
        return
        
    if downloader_thread is None or not downloader_thread.is_alive():
        downloader_thread = threading.Thread(target=_downloader_worker, daemon=True)
        downloader_thread.start()
        print("[STREAM MANAGER] Download worker started in background.")

def start_mediamtx():
    global mediamtx_process
    if mediamtx_process is not None:
        if mediamtx_process.poll() is None:
            return  # Already running
            
    if not os.path.exists(MEDIAMTX_EXE):
        print("[STREAM MANAGER] Cannot start MediaMTX: Binary not found yet.")
        return
        
    try:
        print("[STREAM MANAGER] Launching MediaMTX...")
        # Run it with its folder as CWD so it finds or writes mediamtx.yml in the bin folder
        mediamtx_process = subprocess.Popen(
            [MEDIAMTX_EXE],
            cwd=BIN_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        print("[STREAM MANAGER] MediaMTX started successfully.")
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to start MediaMTX: {e}")

def stop_mediamtx():
    global mediamtx_process
    if mediamtx_process is not None:
        print("[STREAM MANAGER] Stopping MediaMTX...")
        try:
            mediamtx_process.terminate()
            mediamtx_process.wait(timeout=3)
        except Exception as e:
            print(f"[STREAM MANAGER] Error stopping MediaMTX: {e}")
        mediamtx_process = None

# ---------------------------------------------------------------------------
# Imou HLS -> RTSP bridge
#
# One ffmpeg process pulls the Imou HEVC live stream (via the local Flask HLS
# proxy, which re-fetches + auto-regenerates the Imou playlist/live URL) and
# republishes it to MediaMTX path "cam". The existing MediaMTX runOnInit
# transcodes cam -> cam_ai (H.264 640x480) for OpenCV/YOLO, so AI frame
# consumption is unchanged. A supervisor thread restarts the bridge whenever it
# dies or stalls (the Imou freeze-after-~10s issue).
# ---------------------------------------------------------------------------

def start_imou_bridge():
    """Launch the ffmpeg process that relays Imou HLS -> MediaMTX cam path."""
    global _imou_bridge_process
    with _imou_bridge_lock:
        if _imou_bridge_process is not None and _imou_bridge_process.poll() is None:
            return True
        if not os.path.exists(FFMPEG_EXE):
            print("[STREAM MANAGER] Cannot start Imou bridge: ffmpeg binary not found.")
            return False
        proxy_url = get_hls_proxy_url()
        cmd = [
            FFMPEG_EXE, "-loglevel", "info",
            "-fflags", "+discardcorrupt",
            "-i", proxy_url,
            "-c", "copy",
            "-an",
            "-rtsp_transport", "tcp",
            "-f", "rtsp",
            "rtsp://localhost:8554/cam",
        ]
        print("[STREAM MANAGER] Launching Imou HLS bridge -> rtsp://localhost:8554/cam")
        try:
            _imou_bridge_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            return True
        except Exception as e:
            print(f"[STREAM MANAGER ERROR] Failed to start Imou bridge: {e}")
            _imou_bridge_process = None
            return False

def stop_imou_bridge():
    global _imou_bridge_process
    with _imou_bridge_lock:
        if _imou_bridge_process is not None:
            print("[STREAM MANAGER] Stopping Imou HLS bridge...")
            try:
                _imou_bridge_process.terminate()
                _imou_bridge_process.wait(timeout=3)
            except Exception as e:
                print(f"[STREAM MANAGER] Error stopping Imou bridge: {e}")
            _imou_bridge_process = None

def is_imou_bridge_alive():
    with _imou_bridge_lock:
        return _imou_bridge_process is not None and _imou_bridge_process.poll() is None

def mark_imou_frame_received():
    """Called by the camera reader whenever a frame arrives in Imou mode."""
    global _imou_last_ai_frame_time
    _imou_last_ai_frame_time = time.time()

def _restart_imou_bridge():
    global _imou_last_ai_frame_time
    print("[STREAM MANAGER] Imou bridge stalled/died — restarting (fresh live URL will be fetched by the proxy).")
    stop_imou_bridge()
    time.sleep(2)
    start_imou_bridge()
    _imou_last_ai_frame_time = 0.0

def _imou_supervisor_loop():
    """Watchdog: keeps MediaMTX + bridge up and restarts the bridge when the
    stream stalls (no frames for IMOU_STALL_SECONDS) or the process dies."""
    global _imou_last_ai_frame_time
    while True:
        time.sleep(5)
        try:
            if STREAM_MODE != "imou":
                continue
            if not os.path.exists(MEDIAMTX_EXE) or not os.path.exists(FFMPEG_EXE):
                continue
            # Keep MediaMTX running with the Imou config.
            if mediamtx_process is None or mediamtx_process.poll() is not None:
                write_mediamtx_config()
                start_mediamtx()
            if mediamtx_process is None or mediamtx_process.poll() is not None:
                continue
            # Keep the HLS bridge running.
            if not is_imou_bridge_alive():
                print("[STREAM MANAGER] Imou bridge process is not running — restarting.")
                start_imou_bridge()
                continue
            # Stall detection: frames stopped flowing while bridge is up.
            since = time.time() - _imou_last_ai_frame_time
            if _imou_last_ai_frame_time > 0 and since > IMOU_STALL_SECONDS:
                print(f"[STREAM MANAGER] No frames for {since:.0f}s — stream frozen, restarting bridge.")
                _restart_imou_bridge()
        except Exception as e:
            print(f"[STREAM MANAGER SUPERVISOR ERROR] {e}")

def _ensure_imou_supervisor():
    global _imou_supervisor_thread
    if _imou_supervisor_thread is None or not _imou_supervisor_thread.is_alive():
        _imou_supervisor_thread = threading.Thread(target=_imou_supervisor_loop, daemon=True, name="ImouBridgeSupervisor")
        _imou_supervisor_thread.start()
        print("[STREAM MANAGER] Imou bridge supervisor started.")

# RTSPStreamWriter was removed as YOLO overlay was refactored to use WebSockets + HTML Canvas overlay.

