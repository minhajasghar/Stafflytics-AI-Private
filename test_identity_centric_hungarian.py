"""
Unit & Integration Test Suite for Identity-Centric Hungarian Architecture
========================================================================
Validates:
1. Hungarian Assignment (Appearance primary, Spatial secondary)
2. Identity Movement & Exclusivity (Track A -> Track B, Track A evicted)
3. Provisional Candidate Isolation (No Customer minting until confirmation window)
4. Duplicate Prevention & Merging (Unmatched candidate merges into existing)
5. Sticky Labels (Never drops to Unknown during occlusion)
"""
import time
import numpy as np
import cv2
from identity_manager import PersistentIdentityManager, extract_body_reid_vector

def make_person_image(color=(120, 80, 200)):
    # 256 x 128 synthetic person crop
    img = np.zeros((256, 128, 3), dtype=np.uint8)
    img[0:64, :] = (200, 180, 160)      # head
    img[64:170, :] = color              # shirt
    img[170:256, :] = (40, 40, 40)      # pants
    return img

def run_tests():
    print("=" * 70)
    print("TESTING IDENTITY-CENTRIC HUNGARIAN ASSIGNMENT ARCHITECTURE")
    print("=" * 70)

    mgr = PersistentIdentityManager({
        "CUSTOMER_CONFIRMATION_WINDOW_SEC": 1.0,
        "CONFIRMATION_MIN_HITS": 3,
        "BODY_REID_THRESHOLD": 0.70,
        "FACE_MATCH_THRESHOLD": 0.35,
        "RECENTLY_LOST_WINDOW_SEC": 5.0
    })
    mgr.identities.clear()
    mgr.track_to_identity.clear()
    mgr.identity_to_track.clear()
    mgr.provisional_tracks.clear()
    mgr.recently_lost.clear()

    # Pre-register Staff 1 with a distinct blue shirt
    staff_blue_img = make_person_image(color=(220, 50, 50)) # Blue in BGR
    staff_blue_vec = extract_body_reid_vector(staff_blue_img)
    mgr.identities["staff_1"] = {
        "id": "staff_1", "type": "staff", "label": "Staff 1",
        "numeric_index": 1, "face_gallery": [], "body_gallery": [staff_blue_vec],
        "last_seen": time.time(), "last_box": [100, 100, 200, 300], "bound_track_id": None
    }

    # -------------------------------------------------------------
    # TEST 1: Initial Hungarian Assignment to Existing Identity
    # -------------------------------------------------------------
    print("\n[TEST 1] Assigning detection to Staff 1 via Body Appearance...")
    dets = [{
        "track_id": 2,
        "box": [105, 105, 205, 305],
        "body_crop": staff_blue_img,
        "face_crop": None,
        "face_enc": None
    }]
    assigned, evicted = mgr.assign_detections(dets)
    assert 2 in assigned, "Track #2 should be assigned"
    assert assigned[2]["identity_id"] == "staff_1", f"Expected staff_1, got {assigned[2]['identity_id']}"
    assert assigned[2]["label"] == "Staff 1"
    assert mgr.identity_to_track["staff_1"] == 2
    print(" -> PASSED: Track #2 bound to Staff 1 via Hungarian appearance matching.")

    # -------------------------------------------------------------
    # TEST 2: Person Moves -> New Track ID -> Move Identity & Evict Stale Track
    # -------------------------------------------------------------
    print("\n[TEST 2] Person moves: ByteTrack assigns new Track #15 at new seat...")
    dets_moved = [{
        "track_id": 15,
        "box": [400, 100, 500, 300], # Moved to new position
        "body_crop": staff_blue_img,   # Same person!
        "face_crop": None,
        "face_enc": None
    }]
    assigned_m, evicted_m = mgr.assign_detections(dets_moved)
    assert 15 in assigned_m, "Track #15 should be assigned"
    assert assigned_m[15]["identity_id"] == "staff_1", "Identity must MOVE to Track #15"
    assert 2 in evicted_m, "Stale Track #2 must be EVICTED!"
    assert mgr.identity_to_track["staff_1"] == 15, "Identity must point only to Track #15"
    assert 2 not in mgr.track_to_identity, "Stale Track #2 must no longer hold identity"
    print(" -> PASSED: Identity successfully MOVED from Track #2 to Track #15; Track #2 evicted.")

    # -------------------------------------------------------------
    # TEST 3: Provisional Candidate Tracking (No Blind Customer Minting)
    # -------------------------------------------------------------
    print("\n[TEST 3] New unknown person arrives: must be Provisional, NOT a numbered Customer...")
    green_cust_img = make_person_image(color=(50, 200, 50)) # Green in BGR
    dets_new = [{
        "track_id": 20,
        "box": [50, 50, 150, 250],
        "body_crop": green_cust_img,
        "face_crop": None,
        "face_enc": None
    }]
    # Frame 1
    t0 = time.time()
    assigned_p1, _ = mgr.assign_detections(dets_new, current_time=t0)
    assert assigned_p1[20]["type"] == "provisional", "New person must start as provisional"
    assert not assigned_p1[20]["label"].startswith("Customer"), "Must NOT be numbered Customer yet"
    print(f" -> Frame 1: Assigned '{assigned_p1[20]['label']}' (is_locked={assigned_p1[20]['is_locked']})")

    # Frame 2 & 3 before window completes
    assigned_p2, _ = mgr.assign_detections(dets_new, current_time=t0 + 0.3)
    assert assigned_p2[20]["type"] == "provisional", "Must remain provisional before time window"

    # Frame 4 after window completes (t0 + 1.2s)
    assigned_p3, _ = mgr.assign_detections(dets_new, current_time=t0 + 1.2)
    assert assigned_p3[20]["type"] == "customer", "Must be confirmed as customer after window"
    assert assigned_p3[20]["label"].startswith("Customer"), "Must be minted as Customer"
    minted_id = assigned_p3[20]["identity_id"]
    print(f" -> Confirmed & Minted '{assigned_p3[20]['label']}' ({minted_id}) after 1.2s stability.")
    print(" -> PASSED: Provisional stability window prevented premature customer minting.")

    # -------------------------------------------------------------
    # TEST 4: Occlusion Sticky Label Retention
    # -------------------------------------------------------------
    print("\n[TEST 4] Occlusion test: Person turns away / body degraded...")
    dets_occluded = [{
        "track_id": 20,
        "box": [55, 55, 155, 255],
        "body_crop": None, # Completely occluded / missed
        "face_crop": None,
        "face_enc": None
    }]
    assigned_occ, _ = mgr.assign_detections(dets_occluded, current_time=t0 + 1.5)
    assert assigned_occ[20]["label"] == assigned_p3[20]["label"], "Label must remain sticky"
    assert assigned_occ[20]["is_locked"] is True, "Must retain locked status"
    print(f" -> PASSED: Occluded Track #20 retained sticky label '{assigned_occ[20]['label']}'.")

    # -------------------------------------------------------------
    # TEST 5: Duplicate Prevention via Merge
    # -------------------------------------------------------------
    print("\n[TEST 5] Candidate merge: Track re-appears after brief gap with same appearance...")
    dets_return = [{
        "track_id": 44, # New track number for returning customer
        "box": [60, 60, 160, 260],
        "body_crop": green_cust_img, # Same green shirt!
        "face_crop": None,
        "face_enc": None
    }]
    # Run over stability window to trigger merge check
    t1 = time.time()
    mgr.assign_detections(dets_return, current_time=t1)
    mgr.assign_detections(dets_return, current_time=t1 + 0.5)
    assigned_ret, _ = mgr.assign_detections(dets_return, current_time=t1 + 1.2)
    assert assigned_ret[44]["identity_id"] == minted_id, f"Must MERGE into existing {minted_id}, got {assigned_ret[44]['identity_id']}"
    print(f" -> PASSED: Returning Track #44 merged into existing identity '{assigned_ret[44]['label']}' ({minted_id}).")

    print("\n" + "=" * 70)
    print("ALL 5 IDENTITY-CENTRIC TESTS PASSED PERFECTLY!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    run_tests()
