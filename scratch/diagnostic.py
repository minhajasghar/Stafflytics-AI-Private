import cv2
import time
import os
import sys

print("Diagnostic Start")

# 1. Check Camera
print("Testing Camera (DSHOW)...")
try:
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if cap.isOpened():
        print("Camera (DSHOW) Opened Successfully")
        cap.release()
    else:
        print("Camera (DSHOW) Failed to Open")
except Exception as e:
    print(f"Camera (DSHOW) Error: {e}")

# 2. Check YOLO
print("Testing YOLO Load...")
try:
    from ultralytics import YOLO
    model_path = os.path.join('models', 'yolov8n-pose.pt')
    if os.path.exists(model_path):
        model = YOLO(model_path)
        print("YOLO Loaded Successfully")
    else:
        print(f"YOLO Model not found at {model_path}")
except Exception as e:
    print(f"YOLO Load Error: {e}")

print("Diagnostic Complete")
