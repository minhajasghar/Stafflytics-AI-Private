import sys
import cv2
import time

print("Probing proxy RTSP url: rtsp://127.0.0.1:8554/cam ...")
cap = cv2.VideoCapture("rtsp://127.0.0.1:8554/cam")

if not cap.isOpened():
    print("FAILURE: Could not open RTSP stream!")
    sys.exit(1)

ret, frame = cap.read()
if ret and frame is not None:
    print(f"SUCCESS: Captured frame from proxy stream! Resolution: {frame.shape[1]}x{frame.shape[0]}")
else:
    print("FAILURE: Opened stream, but failed to read frames.")
cap.release()
