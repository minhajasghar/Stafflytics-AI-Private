#!/usr/bin/env python3
"""
Stafflytics AI - Edge Vision Worker
==================================
Runs directly on the local Office PC where the camera is connected.
- Reads camera RTSP stream locally with ZERO latency.
- Runs YOLOv11 (OpenVINO / CUDA GPU) tracking & re-identification at full FPS.
- Pushes lightweight bounding boxes & telemetry to the Cloud VPS / Dashboard server.
"""

import os
import sys
import time
import json
import argparse
import threading
import queue
import requests
import cv2
import numpy as np

# Ensure root dir is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

import vision_engine

def parse_args():
    parser = argparse.ArgumentParser(description="Stafflytics Edge YOLOv11 Worker")
    parser.add_argument("--source", type=str, default=os.getenv("EDGE_CAMERA_URL", "rtsp://localhost:8554/cam"),
                        help="RTSP source URL (default: rtsp://localhost:8554/cam)")
    parser.add_argument("--server", type=str, default=os.getenv("SERVER_URL", "http://127.0.0.1:5050"),
                        help="Dashboard server URL to push detections to (default: http://127.0.0.1:5050)")
    parser.add_argument("--fps", type=float, default=20.0,
                        help="Target inference FPS (default: 20)")
    parser.add_argument("--target-w", type=int, default=640,
                        help="Inference frame width (default: 640)")
    parser.add_argument("--target-h", type=int, default=360,
                        help="Inference frame height (default: 360)")
    return parser.parse_args()

class TelemetryPoster:
    """Non-blocking background thread to post detection metadata to the VPS."""
    def __init__(self, endpoint_url):
        self.endpoint_url = endpoint_url
        self.queue = queue.Queue(maxsize=3)
        self.stopped = False
        self.session = requests.Session()
        self.thread = threading.Thread(target=self._run, daemon=True, name="EdgeTelemetryPoster")
        self.thread.start()

    def send(self, payload):
        if self.queue.full():
            try:
                self.queue.get_nowait() # Drop oldest if server is slow
            except queue.Empty:
                pass
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            pass

    def _run(self):
        while not self.stopped:
            try:
                payload = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                # 800ms timeout so a transient network hiccup never stalls
                self.session.post(self.endpoint_url, json=payload, timeout=0.8)
            except Exception as e:
                # Silently ignore transient POST errors
                pass

    def stop(self):
        self.stopped = True

def main():
    args = parse_args()
    print("=" * 60)
    print("  Stafflytics AI - Edge YOLOv11 Worker")
    print("=" * 60)
    print(f"[EDGE] Camera Source : {args.source}")
    print(f"[EDGE] Server Target : {args.server}")
    print(f"[EDGE] Target FPS    : {args.fps}")
    print("-" * 60)

    post_url = args.server.rstrip("/") + "/api/edge/detections"
    poster = TelemetryPoster(post_url)

    # Low latency OpenCV capture flags
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"

    # Initialize Vision Engine
    print("[EDGE] Initializing Vision Engine (YOLOv11)...")
    engine = vision_engine.VisionEngine()
    engine.warmup()
    
    # Wait for YOLO model to finish loading in background
    print("[EDGE] Loading YOLOv11 weights...")
    t0 = time.time()
    while vision_engine.model is None and (time.time() - t0 < 30):
        time.sleep(0.5)

    if vision_engine.model is not None:
        print("[EDGE] YOLOv11 Model Ready!")
    else:
        print("[EDGE WARNING] YOLO model load taking longer than expected. Continuing...")

    consecutive_fails = 0
    cap = None
    frame_interval = 1.0 / max(1.0, args.fps)
    last_infer_time = 0.0

    print(f"[EDGE] Connecting to camera: {args.source} ...")

    while True:
        try:
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(args.source, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    print(f"[EDGE] Camera not opened, retrying in 2s...")
                    time.sleep(2.0)
                    continue
                print(f"[EDGE] Camera stream connected successfully!")
                consecutive_fails = 0

            # Grab latest frame
            if not cap.grab():
                consecutive_fails += 1
                if consecutive_fails > 30:
                    print("[EDGE] Camera grab failed repeatedly. Reconnecting...")
                    cap.release()
                    cap = None
                    time.sleep(1.0)
                time.sleep(0.01)
                continue

            consecutive_fails = 0
            now = time.time()
            if (now - last_infer_time) < frame_interval:
                time.sleep(0.002)
                continue

            ret, frame = cap.retrieve()
            if not ret or frame is None:
                continue

            last_infer_time = now

            # Process frame through Vision Engine
            t_start = time.perf_counter()
            _, detections = engine.process_frame(
                frame,
                target_size=(args.target_w, args.target_h),
                original_frame=frame,
                frame_timestamp=now
            )
            infer_ms = (time.perf_counter() - t_start) * 1000.0

            # Format detections for JSON serialization
            formatted_detections = []
            for d in (detections or []):
                box = d.get('box', [])
                if isinstance(box, np.ndarray):
                    box = box.tolist()
                elif isinstance(box, (list, tuple)):
                    box = [float(b) for b in box]

                formatted_detections.append({
                    "track_id": int(d.get("track_id", 0)),
                    "box": box,
                    "label": str(d.get("label", "HUMAN")),
                    "color": str(d.get("color", "#3b82f6"))
                })

            passage_counts = engine.get_passage_counts()

            # Push telemetry payload to server
            payload = {
                "detections": formatted_detections,
                "frame_w": int(frame.shape[1]),
                "frame_h": int(frame.shape[0]),
                "passage": passage_counts,
                "timestamp": float(now)
            }
            poster.send(payload)

            if int(now * 2) % 6 == 0:  # Print periodically
                det_cnt = len(formatted_detections)
                print(f"[EDGE AI] Active: {det_cnt} people | Infer: {infer_ms:.1f}ms | L->R: {passage_counts.get('l_to_r', 0)} R->L: {passage_counts.get('r_to_l', 0)}")

        except KeyboardInterrupt:
            print("\n[EDGE] Stopped by user.")
            break
        except Exception as e:
            print(f"[EDGE ERROR] {e}")
            time.sleep(1.0)

    if cap is not None:
        cap.release()
    poster.stop()
    print("[EDGE] Worker shutdown complete.")

if __name__ == "__main__":
    main()
