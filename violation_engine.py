# violation_engine.py
# Main orchestration module that runs individual violation detection checks
# and maintains statistics and output overlays.

import os
import cv2
import numpy as np
from datetime import datetime

import database

import config
from redlight_detector import RedLightDetector
from wrongway_detector import WrongWayDetector
from parking_detector import ParkingDetector
from speed_detector import SpeedDetector

class ViolationEngine:
    def __init__(self, log_path="violations.json"):
        """
        Initialize ViolationEngine.
        Args:
            log_path: Kept for backward-compat but no longer used for storage.
                      All violations are now persisted to gridlock.db via database.py.
        """
        self.log_path = log_path  # retained for API compat, not used for writes
            
        # Instantiate detectors using geometry and thresholds from config
        self.redlight_det = RedLightDetector(config.STOP_LINE_COORDINATES)
        self.wrongway_det = WrongWayDetector(config.LANE_RULES)
        self.parking_det = ParkingDetector(config.PARKING_ZONE_POLYGON, config.PARKING_TIME_LIMIT_SEC)
        self.speed_det = SpeedDetector(
            config.SPEED_GATE_1_Y, 
            config.SPEED_GATE_2_Y, 
            config.SPEED_GATES_DISTANCE_METERS, 
            config.SPEED_LIMIT_KMPH
        )
        
        # Violation database list
        self.violations = []
        
        # Stats counters
        self.stats = {
            "total_violations": 0,
            "Red Light Violation": 0,
            "Wrong Way Driving": 0,
            "Illegal Parking": 0,
            "Overspeeding": 0
        }

    def process_frame(self, frame, tracks, frame_num, fps, current_light_state):
        """
        Process tracking results for a single frame, test violations, and draw overlays.
        Args:
            frame: OpenCV image frame (numpy array).
            tracks: List of tuples or objects representing active vehicle tracks.
                    Each track can be (track_id, class_id, conf, bbox_xyxy).
                    class_id COCO indices: 2 (car), 3 (motorcycle), 5 (bus), 7 (truck).
            frame_num: Current frame index of the video feed.
            fps: Video frames per second.
            current_light_state: "RED" or "GREEN" signal state.
        Returns:
            numpy.ndarray: Annotated image frame.
            dict: Accumulated violation statistics dictionary.
        """
        # Draw regional geometries (lines, polygons) in the background
        self._draw_geometry_overlays(frame, current_light_state)

        for track in tracks:
            # Unpack track properties dynamically to support both tuple lists and YOLO Results objects
            if hasattr(track, 'id'):  # Results Box object
                if track.id is None:
                    continue
                track_id = int(track.id.item())
                class_id = int(track.cls.item())
                conf = float(track.conf.item())
                bbox = track.xyxy[0].cpu().tolist()
            else:
                # Expecting format (track_id, class_id, conf, bbox)
                track_id, class_id, conf, bbox = track
            
            # Process only target classes: car (2), motorcycle (3), bus (5), truck (7)
            if class_id not in [2, 3, 5, 7]:
                continue
                
            # 1. Run Red Light Violation Check
            rl_event = self.redlight_det.detect(track_id, bbox, frame_num, current_light_state, conf)
            if rl_event:
                self._register_violation(rl_event)
                
            # 2. Run Wrong Way Driving Check
            ww_event = self.wrongway_det.detect(track_id, bbox, frame_num, conf)
            if ww_event:
                self._register_violation(ww_event)
                
            # 3. Run Illegal Parking Check
            pk_event = self.parking_det.detect(track_id, bbox, frame_num, fps, conf)
            if pk_event:
                self._register_violation(pk_event)
                
            # 4. Run Overspeeding Check
            sp_event = self.speed_det.detect(track_id, bbox, frame_num, fps, conf)
            if sp_event:
                self._register_violation(sp_event)
            
            # Check if this track has committed any violation in the database
            is_violating = False
            violation_label = ""
            
            for v in self.violations:
                if v["vehicle_id"] == str(track_id):
                    is_violating = True
                    # Tailor display labels based on violation type
                    if v["violation_type"] == "Overspeeding":
                        speed = v.get("extra_data", {}).get("estimated_speed_kmph", 0)
                        violation_label = f"OVERSPEEDING! {speed} km/h"
                    elif v["violation_type"] == "Red Light Violation":
                        violation_label = "RED LIGHT RUNNER!"
                    elif v["violation_type"] == "Wrong Way Driving":
                        violation_label = "WRONG WAY DRIVING!"
                    elif v["violation_type"] == "Illegal Parking":
                        violation_label = "ILLEGALLY PARKED!"
                    break
            
            x1, y1, x2, y2 = map(int, bbox)
            
            # Render Bounding Box and label overlay
            if is_violating:
                # Draw RED bounding box for violating vehicles
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                
                # Draw warning tag above bounding box
                label = f"{violation_label} (ID:{track_id})"
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.55
                thickness = 2
                text_size = cv2.getTextSize(label, font, font_scale, thickness)[0]
                
                # Prevent tag from spilling above frame boundaries
                label_y = max(y1, text_size[1] + 10)
                # Solid red tag backplate
                cv2.rectangle(frame, (x1, label_y - text_size[1] - 8), (x1 + text_size[0] + 6, label_y), (0, 0, 255), -1)
                # White warning text
                cv2.putText(frame, label, (x1 + 3, label_y - 4), font, font_scale, (255, 255, 255), thickness)
            
        # Draw dashboard HUD
        self._draw_stats_dashboard(frame)
        
        return frame, self.stats

    def _register_violation(self, violation_data):
        """Assign primary key ID, serialize timestamp, write to SQLite DB, and increment counters."""
        violation_type = violation_data["violation_type"]
        v_type_short = violation_type.split()[0].upper()
        frame_num = violation_data["frame_number"]
        vehicle_id = violation_data["vehicle_id"]
        
        # Populate standard fields
        violation_data["violation_id"] = f"V_{frame_num}_{vehicle_id}_{v_type_short}"
        violation_data["timestamp"] = datetime.now().isoformat()
        
        # Keep in-memory for overlay rendering
        self.violations.append(violation_data)
        
        # Update metrics counters
        self.stats["total_violations"] += 1
        self.stats[violation_type] += 1
        
        # Persist to SQLite (non-blocking; silently ignores duplicates via INSERT OR IGNORE)
        try:
            database.insert_violation(violation_data)
        except Exception as e:
            print(f"[ViolationEngine] DB insert error: {e}")

    def _draw_geometry_overlays(self, frame, light_state):
        """Render all detection lines and zones directly onto the image frame."""
        # 1. Stop Line
        (lx1, ly1), (lx2, ly2) = config.STOP_LINE_COORDINATES
        line_color = (0, 0, 255) if light_state == "RED" else (0, 255, 0)
        cv2.line(frame, (lx1, ly1), (lx2, ly2), line_color, 4)
        cv2.putText(frame, f"STOP LINE ({light_state})", (lx1 + 10, ly1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, line_color, 2)

        # 2. Speed Gates
        # Gate 1
        cv2.line(frame, (100, config.SPEED_GATE_1_Y), (1180, config.SPEED_GATE_1_Y), (255, 255, 0), 2)
        cv2.putText(frame, "SPEED GATE 1", (105, config.SPEED_GATE_1_Y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
        # Gate 2
        cv2.line(frame, (100, config.SPEED_GATE_2_Y), (1180, config.SPEED_GATE_2_Y), (255, 255, 0), 2)
        cv2.putText(frame, "SPEED GATE 2", (105, config.SPEED_GATE_2_Y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        # 3. Illegal Parking Zone Polygon
        poly_arr = np.array(config.PARKING_ZONE_POLYGON, dtype=np.int32)
        # Draw translucent filled overlay
        overlay = frame.copy()
        cv2.fillPoly(overlay, [poly_arr], (0, 165, 255))  # Orange fill
        cv2.addWeighted(overlay, 0.20, frame, 0.80, 0, frame)
        cv2.polylines(frame, [poly_arr], True, (0, 140, 255), 2)
        cv2.putText(frame, "NO PARKING ZONE", (poly_arr[0][0] + 5, poly_arr[0][1] + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 255), 2)

    def _draw_stats_dashboard(self, frame):
        """Render a glassmorphic dashboard HUD on the top right containing live statistics."""
        h, w, _ = frame.shape
        panel_w = 340
        panel_h = 190
        px = w - panel_w - 20
        py = 20

        # Base black backplate
        hud_bg = frame.copy()
        cv2.rectangle(hud_bg, (px, py), (px + panel_w, py + panel_h), (0, 0, 0), -1)
        cv2.addWeighted(hud_bg, 0.70, frame, 0.30, 0, frame)

        # Draw panel outline border
        cv2.rectangle(frame, (px, py), (px + panel_w, py + panel_h), (120, 120, 120), 2)

        # Dashboard Title Header
        cv2.putText(frame, "VIOLATION DETECTION SYSTEM", (px + 15, py + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.line(frame, (px + 15, py + 38), (px + panel_w - 15, py + 38), (150, 150, 150), 1)

        # Stats variables rendering
        cv2.putText(frame, f"Total Violations: {self.stats['total_violations']}", (px + 15, py + 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        
        cv2.putText(frame, f"- Red Light Violations: {self.stats['Red Light Violation']}", (px + 25, py + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(frame, f"- Wrong Way Driving: {self.stats['Wrong Way Driving']}", (px + 25, py + 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(frame, f"- Parking Violations: {self.stats['Illegal Parking']}", (px + 25, py + 140), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(frame, f"- Overspeeding: {self.stats['Overspeeding']}", (px + 25, py + 165), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
