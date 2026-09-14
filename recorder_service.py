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
from datetime import datetime, timedelta

# Configuration
RECORDING_DIR = r"E:\Stafflytics Recording"
MAX_STORAGE_BYTES = 850 * 1024 * 1024 * 1024  # 850 GB
TARGET_AFTER_PURGE_BYTES = 840 * 1024 * 1024 * 1024  # 840 GB (headroom)
RTSP_SOURCE = "http://127.0.0.1:5001/api/recording_feed"

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
    r"""Ensures today's and tomorrow's date directory exist in E:\Stafflytics Recording."""
    from datetime import timedelta
    today = datetime.now()
    for offset in range(3): # Today, Tomorrow, Day after
        d_str = (today + timedelta(days=offset)).strftime("%Y-%m-%d")
        folder_path = os.path.join(RECORDING_DIR, d_str)
        os.makedirs(folder_path, exist_ok=True)


def run_recorder():
    """Runs FFmpeg segment recording with CPU re-encoding for bounding boxes."""
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
            now = datetime.now()
            
            # Calculate seconds remaining until the next hour
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            duration_seconds = int((next_hour - now).total_seconds())
            
            # Segment format: E:\Stafflytics Recording\%Y-%m-%d\HH-00.mp4
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H-00")
            
            output_pattern = os.path.join(RECORDING_DIR, date_str, f"{time_str}.mp4")
            # Avoid overwrite if it crashed and restarted within the same hour
            suffix = 1
            while os.path.exists(output_pattern):
                output_pattern = os.path.join(RECORDING_DIR, date_str, f"{time_str}_part{suffix}.mp4")
                suffix += 1

            # FFmpeg Command for MJPEG stream to H.264 MP4:
            cmd = [
                FFMPEG_PATH,
                "-loglevel", "warning",
                "-f", "mjpeg",
                "-use_wallclock_as_timestamps", "1",
                "-i", RTSP_SOURCE,
                "-t", str(duration_seconds),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-y",
                output_pattern
            ]

            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [RECORDER] Recording segment {time_str}.mp4 for {duration_seconds} seconds...")
            proc = subprocess.Popen(cmd)
            proc.wait()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [RECORDER] Segment finished (code {proc.returncode}). Starting next segment...")
            time.sleep(1)
        except Exception as e:
            print(f"[RECORDER ERROR] {e}. Retrying in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    run_recorder()
