import os
import sys
import time
import zipfile
import requests
import subprocess
import threading
import cv2

BIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "bin"))
MEDIAMTX_EXE = os.path.join(BIN_DIR, "mediamtx.exe")
FFMPEG_EXE = os.path.join(BIN_DIR, "ffmpeg.exe")

current_physical_rtsp_url = None

# Resolution presets matching app.py QUALITY_PRESETS
RESOLUTION_PRESETS = {
    "480p": (640, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080)
}

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
    source: {current_physical_rtsp_url}
    rtspTransport: tcp

  mystream:
    runOnDemand: '\"{ffmpeg_path}\" -rtsp_transport tcp -i rtsp://localhost:8554/cam -vf \"scale={stream_w}:{stream_h}\" -c:v libx264 -preset ultrafast -tune zerolatency -r 15 -pix_fmt yuv420p -an -rtsp_transport tcp -f rtsp rtsp://localhost:8554/mystream'
    runOnDemandRestart: yes
"""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
        print(f"[STREAM MANAGER] Dynamically wrote mediamtx.yml with physical source: {current_physical_rtsp_url}")
    except Exception as e:
        print(f"[STREAM MANAGER ERROR] Failed to write custom mediamtx.yml: {e}")

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
            success = extract_file_from_zip(zip_path, "mediamtx.exe", MEDIAMTX_EXE)
            
            # Also extract the yml config if present
            extract_file_from_zip(zip_path, "mediamtx.yml", os.path.join(BIN_DIR, "mediamtx.yml"))
            
            # Apply dynamic config if available
            if current_physical_rtsp_url:
                write_mediamtx_config()
            
            # Cleanup zip
            try: os.remove(zip_path)
            except: pass
            
            if not success:
                raise Exception("mediamtx.exe not found in downloaded zip file")
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

# RTSPStreamWriter was removed as YOLO overlay was refactored to use WebSockets + HTML Canvas overlay.

