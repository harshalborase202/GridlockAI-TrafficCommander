# parking_detector.py
# Detects vehicles parked/stopped illegally inside a designated polygonal zone.
import cv2
import numpy as np
import math

class ParkingDetector:
    def __init__(self, parking_polygon, parking_time_limit_sec):
        """
        Initialize ParkingDetector.
        Args:
            parking_polygon: List of points [[x1, y1], [x2, y2], ...] defining the restricted zone.
            parking_time_limit_sec: Max allowed stopping time before violation.
        """
        # Convert list of coordinate points to a numpy array for cv2 polygon checks
        self.polygon = np.array(parking_polygon, dtype=np.int32)
        self.parking_time_limit_sec = parking_time_limit_sec
        self.violated_tracks = set()  # Track IDs that already violated this rule
        
        # Keeps track of stationary timers: 
        # {track_id: {"stationary_start_frame": frame_num, "last_centroid": (cx, cy)}}
        self.parking_status = {}
        self.stationary_distance_threshold = 3.0  # Pixels of movement allowed to still be considered "stationary"

    def detect(self, track_id, bbox, frame_num, fps, confidence):
        """
        Check if the vehicle is illegally parked.
        Args:
            track_id: Unique track ID of the vehicle.
            bbox: Bounding box [x1, y1, x2, y2].
            frame_num: Current frame number.
            fps: Video frames per second.
            confidence: Confidence score of the detection.
        Returns:
            dict: Violation event details if a violation occurred, else None.
        """
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)
        curr_centroid = (cx, cy)

        # Check if the centroid is inside the polygonal zone
        # cv2.pointPolygonTest returns positive values for inside, 0 for boundary, negative for outside.
        is_inside = cv2.pointPolygonTest(self.polygon, (float(cx), float(cy)), False) >= 0

        violation_event = None

        if is_inside:
            if track_id not in self.parking_status:
                # Vehicle just entered or tracking started. Initialize stationary check.
                self.parking_status[track_id] = {
                    "stationary_start_frame": frame_num,
                    "last_centroid": curr_centroid
                }
            else:
                # Retrieve previous state
                status = self.parking_status[track_id]
                prev_centroid = status["last_centroid"]
                
                # Calculate movement distance between frames
                dist = math.sqrt((curr_centroid[0] - prev_centroid[0])**2 + (curr_centroid[1] - prev_centroid[1])**2)

                if dist < self.stationary_distance_threshold:
                    # Vehicle has not moved significantly (is stationary).
                    # Calculate how long it has been stationary
                    stationary_frames = frame_num - status["stationary_start_frame"]
                    stationary_duration_sec = stationary_frames / fps
                    
                    if stationary_duration_sec >= self.parking_time_limit_sec:
                        if track_id not in self.violated_tracks:
                            self.violated_tracks.add(track_id)
                            violation_event = {
                                "vehicle_id": str(track_id),
                                "violation_type": "Illegal Parking",
                                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                                "confidence": float(confidence),
                                "frame_number": int(frame_num)
                            }
                else:
                    # Vehicle is moving. Reset the stationary timer to current frame and update position.
                    self.parking_status[track_id] = {
                        "stationary_start_frame": frame_num,
                        "last_centroid": curr_centroid
                    }
        else:
            # If the vehicle leaves the polygon, clear it from active monitoring
            if track_id in self.parking_status:
                del self.parking_status[track_id]

        return violation_event
