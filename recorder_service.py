r"""
Stafflytics AI — 24/7 Continuous Video Recorder & Storage Manager
Records hourly .mp4 video files organized by date folders (E:\Stafflytics Recording\YYYY-MM-DD\HH-00.mp4).
Enforces strict 850 GB FIFO retention (deletes oldest files automatically when size exceeds 850 GB).
"""
import os
import sys
import time
import subprocess
import threading
from datetime import datetime

# Configuration
RECORDING_DIR = r"E:\Stafflytics Recording"
MAX_STORAGE_BYTES = 850 * 1024 * 1024 * 1024  # 850 GB
TARGET_AFTER_PURGE_BYTES = 840 * 1024 * 1024 * 1024  # 840 GB (headroom)
RTSP_SOURCE = "rtsp://localhost:8554/cam"

# Resolve FFmpeg binary
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = os.path.join(BASE_DIR, "bin", "ffmpeg.exe")
if not os.path.exists(FFMPEG_PATH):
    FFMPEG_PATH = "ffmpeg"


def get_total_recording_size(target_dir):
    """Calculates the total size in bytes of all files in the recording directory."""
    total_size = 0
    file_list = []
    if not os.path.exists(target_dir):
        return 0, []
    
    for root, dirs, files in os.walk(target_dir):
        for f in files:
            fp = os.path.join(root, f)
            try:
                stat = os.stat(fp)
                total_size += stat.st_size
                file_list.append((fp, stat.st_mtime, stat.st_size))
            except Exception:
                pass
    return total_size, file_list


def purge_oldest_recordings():
    """Checks disk usage and purges oldest hourly recordings if total size exceeds 850 GB."""
    try:
        total_size, file_list = get_total_recording_size(RECORDING_DIR)
        current_gb = total_size / (1024 ** 3)
        print(f"[STORAGE MANAGER] Current Archive Size: {current_gb:.2f} GB / 850.00 GB limit")

        if total_size >= MAX_STORAGE_BYTES:
            print(f"[STORAGE MANAGER WARNING] Reached 850 GB storage threshold ({current_gb:.2f} GB). Starting FIFO cleanup...")
            # Sort files by modification time (oldest first)
            file_list.sort(key=lambda x: x[1])

            bytes_deleted = 0
            for fp, mtime, fsize in file_list:
                if total_size - bytes_deleted <= TARGET_AFTER_PURGE_BYTES:
                    break
                try:
                    os.remove(fp)
                    bytes_deleted += fsize
                    print(f"[STORAGE PURGE] Deleted oldest archive: {fp} ({fsize / (1024**2):.1f} MB)")
                except Exception as del_err:
                    print(f"[STORAGE PURGE ERROR] Could not delete {fp}: {del_err}")

            # Clean up any empty date directories
            for root, dirs, files in os.walk(RECORDING_DIR, topdown=False):
                if root != RECORDING_DIR and not os.listdir(root):
                    try:
                        os.rmdir(root)
                        print(f"[STORAGE PURGE] Removed empty directory: {root}")
                    except Exception:
                        pass
                        
            new_total = (total_size - bytes_deleted) / (1024 ** 3)
            print(f"[STORAGE MANAGER] Purge complete. New Archive Size: {new_total:.2f} GB")
    except Exception as e:
        print(f"[STORAGE MANAGER ERROR] {e}")


def storage_supervisor_loop():
    """Background thread checking storage every 10 minutes."""
    while True:
        purge_oldest_recordings()
        time.sleep(600)  # Check every 10 minutes


def ensure_date_folders():
    """Ensures today's and tomorrow's date directory exist in E:\Stafflytics Recording."""
    from datetime import timedelta
    today = datetime.now()
    for offset in range(3): # Today, Tomorrow, Day after
        d_str = (today + timedelta(days=offset)).strftime("%Y-%m-%d")
        folder_path = os.path.join(RECORDING_DIR, d_str)
        os.makedirs(folder_path, exist_ok=True)


def run_recorder():
    """Runs FFmpeg segment recording with 0% CPU stream copy."""
    os.makedirs(RECORDING_DIR, exist_ok=True)
    print("=" * 65)
    print("  Stafflytics AI — 24/7 Continuous Video Recorder Service")
    print(f"  Target Archive: {RECORDING_DIR}")
    print(f"  Storage Limit: 850 GB (FIFO auto-purge enabled)")
    print("=" * 65)

    # Start background storage purge supervisor
    t = threading.Thread(target=storage_supervisor_loop, daemon=True, name="StorageSupervisor")
    t.start()

    while True:
        try:
            ensure_date_folders()
            # Segment format: E:\Stafflytics Recording\%Y-%m-%d\%H-00.mp4
            output_pattern = os.path.join(RECORDING_DIR, "%Y-%m-%d", "%H-00.mp4")

            # FFmpeg Command:
            # -c copy : direct stream copy (0% CPU, no quality loss)
            # -segment_time 3600 : hourly files (3600 seconds)
            # -segment_atclocktime 1 : aligned to exact clock hours (:00)
            # -strftime 1 : allows %Y-%m-%d\%H-00 in output path
            cmd = [
                FFMPEG_PATH,
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-i", RTSP_SOURCE,
                "-c", "copy",
                "-f", "segment",
                "-segment_time", "3600",
                "-segment_atclocktime", "1",
                "-reset_timestamps", "1",
                "-strftime", "1",
                output_pattern
            ]

            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [RECORDER] Starting hourly segment recording...")
            proc = subprocess.Popen(cmd)
            proc.wait()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [RECORDER] FFmpeg exited (code {proc.returncode}). Reconnecting in 3s...")
            time.sleep(3)
        except Exception as e:
            print(f"[RECORDER ERROR] {e}. Retrying in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    run_recorder()
