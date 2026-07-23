import cv2
import time
import os
import sys

# Define URLs
CAMERA_URL = "rtsp://admin:L2DD2594@192.168.50.137:554/cam/realmonitor?channel=1&subtype=0"
MEDIAMTX_URL = "rtsp://127.0.0.1:8554/live"

# Set FFMPEG options as app.py does
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000|reorder_queue_size;0"

def test_stream(url, name):
    print(f"\n--- Testing {name}: {url} ---")
    
    # Try FFMPEG first, then default
    backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]
    for be in backends:
        print(f"Opening with backend: {be}...")
        try:
            start_time = time.time()
            cap = cv2.VideoCapture(url, be)
            if cap:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            
            if cap and cap.isOpened():
                print(f"Success: Connected to {name} in {time.time() - start_time:.2f}s")
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"Success: Read frame from {name}! Shape: {frame.shape}")
                    cap.release()
                    return True
                else:
                    print(f"Error: Connected, but read() returned ret={ret}, frame={'None' if frame is None else 'Not None'}")
                cap.release()
            else:
                print(f"Error: Failed to open {name} stream (took {time.time() - start_time:.2f}s)")
        except Exception as e:
            print(f"Exception during test of {name} with backend {be}: {e}")
    return False

print("Starting RTSP Connection Diagnostics...")
direct_ok = test_stream(CAMERA_URL, "Direct Camera RTSP")
mediamtx_ok = test_stream(MEDIAMTX_URL, "Local MediaMTX RTSP")

print("\n--- Diagnostic Summary ---")
print(f"Direct Camera RTSP Connection: {'ONLINE' if direct_ok else 'OFFLINE'}")
print(f"Local MediaMTX RTSP Connection: {'ONLINE' if mediamtx_ok else 'OFFLINE'}")

if not direct_ok:
    print("\nTroubleshooting Direct Camera Connection:")
    print("1. Is the camera powered on?")
    print("2. Is the IP address 192.168.50.137 reachable? Run: ping 192.168.50.137")
    print("3. Are the credentials (admin / L2DD2594) correct?")
    print("4. Is there another RTSP client (like VLC, or an NVR, or another user) holding the stream? Many cameras only support a single connection.")

if direct_ok and not mediamtx_ok:
    print("\nTroubleshooting MediaMTX Connection:")
    print("1. Is MediaMTX running? Double-click mediamtx.exe or run it in powershell.")
    print("2. Look at the MediaMTX logs. Does it show errors trying to connect to the camera?")
    print("3. Check for firewall blockages on port 8554.")
    print("4. Did you copy mediamtx.yml containing the source configuration to the MediaMTX directory?")
