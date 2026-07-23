import os
import sys
import numpy as np
import cv2

print("Starting test_cam_and_yolo.py")
try:
    # 1. Try to open the proxy RTSP URL
    RTSP_URL = "rtsp://127.0.0.1:8554/cam"
    print(f"Connecting to RTSP URL: {RTSP_URL}")
    cap = cv2.VideoCapture(RTSP_URL)
    
    if not cap.isOpened():
        print(f"Failed to open proxy RTSP URL: {RTSP_URL}")
        # Try direct physical URL
        PHYSICAL_RTSP_URL = "rtsp://admin:L2DD2594@192.168.50.251:554/cam/realmonitor?channel=1&subtype=0"
        print(f"Connecting to physical RTSP URL: {PHYSICAL_RTSP_URL}")
        cap = cv2.VideoCapture(PHYSICAL_RTSP_URL)
        if not cap.isOpened():
            print("Failed to open physical RTSP URL as well.")
            sys.exit(1)
            
    print("Camera stream opened successfully.")
    
    # 2. Load YOLO model
    from ultralytics import YOLO
    model_path = os.path.join('models', 'yolov8n-pose.pt')
    if not os.path.exists(model_path):
        print("Model file does not exist!")
        sys.exit(1)
    model = YOLO(model_path)
    print("YOLO Model loaded.")
    
    # 3. Read 5 frames and process
    for i in range(5):
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"Frame {i}: Failed to read frame")
            continue
            
        print(f"Frame {i}: Read frame of shape {frame.shape}")
        
        # Run YOLO track/detection
        small_frame = cv2.resize(frame, (640, 480))
        results = model.track(small_frame, persist=True, verbose=False)
        print(f"Frame {i}: YOLO results length: {len(results)}")
        if len(results) > 0:
            res = results[0]
            if res.boxes is not None:
                boxes = res.boxes.xyxy.cpu().numpy()
                cls = res.boxes.cls.cpu().numpy()
                conf = res.boxes.conf.cpu().numpy()
                track_ids = res.boxes.id.int().cpu().numpy() if res.boxes.id is not None else []
                print(f"Frame {i}: Detected {len(boxes)} boxes:")
                for b, c, cf, tid in zip(boxes, cls, conf, track_ids if len(track_ids) == len(boxes) else [None]*len(boxes)):
                    print(f"  - Track ID: {tid}, Class: {c}, Conf: {cf:.2f}, Box: {b}")
            else:
                print(f"Frame {i}: res.boxes is None")
        else:
            print(f"Frame {i}: No results returned")
            
    cap.release()
except Exception as e:
    import traceback
    traceback.print_exc()
