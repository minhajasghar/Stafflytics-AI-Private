import cv2
import os

url = "rtsp://admin:L2DD2594@192.168.50.251:554/cam/realmonitor?channel=1&subtype=0"
print(f"Opening RTSP URL to check resolution: {url}")

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

if cap.isOpened():
    ret, frame = cap.read()
    if ret and frame is not None:
        h, w, c = frame.shape
        print(f"\nSUCCESS! Frame read successfully.")
        print(f"Captured Frame Width: {w}px")
        print(f"Captured Frame Height: {h}px")
        print(f"Captured Frame Channels: {c}")
    else:
        print("\nFailed to read frame.")
    cap.release()
else:
    print("\nFailed to open RTSP stream.")
