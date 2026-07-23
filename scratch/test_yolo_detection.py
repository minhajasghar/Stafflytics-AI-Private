import os
import sys
import numpy as np
import cv2

print("Starting test_yolo_detection.py")
try:
    from ultralytics import YOLO
    model_path = os.path.join('models', 'yolov8n-pose.pt')
    print("Model path:", os.path.abspath(model_path))
    if not os.path.exists(model_path):
        print("Model file does not exist!")
        sys.exit(1)
        
    model = YOLO(model_path)
    print("YOLO Model loaded successfully.")
    
    # Create a dummy image with a person-like shape or just blank
    # To see if tracking runs without error
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    
    print("Running model.track on blank frame...")
    results = model.track(img, persist=True, verbose=True)
    print("Results length:", len(results))
    if len(results) > 0:
        res = results[0]
        print("Boxes:", res.boxes)
        if res.boxes is not None:
            print("Boxes xyxy:", res.boxes.xyxy)
            print("Boxes id:", res.boxes.id)
            print("Boxes cls:", res.boxes.cls)
            
except Exception as e:
    import traceback
    traceback.print_exc()
