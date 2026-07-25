import cv2
import os

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

url = "rtsp://127.0.0.1:8554/mystream"
print(f"Opening local RTSP stream: {url}")
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
if cap and cap.isOpened():
    ret, frame = cap.read()
    if ret and frame is not None:
        print(f"SUCCESS: Read frame from local proxy! Shape: {frame.shape}")
    else:
        print("FAILED: Opened connection, but failed to read frame.")
    cap.release()
else:
    print("FAILED: Could not open local proxy RTSP stream.")
