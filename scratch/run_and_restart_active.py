import sys
sys.path.append('.')
import database
import psutil
import subprocess
import time

print("Initializing MySQL database & migrations...")
database.init_db()
print("Database migrated successfully.")

print("Killing conflicting python/mediamtx/ffmpeg processes...")
# Kill other python instances running app.py
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmd = proc.info.get('cmdline') or []
        if any('app.py' in part for part in cmd) and proc.pid != sys.argv[0] and proc.pid != psutil.Process().pid:
            print(f"Terminating python process {proc.pid}...")
            proc.terminate()
            proc.wait(timeout=3)
    except Exception:
        pass

# Kill mediamtx and ffmpeg
for proc in psutil.process_iter(['name']):
    try:
        name = proc.info.get('name') or ''
        if any(x in name.lower() for x in ['mediamtx', 'ffmpeg']):
            print(f"Terminating streaming process {proc.name()} (PID {proc.pid})...")
            proc.terminate()
            proc.wait(timeout=3)
    except Exception:
        pass

print("All conflicting processes killed. Starting app.py server in active workspace...")
new_proc = subprocess.Popen(
    [sys.executable, "app.py"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)
print(f"Server launched with PID: {new_proc.pid}")
time.sleep(2)
print("Restart process complete.")
