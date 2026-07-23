import cv2
import time
import os

new_url = "rtsp://admin:L2DD2594@192.168.50.249:554/cam/realmonitor?channel=1&subtype=0"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000|reorder_queue_size;0"

print(f"Probing camera at new IP: {new_url} ...")
start = time.time()
try:
    cap = cv2.VideoCapture(new_url, cv2.CAP_FFMPEG)
    if cap and cap.isOpened():
        print(f"Connected to camera on {new_url} in {time.time() - start:.2f}s!")
        ret, frame = cap.read()
        if ret and frame is not None:
            print(f"SUCCESS: Read frame! Shape: {frame.shape}")
        else:
            print("ERROR: Connected, but failed to read frame.")
        cap.release()
    else:
        print("ERROR: Failed to connect to camera on this URL.")
except Exception as e:
    print(f"Exception: {e}")
