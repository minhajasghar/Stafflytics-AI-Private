import socket
import psutil
import urllib.request
import json

def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0

print(f"Checking Port 5000 (Flask): {check_port(5000)}")
print(f"Checking Port 8554 (MediaMTX RTSP): {check_port(8554)}")
print(f"Checking Port 8889 (MediaMTX WebRTC): {check_port(8889)}")

print("\nListing python processes:")
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmd = proc.info.get('cmdline') or []
        if 'python' in proc.info['name'].lower() or any('app.py' in part for part in cmd):
            print(f"PID: {proc.pid}, Name: {proc.name()}, Cmdline: {cmd}")
    except Exception:
        pass

print("\nListing mediamtx/ffmpeg processes:")
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        name = proc.info.get('name') or ''
        if any(x in name.lower() for x in ['mediamtx', 'ffmpeg']):
            print(f"PID: {proc.pid}, Name: {proc.name()}, Cmdline: {proc.info.get('cmdline')}")
    except Exception:
        pass
