# Smart Traffic Violation Detection System (Phase 1)

Welcome to Phase 1 of your AI-powered Smart Traffic Violation Detection System! This phase focuses on **Vehicle Detection and Tracking** using Python in Google Colab. 

This repository contains a pre-compiled notebook, [traffic_detection_tracking.ipynb](file:///c:/Users/harsh/OneDrive/Desktop/GRIDLOCK/traffic_detection_tracking.ipynb), which you can download and run directly in Google Colab.

---

## 🚀 Quick Start Guide for Google Colab

If you are using Google Colab for the first time, follow these steps to run the project:

1. **Open Google Colab:** Go to [colab.research.google.com](https://colab.research.google.com/).
2. **Upload the Notebook:**
   - In the Colab popup window, select the **Upload** tab.
   - Drag and drop or choose the file `traffic_detection_tracking.ipynb` from this folder.
3. **Enable GPU Hardware Acceleration (Crucial for Speed):**
   - In the top menu bar of Google Colab, go to **Runtime** ➔ **Change runtime type**.
   - Under **Hardware accelerator**, select **T4 GPU** (or any available GPU).
   - Click **Save**.
4. **Run Cells:** Click the **Play** button `[ ]` on the left of each cell sequentially, or press `Shift + Enter` to run individual cells.

---

## 📂 Google Colab Code Cells

If you prefer to copy and paste the code manually, here are the 4 cells in sequence:

### Cell 1: Installation & Setup
Installs the YOLOv8 and ByteTrack components via the `ultralytics` package and verifies that the T4 GPU accelerator is active.

```python
# Install the Ultralytics YOLOv8 library
!pip install -q ultralytics

# Verify GPU support and library imports
import torch
import ultralytics
from ultralytics import YOLO
import cv2
import os

print(f"CUDA GPU Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"Device Name: {torch.cuda.get_device_name(0)}")
else:
    print("Warning: GPU not detected. Running on CPU. (To enable GPU, go to Edit -> Notebook Settings -> Hardware Accelerator -> select GPU T4)")

print(f"Ultralytics Version: {ultralytics.__version__}")
print(f"OpenCV Version: {cv2.__version__}")
```

---

### Cell 2: Upload Video Cell
Prompts you to select and upload a CCTV traffic video from your local computer. It automatically validates the format and registers it as `input_video.mp4`.

```python
from google.colab import files

print("Please select your traffic video file (.mp4) to upload:")
uploaded = files.upload()

# Get the name of the uploaded file
uploaded_filename = list(uploaded.keys())[0]

# Ensure it's an MP4 file
if not uploaded_filename.lower().endswith('.mp4'):
    raise ValueError(f"Uploaded file '{uploaded_filename}' is not a .mp4 video. Please run this cell again and select an MP4 video.")

# Rename the file to a standard input name
input_video_path = 'input_video.mp4'
if os.path.exists(input_video_path):
    os.remove(input_video_path)

os.rename(uploaded_filename, input_video_path)
print(f"Successfully uploaded and saved video as '{input_video_path}'")
```

---

### Cell 3: Detection & Tracking Cell
This runs the main detection and tracking loop. It overlays bounding boxes, confidence tags, tracking IDs, and renders a glassmorphic traffic statistics HUD in the video stream. Finally, it converts the output to H.264 using `ffmpeg`.

```python
# 1. Initialize YOLOv8 Model
# yolov8n.pt is pre-trained on COCO dataset which includes cars, buses, trucks, and motorcycles
model = YOLO('yolov8n.pt')

input_video_path = 'input_video.mp4'
temp_output_path = 'output_tracked_raw.mp4'
final_output_path = 'output_tracked.mp4'

if not os.path.exists(input_video_path):
    raise FileNotFoundError(f"'{input_video_path}' not found. Please upload a video in Step 2 first.")

# 2. Open Video Stream
cap = cv2.VideoCapture(input_video_path)
if not cap.isOpened():
    raise ValueError("Error: Could not open the video file.")

# Extract video dimensions, frame rate, and frame count
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = int(cap.get(cv2.CAP_PROP_FPS))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# Set up raw VideoWriter (mp4v codec)
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(temp_output_path, fourcc, fps, (width, height))

# 3. Class Definitions & Style Setup
CLASS_NAMES = {2: 'Car', 3: 'Motorcycle', 5: 'Bus', 7: 'Truck'}
TARGET_CLASSES = list(CLASS_NAMES.keys())

# Harmonious colors for drawing (B, G, R format for OpenCV)
CLASS_COLORS = {
    2: (255, 102, 102),   # Coral Red for Cars
    3: (102, 255, 102),   # Mint Green for Motorcycles
    5: (102, 178, 255),   # Sky Blue for Buses
    7: (255, 178, 102)    # Warm Orange for Trucks
}

# Cumulative Stats Counters
total_tracked_vehicles = set()
vehicle_type_stats = {name: set() for name in CLASS_NAMES.values()}

print("Pipeline started processing. This may take a few minutes depending on video length...")

# 4. Stream-based Tracking Generator Loop
# stream=True processes frame by frame to keep memory footprints low
results = model.track(
    source=input_video_path,
    tracker="bytetrack.yaml",
    persist=True,
    classes=TARGET_CLASSES,
    stream=True
)

frame_count = 0

for result in results:
    frame = result.orig_img.copy()
    boxes = result.boxes
    active_vehicle_count = 0
    
    # Process detections if active tracks exist
    if boxes is not None and boxes.id is not None:
        track_ids = boxes.id.int().cpu().tolist()
        class_ids = boxes.cls.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        xyxys = boxes.xyxy.int().cpu().tolist()
        
        active_vehicle_count = len(track_ids)
        
        # Draw trackers & update metrics
        for track_id, class_id, conf, xyxy in zip(track_ids, class_ids, confidences, xyxys):
            class_name = CLASS_NAMES.get(class_id, 'Vehicle')
            
            # Register unique track IDs
            total_tracked_vehicles.add(track_id)
            vehicle_type_stats[class_name].add(track_id)
            
            # Look up color
            color = CLASS_COLORS.get(class_id, (0, 255, 255))
            
            # Draw bounding box
            x1, y1, x2, y2 = xyxy
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            
            # Text Tag
            label = f"{class_name} ID:{track_id} {conf:.2f}"
            
            # Draw text backplate
            font_face = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 2
            text_size = cv2.getTextSize(label, font_face, font_scale, thickness)[0]
            
            label_y = max(y1, text_size[1] + 10)
            cv2.rectangle(frame, (x1, label_y - text_size[1] - 8), (x1 + text_size[0] + 6, label_y), color, -1)
            cv2.putText(frame, label, (x1 + 3, label_y - 4), font_face, font_scale, (0, 0, 0), thickness)
            
    # 5. Overlay Semi-Transparent HUD
    hud_overlay = frame.copy()
    cv2.rectangle(hud_overlay, (15, 15), (320, 220), (0, 0, 0), -1)
    cv2.addWeighted(hud_overlay, 0.65, frame, 0.35, 0, frame)
    
    # Render HUD text
    cv2.putText(frame, "TRAFFIC MONITOR HUD", (25, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.line(frame, (25, 48), (310, 48), (180, 180, 180), 1)
    
    cv2.putText(frame, f"Active Vehicles: {active_vehicle_count}", (25, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    cv2.putText(frame, f"Total Logged: {len(total_tracked_vehicles)}", (25, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
    
    # Write stats breakdown
    stats_y = 130
    for name, unique_ids in vehicle_type_stats.items():
        count = len(unique_ids)
        cv2.putText(frame, f"- {name}s: {count}", (35, stats_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
        stats_y += 20

    # Write output frame
    out.write(frame)
    
    # Periodic progress prints
    frame_count += 1
    if frame_count % 30 == 0 or frame_count == total_frames:
        print(f"Processed Frame {frame_count}/{total_frames} ({(frame_count/total_frames)*100:.1f}%)")

# Clean up resources
cap.release()
out.release()

# 5. Define final statistics variables for downstream dashboard integration
total_vehicle_count = len(total_tracked_vehicles)
vehicle_type_count = {name: len(unique_ids) for name, unique_ids in vehicle_type_stats.items()}

print("Tracking completed! Re-encoding raw video to browser-native H.264 codec...")

# 6. Re-encode video file using pre-installed ffmpeg
if os.path.exists(temp_output_path):
    if os.path.exists(final_output_path):
        os.remove(final_output_path)
    
    # Re-encode to H.264 and delete raw output
    os.system(f"ffmpeg -y -i {temp_output_path} -vcodec libx264 {final_output_path} -loglevel warning")
    os.remove(temp_output_path)
    print(f"H.264 Conversion successful! Output video saved to: {final_output_path}")
else:
    print("Error: Tracking failed. The raw video could not be compiled.")
```

---

### Cell 4: Visualization & Playback Cell
Calculates and displays a text-based analytical breakdown of vehicle classifications and embeds an HTML5 video player to let you review the tracking results directly within the Google Colab interface.

```python
from IPython.display import HTML
from base64 import b64encode

# 1. Print beautifully formatted Summary Statistics
print("=" * 40)
print("       FINAL TRAFFIC ANALYSIS REPORT   ")
print("=" * 40)
print(f"Total Unique Vehicles Logged: {total_vehicle_count}")
print("-" * 40)
for name, count in vehicle_type_count.items():
    print(f"   - {name}s Detected: {count}")
print("=" * 40)

# 2. Embed the Video directly in Google Colab
if os.path.exists('output_tracked.mp4'):
    # Load and encode video
    mp4 = open('output_tracked.mp4', 'rb').read()
    data_url = "data:video/mp4;base64," + b64encode(mp4).decode()
    
    # Restrict output size for a clean look
    html_code = f"""
    <div style="text-align: center; margin-top: 10px;">
        <video width="854" height="480" controls style="border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
            <source src="{data_url}" type="video/mp4">
            Your browser does not support the video tag.
        </video>
    </div>
    """
    display(HTML(html_code))
else:
    print("Error: output_tracked.mp4 was not found. Please ensure Step 3 ran without errors.")
```

---

## 🛠️ Architecture Behind Phase 1

Understanding how these parts connect is vital for your hackathon pitch:

1. **Object Detection (YOLOv8):** 
   - YOLO (You Only Look Once) treats detection as a single regression problem. The frame is fed once into a deep convolutional neural network, yielding bounding boxes, confidence scores, and class predictions.
   - We utilize a pre-trained **YOLOv8-Nano** model, which is optimized for edge deployment, providing high frame rates (FPS) while preserving high precision for standard vehicles.
2. **Object Tracking (ByteTrack):** 
   - Traditional trackers filter out low-confidence detections. Unfortunately, this means vehicles hidden by occlusion, shadow, or weather lose their tracking IDs and register as new vehicles, corrupting count statistics.
   - **ByteTrack** solves this by utilizing *almost every* bounding box. It first matches high-confidence boxes using Kalman filters (predicting motion). For unmatched tracks, it executes a secondary match with low-confidence bounding boxes. This keeps IDs stable even when vehicles are briefly hidden or pass behind structures.

---

## 💡 Recommendations for Phase 2: Automatic Violation Detection Engine

To secure a winning slot at your hackathon, Phase 2 needs to leverage the track IDs created in Phase 1 to implement automated rule checks. Here are 5 practical violation engine blueprints:

### 1. Speed Violation Detection
* **Concept:** Implement "Virtual Speed Gates".
* **Code Implementation:** 
  Define two horizontal lines (ROIs) on the road with a known real-world physical distance (e.g., $d = 20\text{ meters}$). 
  ```python
  # Define boundary coordinates
  y_gate1, y_gate2 = 300, 500
  vehicle_timestamps = {} # {track_id: {gate1: t1, gate2: t2}}
  ```
  When a vehicle's tracking centroid crosses `y_gate1`, log the time. When it crosses `y_gate2`, calculate $\Delta t$. 
  $\text{Speed} = \frac{d}{\Delta t} \times 3.6\text{ (km/h)}$. If speed exceeds the speed limit, trigger a violation alert.

### 2. Wrong-Way Driving Detection
* **Concept:** Track flow trajectory vectors.
* **Code Implementation:**
  Store the history of centroids for each `track_id` over the last 10-15 frames.
  ```python
  trajectories = {} # {track_id: [ (x1, y1), (x2, y2), ... ]}
  ```
  Calculate the movement vector: $\Delta y = y_{\text{current}} - y_{\text{previous}}$. If vehicles in a specific lane have a positive $\Delta y$ (e.g., moving down) but a vehicle has a significant negative $\Delta y$ (e.g., moving up), flag a Wrong-Way driving violation.

### 3. Red Light Runner Detection
* **Concept:** Intersection occupancy matching.
* **Code Implementation:**
  Define a polygonal Region of Interest (ROI) corresponding to the pedestrian crossing zone or stop line using `cv2.pointPolygonTest`.
  ```python
  crossing_poly = np.array([[x1, y1], [x2, y2], [x3, y3], [x4, y4]], np.int32)
  ```
  Poll a simulated or detected traffic light state. If the light state is "RED", and a vehicle centroid enters the `crossing_poly`, instantly save the frame and flag a Red Light violation.

### 4. No-Helmet (Motorcycle) Violations
* **Concept:** Hierarchical model cascading.
* **Code Implementation:**
  Whenever the Phase 1 tracker identifies a `Motorcycle` (class ID 3), extract its bounding box crop `motorcycle_crop = frame[y1:y2, x1:x2]`.
  Feed this crop into a secondary, specialized YOLO model trained specifically on two classes: `Helmet` and `No-Helmet`. If `No-Helmet` is detected near the top region of the motorcycle bounding box, issue a safety violation.

### 5. Illegal Parking / Stopping Violations
* **Concept:** Track-ID stationary monitoring.
* **Code Implementation:**
  Define a restricted yellow zone ROI polygon.
  Maintain a frame counter or timer for each track ID residing inside the polygon.
  ```python
  # If velocity (displacement of centroid over time) is near zero for > 15 seconds:
  # Trigger 'Illegal Parking Violation'
  ```

---

Good luck with your Hackathon!
