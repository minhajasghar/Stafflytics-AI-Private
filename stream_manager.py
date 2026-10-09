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
# On Windows use the bundled binary; on Linux/Mac rely on the system-installed ffmpeg.
FFMPEG_EXE = os.path.join(BIN_DIR, "ffmpeg.exe") if _IS_WINDOWS else "ffmpeg"

current_physical_rtsp_url = None

# ---------------------------------------------------------------------------
# Camera source mode — controlled by the CAMERA_SOURCE_MODE environment var.
#
#   "remote_rtsp"  (default) — MediaMTX pulls directly from REMOTE_RTSP_URL
#                              (e.g. a Tailscale peer running MediaMTX).
#   "rtsp"         — legacy local-RTSP + MediaMTX/WebRTC flow.
#
#   "imou"         — DISABLED. This software does not use the Imou Open
#                    Platform API, so any "imou" value is treated as
#                    "remote_rtsp".
# ---------------------------------------------------------------------------
CAMERA_SOURCE_MODE = os.environ.get("CAMERA_SOURCE_MODE", "remote_rtsp").strip().lower()
if CAMERA_SOURCE_MODE == "imou":
    print("[STREAM MANAGER] 'imou' mode is disabled — forcing remote_rtsp.")
    CAMERA_SOURCE_MODE = "remote_rtsp"
REMOTE_RTSP_URL    = os.environ.get("CAMERA_RTSP_URL", os.environ.get("REMOTE_RTSP_URL", "rtsp://100.93.176.107:8554/cam")).strip()

# Internal runtime mode (may be overridden by setup_* helpers at runtime).
STREAM_MODE = CAMERA_SOURCE_MODE

# Imou HLS -> H.264 RTSP bridge (one ffmpeg process transcoding the raw Imou
# HLS live URL and publishing H.264 640x480 to MediaMTX path "cam_ai").
# OpenCV/YOLO reads cam_ai directly (no physical RTSP, no HLS->RTSP copy chain).
_imou_bridge_process = None
_imou_bridge_lock = threading.Lock()
_imou_supervisor_thread = None
_imou_last_ai_frame_time = 0.0
_imou_bridge_start_time = 0.0
_imou_bridge_log_file = None
IMOU_STALL_SECONDS = 30

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
    """Local Flask HLS proxy endpoint that the browser hls.js player pulls from.
    The proxy re-fetches the Imou playlist on every request and auto-regenerates
    the live URL when it goes stale, which prevents the ~10s freeze issue.
    NOTE: the backend ffmpeg bridge must NOT use this proxy — the rewritten
    segment URLs (``/api/stream/segment?u=...``) are rejected by FFmpeg's HLS
    demuxer (allowed_segment_extensions check). The bridge reads the raw Imou
    HLS URL directly instead (see get_imou_live_url)."""
    port = os.environ.get("STAFFLYTICS_PORT", "5050")
    return "http://127.0.0.1:%s/api/stream/playlist" % port

def get_imou_live_url():
    """Raw Imou Open Platform HLS live URL for the backend bridge.

    Used instead of the proxied playlist because FFmpeg's HLS demuxer only
    accepts segment URIs ending in a media extension (.ts/.m4s...); the proxy
    rewrites segments to /api/stream/segment?u=... which FFmpeg rejects.
    """
    try:
        import imou_client
        client = imou_client.ImouClient()
        url = client.get_live_url()
        print(f"[STREAM MANAGER] Raw Imou live URL acquired: {url[:80]}...")
        return url
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to get raw Imou live URL: {e}")
        return None

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
    if STREAM_MODE == "remote_rtsp":
        _write_mediamtx_config_remote_rtsp()
        return
    if not current_physical_rtsp_url:
        return
    
    config_path = os.path.join(BIN_DIR, "mediamtx.yml")
    ffmpeg_path = FFMPEG_EXE
    stream_w, stream_h = get_stream_resolution()
    
    config_content = f"""# MediaMTX configuration for Stafflytics (auto-generated)
rtspAddress: :8554
rtpAddress: :8556
rtcpAddress: :8557

webrtc: yes
webrtcAddress: :8889
webrtcAllowOrigin: "*"
webrtcICEServers2:
  - url: stun:stun.l.google.com:19302
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
    runOnInit: '"{ffmpeg_path}" -loglevel quiet -rtsp_transport tcp -i rtsp://localhost:8554/cam -vf "scale=640:-2" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://localhost:8554/cam_ai'
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

    MediaMTX is kept only as a tiny local RTSP target for the AI pipeline.
    The ffmpeg Imou bridge transcodes the raw Imou HLS straight to H.264 and
    publishes it on the single "cam_ai" path, which OpenCV/YOLO reads.
    Differences from legacy mode:
      * webrtc is disabled (the browser plays the Imou HLS directly).
      * the on-demand "mystream" (WHEP) path is removed.
      * no "cam" relay / no runOnInit transcode — the bridge does the H.264
        transcode itself, so there is exactly one moving part.
    """
    config_path = os.path.join(BIN_DIR, "mediamtx.yml")

    config_content = f"""# MediaMTX configuration for Stafflytics - IMOU HLS MODE (auto-generated)
# Local RTSP target for the AI pipeline. Browser plays Imou HLS directly.
rtspAddress: :8554
rtpAddress: :8556
rtcpAddress: :8557

webrtc: no

readTimeout: 30s

rtmp: no
hls: no
srt: no

paths:
  cam_ai:
    # H.264 transcoded AI stream. The ffmpeg Imou bridge (start_imou_bridge)
    # publishes the raw Imou HLS transcoded to H.264 640x480 here; OpenCV/YOLO
    # reads it. This path accepts external publishers only.
    source: publisher
"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        print("[STREAM MANAGER] Wrote Imou-mode mediamtx.yml (single cam_ai publisher path).")
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to write Imou mediamtx.yml: {e}")

def _write_mediamtx_config_remote_rtsp():
    """Remote RTSP mode config.

    MediaMTX's "cam" path pulls directly from REMOTE_RTSP_URL (e.g. a Tailscale
    peer running MediaMTX).  cam_ai transcoding for AI is preserved unchanged.
    The Imou HLS bridge is NOT used in this mode.
    """
    remote_url = REMOTE_RTSP_URL
    if not remote_url:
        print("[STREAM MANAGER ERROR] remote_rtsp mode selected but REMOTE_RTSP_URL is not set.")
        return
    config_path = os.path.join(BIN_DIR, "mediamtx.yml")
    ffmpeg_path = FFMPEG_EXE
    ff_bin = f'"{ffmpeg_path}"' if _IS_WINDOWS else (ffmpeg_path or "ffmpeg")

    stream_w, stream_h = get_stream_resolution()
    config_content = f"""# MediaMTX configuration for Stafflytics - REMOTE RTSP MODE (auto-generated)
# "cam" pulls directly from the remote RTSP source; no Imou bridge needed.
rtspAddress: :8554
rtpAddress: :8556
rtcpAddress: :8557

webrtc: yes
webrtcAddress: :8889
webrtcAllowOrigin: "*"
webrtcICEServers2:
  - url: stun:stun.l.google.com:19302
  - url: stun:stun1.l.google.com:19302
  - url: stun:stun2.l.google.com:19302
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: :8189
webrtcHandshakeTimeout: 30s

readTimeout: 60s
writeTimeout: 60s

rtmp: no
hls: no
srt: no

paths:
  cam:
    # Pull directly from the remote RTSP peer (e.g. Tailscale MediaMTX node).
    source: {remote_url}
    rtspTransport: tcp
    sourceOnDemand: no
    overridePublisher: yes

  cam_ai:
    # H.264 transcoded stream for OpenCV / YOLO AI processing.
    # scale=640:-2 preserves source aspect ratio (no forced 4:3 stretch).
    runOnInit: '{ff_bin} -loglevel warning -rtsp_transport tcp -i rtsp://127.0.0.1:8554/cam -vf "scale=640:-2" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/cam_ai'
    runOnInitRestart: yes

  mystream:
    runOnDemand: '{ff_bin} -rtsp_transport tcp -i rtsp://127.0.0.1:8554/cam -vf "scale={stream_w}:{stream_h}" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/mystream'
    runOnDemandRestart: yes
"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        print(f"[STREAM MANAGER] Wrote remote-rtsp mediamtx.yml (source: {remote_url}).")
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to write remote-rtsp mediamtx.yml: {e}")

def setup_remote_rtsp_stream(remote_url=None):
    """Switch the whole streaming pipeline to Remote RTSP mode.

    Optionally accepts a runtime override for the URL; otherwise uses the
    REMOTE_RTSP_URL environment variable set at startup, falling back to the
    RTSP URL saved in the database (Settings -> RTSP Camera URL).
    The Imou HLS bridge is stopped and not restarted.
    """
    global STREAM_MODE, REMOTE_RTSP_URL
    if remote_url:
        REMOTE_RTSP_URL = remote_url
    if not REMOTE_RTSP_URL:
        try:
            import database
            saved = database.get_system_settings().get('rtsp_url', '').strip()
            if saved:
                REMOTE_RTSP_URL = saved
                print(f"[STREAM MANAGER] REMOTE_RTSP_URL not set — using saved camera URL: {saved}")
        except Exception as e:
            print(f"[STREAM MANAGER ERROR] Could not read saved RTSP URL: {e}")
    print(f"[STREAM MANAGER] Switching to REMOTE RTSP mode (source: {REMOTE_RTSP_URL}).")
    STREAM_MODE = "remote_rtsp"
    stop_imou_bridge()   # no-op if not running
    write_mediamtx_config()
    stop_mediamtx()
    start_mediamtx()
    return True

def setup_imou_stream():
    """Imou HLS mode is DISABLED — this software does not use the Imou API.
    Calling this function is a no-op that never activates Imou mode."""
    global STREAM_MODE
    print("[STREAM MANAGER] IMOU HLS MODE is DISABLED — ignoring setup_imou_stream().")
    STREAM_MODE = "remote_rtsp"
    return False

def setup_mediamtx(physical_rtsp_url):
    global current_physical_rtsp_url
    current_physical_rtsp_url = physical_rtsp_url
    write_mediamtx_config()
    stop_mediamtx()
    start_mediamtx()


# MediaMTX download URL — platform-aware so Linux VPS gets the correct binary.
_MEDIAMTX_VERSION = "1.19.2"
_MEDIAMTX_TAG    = "v1.19.2"
if _IS_WINDOWS:
    MEDIAMTX_URL = f"https://github.com/bluenviron/mediamtx/releases/download/{_MEDIAMTX_TAG}/mediamtx_{_MEDIAMTX_TAG}_windows_amd64.zip"
    _MEDIAMTX_ARCHIVE_EXT = ".zip"
else:
    import struct as _struct
    _arch = "arm64" if _struct.calcsize("P") == 8 and platform.machine().lower() in ("aarch64", "arm64") else "amd64"
    MEDIAMTX_URL = f"https://github.com/bluenviron/mediamtx/releases/download/{_MEDIAMTX_TAG}/mediamtx_{_MEDIAMTX_TAG}_linux_{_arch}.tar.gz"
    _MEDIAMTX_ARCHIVE_EXT = ".tar.gz"
# GyanD essentials zip containing ffmpeg.exe (Windows only)
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

def _extract_mediamtx(archive_path, dest_path):
    """Extract the mediamtx binary from either a .zip or .tar.gz archive."""
    if archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
        import tarfile
        print(f"[STREAM MANAGER] Extracting tar.gz {archive_path}...")
        with tarfile.open(archive_path, 'r:gz') as tar:
            for member in tar.getmembers():
                if member.name.endswith(MEDIAMTX_BINARY_NAME) or member.name == MEDIAMTX_BINARY_NAME:
                    member.name = os.path.basename(member.name)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with tar.extractfile(member) as src, open(dest_path, 'wb') as dst:
                        dst.write(src.read())
                    # Make executable on Linux
                    if not _IS_WINDOWS:
                        os.chmod(dest_path, 0o755)
                    return True
        return False
    else:
        return extract_file_from_zip(archive_path, MEDIAMTX_BINARY_NAME, dest_path)

def _downloader_worker():
    global download_status, download_complete, download_error
    os.makedirs(BIN_DIR, exist_ok=True)
    
    # 1. Download MediaMTX if missing
    if not os.path.exists(MEDIAMTX_EXE):
        try:
            download_status = "Downloading MediaMTX..."
            print(f"[STREAM MANAGER] {download_status} ({MEDIAMTX_URL})")
            archive_path = os.path.join(BIN_DIR, "mediamtx" + _MEDIAMTX_ARCHIVE_EXT)
            
            # Download with progress log
            r = requests.get(MEDIAMTX_URL, stream=True)
            r.raise_for_status()
            with open(archive_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            download_status = "Extracting MediaMTX..."
            print(f"[STREAM MANAGER] {download_status}")
            success = _extract_mediamtx(archive_path, MEDIAMTX_EXE)
            
            # Also extract the yml config if present (zip only)
            if archive_path.endswith('.zip'):
                extract_file_from_zip(archive_path, "mediamtx.yml", os.path.join(BIN_DIR, "mediamtx.yml"))
            
            # Apply dynamic config
            write_mediamtx_config()
            
            # Cleanup archive
            try: os.remove(archive_path)
            except: pass
            
            if not success:
                raise Exception(f"{MEDIAMTX_BINARY_NAME} not found in downloaded archive")
            print("[STREAM MANAGER] MediaMTX extracted successfully.")
        except Exception as e:
            download_error = f"MediaMTX download failed: {str(e)}"
            download_status = "Error"
            print(f"[STREAM MANAGER] {download_error}")
            return

    # 2. Download FFmpeg if missing (Windows only — Linux uses system ffmpeg from PATH)
    if _IS_WINDOWS and not os.path.exists(FFMPEG_EXE):
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

def _ffmpeg_available():
    """Return True when the ffmpeg command/binary is usable."""
    if _IS_WINDOWS:
        return os.path.exists(FFMPEG_EXE)
    # On Linux/Mac we rely on system ffmpeg — check it is on PATH.
    import shutil
    return shutil.which("ffmpeg") is not None

def ensure_binaries_async():
    global downloader_thread
    # In remote_rtsp mode ffmpeg is only needed for cam_ai transcoding (same as
    # imou mode), so we still require it.  The check is otherwise identical.
    if os.path.exists(MEDIAMTX_EXE) and _ffmpeg_available():
        global download_status, download_complete
        download_status = "Complete"
        download_complete = True
        print("[STREAM MANAGER] Binaries already exist / are available.")
        # Write the correct config for whichever mode was active at startup.
        write_mediamtx_config()
        start_mediamtx()
        # Start the Imou bridge supervisor only when in imou mode.
        if STREAM_MODE == "imou":
            _ensure_imou_supervisor()
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
# Imou HLS -> H.264 bridge
#
# One ffmpeg process pulls the raw Imou HLS live stream (fetched from the Imou
# Open Platform API — NOT the proxied playlist, whose rewritten segment URLs
# FFmpeg's HLS demuxer rejects) and transcodes it to H.264 640x480, publishing
# it to MediaMTX path "cam_ai" where OpenCV/YOLO reads it. A supervisor thread
# restarts the bridge whenever it dies or stalls (the Imou freeze-after-~10s
# issue), which also forces a fresh Imou live URL to be fetched.
# ---------------------------------------------------------------------------

def start_imou_bridge():
    """Launch the ffmpeg process that pulls the raw Imou HLS and transcodes it
    straight to H.264 640x480 on MediaMTX path "cam_ai" (the AI stream YOLO and
    the MJPEG fallback consume). Single transcode = fewer failure points than
    the old copy-to-cam + runOnInit re-transcode chain.

    Stderr is written to bin/imou_bridge.log so ffmpeg exit reasons can be
    diagnosed instead of being swallowed."""
    global _imou_bridge_process
    with _imou_bridge_lock:
        if _imou_bridge_process is not None and _imou_bridge_process.poll() is None:
            return True
        if not _ffmpeg_available():
            print("[STREAM MANAGER] Cannot start Imou bridge: ffmpeg not found (install via apt install ffmpeg on Linux).")
            return False
        live_url = get_imou_live_url()
        if not live_url:
            return False
        # HTTP reconnect flags: the Imou CDN (singapore) is flaky — reconnect
        # mid-stream instead of exiting, and cap per-socket timeouts so a dead
        # connection fails fast and the supervisor can restart with a fresh URL.
        cmd = [
            FFMPEG_EXE, "-loglevel", "warning",
            "-fflags", "+discardcorrupt",
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-rw_timeout", "8000000",
            "-i", live_url,
            # 16:9 output to match the source aspect (no vertical stretch), so
            # detection coordinates line up with the browser's HLS video.
            "-vf", "scale=640:360",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-r", "15",
            "-pix_fmt", "yuv420p",
            "-an",
            "-rtsp_transport", "tcp",
            "-f", "rtsp",
            "rtsp://localhost:8554/cam_ai",
        ]
        print("[STREAM MANAGER] Launching Imou HLS bridge (raw HLS -> H.264 cam_ai) -> rtsp://localhost:8554/cam_ai")
        try:
            bridge_log = os.path.join(BIN_DIR, "imou_bridge.log")
            global _imou_bridge_log_file
            if _imou_bridge_log_file is not None:
                try:
                    _imou_bridge_log_file.close()
                except Exception:
                    pass
            _imou_bridge_log_file = open(bridge_log, "a")
            _imou_bridge_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=_imou_bridge_log_file,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            global _imou_bridge_start_time
            _imou_bridge_start_time = time.time()
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
    stream stalls (no frames for IMOU_STALL_SECONDS) or the process dies.

    Stall is measured from the later of the last received frame or the last
    bridge start, so a bridge that never delivers a single frame (frozen CDN
    HLS) is still restarted instead of hanging forever."""
    global _imou_last_ai_frame_time
    while True:
        time.sleep(5)
        try:
            if STREAM_MODE != "imou":
                continue
            if not os.path.exists(MEDIAMTX_EXE) or not _ffmpeg_available():
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
            # Baseline = last frame received, or bridge start time if none yet.
            baseline = max(_imou_last_ai_frame_time, _imou_bridge_start_time)
            since = time.time() - baseline
            if baseline > 0 and since > IMOU_STALL_SECONDS:
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

