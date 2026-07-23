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

class RTSPStreamWriter:
    def __init__(self, rtsp_url="rtsp://localhost:8554/mystream", width=640, height=480, fps=10):
        self.rtsp_url = rtsp_url
        self.width = width
        self.height = height
        self.fps = fps
        self.process = None
        self.lock = threading.Lock()
        self.running = False
        self.latest_frame = None
        self.thread = None
        
    def _start_ffmpeg(self):
        if not os.path.exists(FFMPEG_EXE):
            return False
            
        ffmpeg_cmd = [
            FFMPEG_EXE,
            '-y',
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{self.width}x{self.height}',
            '-r', str(self.fps),
            '-i', '-',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-g', str(self.fps),
            '-threads', '0',
            '-an',
            '-f', 'rtsp',
            '-rtsp_transport', 'tcp',
            self.rtsp_url
        ]
        
        try:
            self.log_file = open("ffmpeg_writer.log", "w")
            self.process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.log_file,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            self.running = True
            
            # Start background writer thread
            self.thread = threading.Thread(target=self._writer_loop, daemon=True)
            self.thread.start()
            
            print(f"[RTSP STREAM WRITER] FFmpeg stream writing to {self.rtsp_url} initialized with background thread. Log: ffmpeg_writer.log")
            return True
        except Exception as e:
            print(f"[RTSP STREAM WRITER ERROR] Failed to start FFmpeg: {e}")
            self.process = None
            self.running = False
            return False

    def _writer_loop(self):
        import numpy as np
        import time
        interval = 1.0 / self.fps
        black_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        
        while self.running:
            t_start = time.time()
            frame_to_write = None
            
            with self.lock:
                if self.latest_frame is not None:
                    frame_to_write = self.latest_frame.copy()
                else:
                    frame_to_write = black_frame.copy()
            
            if self.process is not None:
                try:
                    self.process.stdin.write(frame_to_write.tobytes())
                    self.process.stdin.flush()
                except Exception as e:
                    print(f"[RTSP STREAM WRITER ERROR] Write error in background loop: {e}. Stopping writer.")
                    self.running = False
                    break
            
            elapsed = time.time() - t_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def write_frame(self, frame):
        # Resize if frame shape does not match configuration
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height))
            
        with self.lock:
            self.latest_frame = frame.copy()
            
        if not self.running or self.process is None:
            return self._start_ffmpeg()
        return True

    def stop(self):
        self.running = False
        if self.thread is not None:
            try:
                self.thread.join(timeout=1)
            except:
                pass
            self.thread = None
            
        with self.lock:
            if self.process is not None:
                try:
                    self.process.stdin.close()
                except:
                    pass
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except:
                    pass
                try:
                    if hasattr(self, 'log_file') and self.log_file:
                        self.log_file.close()
                except:
                    pass
                self.process = None
                self.latest_frame = None
                print("[RTSP STREAM WRITER] FFmpeg stream writer stopped.")
