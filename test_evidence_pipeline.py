# test_evidence_pipeline.py
# Verification and unit testing script for Phase 3 evidence generation, ANPR, and ticketing.

import os
import cv2
import numpy as np
import json
from evidence_generator import EvidenceGenerator
from evidence_manager import EvidenceManager

def run_test_suite():
    print("="*60)
    print("      PHASE 3: EVIDENCE ENGINE UNIT TESTING SUITE")
    print("="*60)
    
    # 1. Setup Master Orchestrator
    # We choose FPS = 15.
    # Therefore, 1 second = 15 frames, 2 seconds = 30 frames.
    # Violation F = 50:
    # T - 2s = frame 20
    # T - 1s = frame 35
    # T = frame 50
    # T + 1s = frame 65
    # T + 2s = frame 80
    fps = 15
    orchestrator = EvidenceGenerator(fps=fps)
    
    # Canvas size for mock frames
    w, h = 1280, 720
    
    print(f"Initializing simulation stream | FPS: {fps}")
    print("Streaming frames 0 to 100...")

    violation_id = "V_50_101_RED"
    violation_frame = 50
    mock_bbox = [200, 300, 450, 550]  # Vehicle bounding box coordinates

    case_tickets = []

    # 2. Run Video Stream Simulation
    for f in range(101):
        # Generate a dummy frame with a grey background and frame index text
        frame = np.ones((h, w, 3), dtype=np.uint8) * 40
        # Draw some lanes
        cv2.line(frame, (100, 500), (1180, 500), (0, 0, 255), 2)
        # Draw frame number
        cv2.putText(frame, f"CCTV FEED - FRAME {f}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        
        # Draw vehicle 101 bounding box on frame 50 to simulate detection
        if f == violation_frame:
            cv2.rectangle(frame, (mock_bbox[0], mock_bbox[1]), (mock_bbox[2], mock_bbox[3]), (0, 255, 255), 3)
            cv2.putText(frame, "VEHICLE ID 101", (mock_bbox[0], mock_bbox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
        # Feed frame to buffer
        orchestrator.add_stream_frame(f, frame)

        # Trigger violation detection at frame 50
        if f == violation_frame:
            print(f"--> [Trigger] Red Light Violation detected at frame {f} for Vehicle 101.")
            orchestrator.trigger_violation_evidence(violation_id, violation_frame, mock_bbox)

        # Call update on every frame to check for task completions
        # (Pass mock tracking conf of 0.93)
        completed_cases = orchestrator.update_and_process(f, frame, tracker_confidence=0.93)
        if completed_cases:
            print(f"--> [Completed] Evidence generated successfully for {violation_id} at frame {f}!")
            case_tickets.extend(completed_cases)

    # 3. Assert Directory and File Structure
    print("\n" + "-"*50)
    print("VERIFYING ARTIFACT FILESYSTEM OUTPUTS")
    print("- "*25)
    
    target_dir = os.path.join("evidence", violation_id)
    assert os.path.exists(target_dir), "Directory 'evidence/V_50_101_RED' does not exist."
    print("[OK] Evidence directory created.")

    expected_files = [
        "frame_minus2.jpg",
        "frame_minus1.jpg",
        "frame_0.jpg",
        "frame_plus1.jpg",
        "frame_plus2.jpg",
        "cropped_vehicle.jpg",
        "enhanced_vehicle.jpg",
        "plate_crop.jpg",
        "evidence_summary.jpg",
        "ticket.json"
    ]

    for fname in expected_files:
        path = os.path.join(target_dir, fname)
        assert os.path.exists(path), f"File {fname} is missing in case folder."
        print(f"  [OK] Found file: {fname}")

    # Check case index
    index_path = "evidence/case_index.json"
    assert os.path.exists(index_path), "Central case_index.json is missing."
    print("[OK] Central case_index.json found.")

    # 4. Assert Database Case Management operations
    print("\n" + "-"*50)
    print("VERIFYING CASE MANAGEMENT DATABASE LOOKUPS")
    print("- "*25)

    manager = EvidenceManager()
    
    # Query 1: load_case
    loaded_case = manager.load_case(violation_id)
    assert loaded_case is not None, "Failed to load case from registry."
    assert loaded_case["violation_id"] == violation_id, "Mismatch in loaded case ID."
    print(f"[OK] load_case lookup: Retrieved Ticket ID {loaded_case['ticket_id']}")

    # Query 2: get_case_by_plate
    plate_matches = manager.get_case_by_plate("DL 3C AW 5678")
    assert len(plate_matches) > 0, "No cases found for plate DL 3C AW 5678."
    print(f"[OK] get_case_by_plate lookup: Found {len(plate_matches)} case(s) for vehicle license plate.")

    # Query 3: get_case_by_violation_type
    type_matches = manager.get_case_by_violation_type("Red Light Violation")
    assert len(type_matches) > 0, "No cases found for violation type Red Light Violation."
    print(f"[OK] get_case_by_violation_type lookup: Found {len(type_matches)} case(s) for Red Light Running.")

    print("\n" + "="*60)
    print("           ALL TESTS PASSED SUCCESSFULLY! (100% OK)")
    print("="*60)

    # Print resulting JSON ticket for command center review
    print("\nGenerated Digital Ticket Output (Command Center Preview):")
    print(json.dumps(loaded_case, indent=2))

if __name__ == "__main__":
    run_test_suite()
