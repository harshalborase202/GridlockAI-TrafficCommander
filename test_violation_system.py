# test_violation_system.py
# Synthetic simulation harness to test and verify the traffic violation detection system.
# This script generates a test video containing mock vehicle trajectories and feeds it to the violation engine.

import cv2
import numpy as np
import os
import json
from violation_engine import ViolationEngine
import config

def generate_synthetic_traffic_video(filename="test_simulation.mp4", duration_frames=220, fps=30):
    """
    Generates a synthetic traffic video containing vehicles executing specific movements
    designed to trigger all four traffic violations.
    """
    width, height = 1280, 720
    # Open VideoWriter
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(filename, fourcc, fps, (width, height))
    
    print(f"Generating synthetic video: {filename}...")
    
    # Generate background frame representing a simple street lane layout
    background = np.zeros((height, width, 3), dtype=np.uint8)
    # Draw simple road outlines to make it look realistic
    background[:, 590:610] = (100, 100, 100)  # Center lane dividing line
    
    # We will simulate 4 vehicles:
    # 1. Car (ID 101): Crosses Stop Line y=500 moving DOWN from frame 10 to 30. Light is RED.
    # 2. Motorcycle (ID 102): Drives UP (y decreasing) on the RIGHT lane (x=900) from frame 1 to 30. Allowed is DOWN. (Wrong Way)
    # 3. Truck (ID 103): Enters No Parking Zone (x=200, y=600) and remains stationary from frame 40 to 220 (approx 6 seconds).
    # 4. Bus (ID 104): Passes Speed Gate 1 (y=320) at frame 80, passes Speed Gate 2 (y=480) at frame 86 (speeding!).
    
    for f in range(duration_frames):
        # Start with a clean copy of the road background
        frame = background.copy()
        
        # 1. Simulate Vehicle 101 (Car)
        if 10 <= f <= 30:
            # Moves from y = 420 to 580 (crosses 500)
            y = 420 + (f - 10) * 8
            # Draw green rectangle for Car
            cv2.rectangle(frame, (250, y - 20), (330, y + 20), (0, 200, 0), -1)
            
        # 2. Simulate Vehicle 102 (Motorcycle)
        if 1 <= f <= 35:
            # Moves from y = 600 to 300 (moving upwards, which is wrong way for right lane)
            y = 600 - (f - 1) * 9
            # Draw cyan circle representing Motorcycle
            cv2.circle(frame, (900, y), 15, (255, 200, 0), -1)
            
        # 3. Simulate Vehicle 103 (Truck)
        if 40 <= f <= 220:
            # Enters parking zone and stops at (200, 600)
            y = 600
            # Draw blue rectangle representing stationary Truck
            cv2.rectangle(frame, (160, y - 30), (240, y + 30), (250, 50, 50), -1)
            
        # 4. Simulate Vehicle 104 (Bus)
        if 80 <= f <= 100:
            # Enters above Gate 1 (320) and exits below Gate 2 (480)
            # Moves from y = 290 to 590. Crosses 320 at frame 82, 480 at frame 92 (10 frames = 0.33s = 216 km/h)
            y = 290 + (f - 80) * 15
            # Draw magenta rectangle representing speeding Bus
            cv2.rectangle(frame, (500, y - 40), (580, y + 40), (200, 0, 200), -1)
            
        video_writer.write(frame)
        
    video_writer.release()
    print("Synthetic video generated successfully!")

def run_violation_pipeline(input_filename="test_simulation.mp4", output_filename="output_tracked.mp4"):
    """
    Feeds the synthetic video frames into the violation engine by simulating tracker outputs
    and compiling the final output video with HUD and bounding box overlays.
    """
    cap = cv2.VideoCapture(input_filename)
    if not cap.isOpened():
        raise ValueError(f"Could not open test video: {input_filename}")
        
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Initialize output video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_filename, fourcc, fps, (width, height))
    
    # Instantiate the Violation Engine
    engine = ViolationEngine("violations.json")
    
    print("\nRunning tracking & violation engine pipeline simulation...")
    
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # Simulate traffic light scheduler: RED from frame 0-100, GREEN from frame 100-220
        light_state = "RED" if frame_idx < 100 else "GREEN"
        
        # Build mock active tracks list for the current frame
        # Formatted as: (track_id, class_id, confidence, bbox_xyxy)
        # Class mapping COCO: 2 (car), 3 (motorcycle), 5 (bus), 7 (truck)
        active_tracks = []
        
        # 1. Car (ID 101) - crosses y=500 stop line during RED light (frame 10-30)
        if 10 <= frame_idx <= 30:
            y = 420 + (frame_idx - 10) * 8
            active_tracks.append((101, 2, 0.95, [250, y - 20, 330, y + 20]))
            
        # 2. Motorcycle (ID 102) - drives UP in right lane (frame 1-35)
        if 1 <= frame_idx <= 35:
            y = 600 - (frame_idx - 1) * 9
            active_tracks.append((102, 3, 0.91, [885, y - 15, 915, y + 15]))
            
        # 3. Truck (ID 103) - parked stationary inside No Parking polygon (frame 40-220)
        if 40 <= frame_idx <= 220:
            active_tracks.append((103, 7, 0.88, [160, 570, 240, 630]))
            
        # 4. Bus (ID 104) - overspeeding between gates (frame 80-100)
        if 80 <= frame_idx <= 100:
            y = 290 + (frame_idx - 80) * 15
            active_tracks.append((104, 5, 0.94, [500, y - 40, 580, y + 40]))
            
        # Process frame
        annotated_frame, stats = engine.process_frame(
            frame, active_tracks, frame_idx, fps, light_state
        )
        
        out.write(annotated_frame)
        
        # Print periodic updates
        if frame_idx % 30 == 0:
            print(f"Frame {frame_idx:03d} processed | Active violations logged: {stats['total_violations']}")
            
        frame_idx += 1
        
    cap.release()
    out.release()
    
    print("\n" + "="*50)
    print("             PIPELINE COMPLETED SUCCESSFULY")
    print("="*50)
    print("Final Statistics:")
    print(f"- Total Violations Logged: {stats['total_violations']}")
    print(f"  * Red Light Running:     {stats['Red Light Violation']}")
    print(f"  * Wrong Way Driving:     {stats['Wrong Way Driving']}")
    print(f"  * Illegal Parking:       {stats['Illegal Parking']}")
    print(f"  * Overspeeding:          {stats['Overspeeding']}")
    print("="*50)

if __name__ == "__main__":
    # 1. Generate synthetic traffic footage
    generate_synthetic_traffic_video("test_simulation.mp4")
    
    # 2. Run simulation pipeline
    run_violation_pipeline("test_simulation.mp4", "output_tracked.mp4")
    
    # 3. Confirm violations.json log output
    print(f"Checking serialization data logs in 'violations.json':")
    if os.path.exists("violations.json"):
        with open("violations.json", 'r') as f:
            log_data = json.load(f)
        print(f"Successfully loaded {len(log_data)} violation log events.")
        # Print sample event
        if len(log_data) > 0:
            print("\nSample Violation Event Log:")
            print(json.dumps(log_data[0], indent=2))
