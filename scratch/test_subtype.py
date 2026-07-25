import cv2
import os

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

ip = "192.168.50.251"
subtypes = [0, 1]

for subtype in subtypes:
    url = f"rtsp://admin:L2DD2594@{ip}:554/cam/realmonitor?channel=1&subtype={subtype}"
    print(f"\nProbing URL: {url}")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if cap and cap.isOpened():
        ret, frame = cap.read()
        if ret and frame is not None:
            print(f"SUCCESS: Connected and read frame from {ip} (subtype={subtype})! Shape: {frame.shape}")
        else:
            print(f"FAILED: Connected to {ip} (subtype={subtype}), but could not read frame.")
        cap.release()
    else:
        print(f"FAILED: Could not open connection to {ip} (subtype={subtype}).")
