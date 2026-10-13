"""
Stafflytics AI - Persistent Identity System Verification & Test Suite
====================================================================
Tests the persistent identity system against:
(a) ID stability when face is blocked / covered or person is occluded behind a chair.
(b) Identity re-attachment when a person leaves the frame and returns within the 60s window.
(c) Strict separation: Staff and Customers are never mixed.
(d) Atomic counter safety under concurrent multi-threaded execution (no duplicate IDs).

Can be run standalone:
    python test_identity_system.py
Or with an optional video file:
    python test_identity_system.py --video path/to/video.mp4
"""

import sys
import os
import time
import argparse
import threading
import numpy as np
import cv2

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database
from identity_manager import (
    PersistentIdentityManager,
    extract_body_reid_vector,
    compute_laplacian_sharpness
)


def create_synthetic_person(color_shirt=(180, 50, 50), color_pants=(30, 30, 30), face_visible=True):
    """Generates a synthetic person body crop and face crop for testing."""
    # Body crop: 256h x 128w
    body = np.zeros((256, 128, 3), dtype=np.uint8)
    # Head region (0-25%)
    body[0:64, :] = (200, 180, 160)
    # Torso / Shirt (25-65%)
    body[64:166, :] = color_shirt
    # Pants (65-100%)
    body[166:256, :] = color_pants
    
    if face_visible:
        face = np.full((80, 80, 3), (200, 180, 160), dtype=np.uint8)
        # Add eyes and mouth for texture / sharpness
        cv2.circle(face, (25, 30), 5, (20, 20, 20), -1)
        cv2.circle(face, (55, 30), 5, (20, 20, 20), -1)
        cv2.rectangle(face, (30, 55), (50, 60), (40, 40, 120), -1)
    else:
        face = None
        
    return body, face


def run_tests():
    print("=" * 70)
    print("  Stafflytics AI: Persistent Identity System Test Suite")
    print("=" * 70)
    
    # Initialize clean in-memory test configuration
    test_config = {
        "FACE_MATCH_THRESHOLD": 0.38,
        "BODY_REID_THRESHOLD": 0.75,
        "FUSED_MATCH_THRESHOLD": 0.65,
        "RECENTLY_LOST_WINDOW_SEC": 5.0,  # 5 seconds for fast test cycle
        "CUSTOMER_CONFIRMATION_WINDOW_SEC": 0.5, # 500ms confirmation for test
        "CONFIRMATION_MIN_HITS": 3,
        "VERIFICATION_INTERVAL_FRAMES": 10,
        "MAX_GALLERY_SIZE": 5
    }
    
    manager = PersistentIdentityManager(config=test_config)
    manager.identities.clear()
    manager.track_to_identity.clear()
    manager.identity_to_track.clear()
    manager.provisional_tracks.clear()
    manager.recently_lost.clear()
    total_id_switches = 0
    passed_tests = 0
    total_tests = 4

    # -----------------------------------------------------------------------
    # TEST (d): Atomic Counter Safety & Concurrency
    # -----------------------------------------------------------------------
    print("\n[TEST 1/4] Atomic Counter Safety & Concurrent Multi-Threading...")
    generated_staff_ids = []
    generated_cust_ids = []
    counter_lock = threading.Lock()

    def allocate_staff_worker():
        idx = database.get_next_identity_index("staff")
        with counter_lock:
            generated_staff_ids.append(idx)

    def allocate_cust_worker():
        idx = database.get_next_identity_index("customer")
        with counter_lock:
            generated_cust_ids.append(idx)

    threads = []
    for _ in range(20):
        threads.append(threading.Thread(target=allocate_staff_worker))
        threads.append(threading.Thread(target=allocate_cust_worker))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify no duplicates
    assert len(generated_staff_ids) == 20, "Failed: Expected 20 staff IDs generated"
    assert len(set(generated_staff_ids)) == 20, "FAILED: Duplicate staff ID generated!"
    assert len(set(generated_cust_ids)) == 20, "FAILED: Duplicate customer ID generated!"
    print(f" -> PASSED: 20 Staff & 20 Customer IDs atomically allocated with 0 duplicates.")
    passed_tests += 1

    # -----------------------------------------------------------------------
    # TEST (c): Staff & Customer Separation & Enrollment Mode
    # -----------------------------------------------------------------------
    print("\n[TEST 2/4] Staff Enrollment & Customer Isolation...")
    staff_body, staff_face = create_synthetic_person(color_shirt=(220, 40, 40), color_pants=(10, 10, 10))
    # Synthetic face embedding vector (normalized 512-d)
    np.random.seed(42)
    fake_staff_face_emb = np.random.randn(512).astype(np.float32)
    fake_staff_face_emb /= np.linalg.norm(fake_staff_face_emb)

    # Enable Staff Enrollment
    manager.enable_enrollment_mode(target_track_id=101)
    label_staff, col_s, staff_iid, is_conf_s = manager.process_track_observation(
        track_id=101,
        box=[100, 100, 200, 300],
        frame_count=1,
        face_embedding=fake_staff_face_emb,
        body_crop=staff_body,
        face_crop=staff_face
    )
    assert label_staff.startswith("Staff"), f"FAILED: Expected Staff ID, got {label_staff}"
    assert is_conf_s is True, "FAILED: Staff should be immediately confirmed upon enrollment"
    print(f" -> Enrolled Track #101 as '{label_staff}' (ID: {staff_iid}).")

    # Now introduce an unknown person (Customer candidate)
    cust_body, cust_face = create_synthetic_person(color_shirt=(30, 180, 40), color_pants=(80, 80, 80))
    fake_cust_face_emb = np.random.randn(512).astype(np.float32)
    fake_cust_face_emb /= np.linalg.norm(fake_cust_face_emb)

    # First observation should be 'Unknown'
    label_c1, _, cid1, conf1 = manager.process_track_observation(
        track_id=202,
        box=[300, 100, 400, 300],
        frame_count=1,
        face_embedding=fake_cust_face_emb,
        body_crop=cust_body,
        face_crop=cust_face
    )
    assert not label_c1.startswith("Customer"), f"FAILED: Candidate customer should not be confirmed early, got {label_c1}"
    assert conf1 is False, "FAILED: Candidate customer should not be confirmed early"

    # Simulate stability over confirmation window
    time.sleep(0.55)
    for f in range(2, 6):
        label_c2, _, cid2, conf2 = manager.process_track_observation(
            track_id=202,
            box=[300, 100, 400, 300],
            frame_count=f,
            face_embedding=fake_cust_face_emb,
            body_crop=cust_body,
            face_crop=cust_face
        )

    assert label_c2.startswith("Customer"), f"FAILED: Stable person should become Customer, got {label_c2}"
    assert conf2 is True, "FAILED: Customer should be confirmed after window"
    assert label_staff != label_c2, "FAILED: Staff and customer IDs mixed!"
    print(f" -> Confirmed Track #202 as '{label_c2}'. Staff & Customers strictly isolated.")
    passed_tests += 1

    # -----------------------------------------------------------------------
    # TEST (a): ID Stability when Face is Covered / Occluded (Hand on chin / Mask)
    # -----------------------------------------------------------------------
    print("\n[TEST 3/4] ID Stability during Face Occlusion (Mask / Hand on Chin / Turned Away)...")
    # Observation with NO FACE (face blocked), only body ReID visible
    assigned_labels = []
    for f in range(10, 25):
        # Face is None!
        label_occ, _, iid_occ, is_conf_occ = manager.process_track_observation(
            track_id=101,
            box=[105, 100, 205, 300],
            frame_count=f,
            face_embedding=None, # Face is 100% blocked
            body_crop=staff_body,
            face_crop=None
        )
        assigned_labels.append(label_occ)

    id_switches_a = sum(1 for l in assigned_labels if l != label_staff)
    total_id_switches += id_switches_a
    assert id_switches_a == 0, f"FAILED: ID switched during occlusion! (Switches: {id_switches_a})"
    print(f" -> PASSED: Track #101 maintained '{label_staff}' across 15 occluded frames. ID switches: {id_switches_a}")
    passed_tests += 1

    # -----------------------------------------------------------------------
    # TEST (b): Leave & Re-enter Frame within 60s Window
    # -----------------------------------------------------------------------
    print("\n[TEST 4/4] Leave & Return within Window Re-Identification...")
    # Staff member leaves frame
    manager.handle_track_lost(101)
    assert 101 not in manager.active_locks, "FAILED: Track should be cleared from active locks"
    assert staff_iid in manager.recently_lost, "FAILED: Identity should be preserved in recently_lost buffer"

    # Now person re-enters frame with a NEW ByteTrack track_id: 303!
    # Even with face partially occluded or visible:
    label_returned, _, returned_iid, is_conf_ret = manager.process_track_observation(
        track_id=303, # New track assigned by ByteTrack
        box=[120, 100, 220, 300],
        frame_count=50,
        face_embedding=None, # Re-entering with face looking down/away!
        body_crop=staff_body, # Body ReID matches!
        face_crop=None
    )
    assert returned_iid == staff_iid, f"FAILED: Re-entry ID mismatch! Expected {staff_iid}, got {returned_iid}"
    assert label_returned == label_staff, f"FAILED: Re-entry label mismatch! Expected {label_staff}, got {label_returned}"
    print(f" -> PASSED: New Track #303 successfully re-attached to '{label_returned}' via Body ReID within window.")
    passed_tests += 1

    # -----------------------------------------------------------------------
    # Summary Report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  VERIFICATION REPORT SUMMARY")
    print("=" * 70)
    print(f" Tests Passed:         {passed_tests} / {total_tests}")
    print(f" Total ID Switches:    {total_id_switches}")
    print(f" Face Occlusion Test:  STABLE (0 switches)")
    print(f" Re-attachment Test:   SUCCESSFUL")
    print(f" Staff/Customer Mix:   NONE (Strict Separation)")
    print(f" Atomic Counter Check: ZERO DUPLICATES (Thread-Safe)")
    print("=" * 70)
    
    return total_id_switches == 0 and passed_tests == total_tests


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Persistent Identity Verification")
    parser.add_argument("--video", type=str, default=None, help="Optional path to a recorded video replay file")
    args = parser.parse_args()
    
    if args.video and os.path.exists(args.video):
        print(f"[REPLAY] Running persistent identity on recorded video: {args.video}")
        import vision_engine
        cap = cv2.VideoCapture(args.video)
        engine = vision_engine.VisionEngine()
        frame_idx = 0
        id_switches = 0
        prev_tracks = {}
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            frame_idx += 1
            _, dets = engine.process_frame(frame)
            for d in dets:
                tid = d["track_id"]
                lbl = d["label"]
                if tid in prev_tracks and prev_tracks[tid] != lbl:
                    id_switches += 1
                prev_tracks[tid] = lbl
            if frame_idx % 50 == 0:
                print(f"  Frame {frame_idx}: {len(dets)} tracks, cumulative ID switches: {id_switches}")
        cap.release()
        print(f"\n[VIDEO REPLAY RESULT] Processed {frame_idx} frames. Total ID switches: {id_switches}")
    else:
        success = run_tests()
        sys.exit(0 if success else 1)
