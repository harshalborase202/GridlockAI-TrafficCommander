# speed_detector.py
# Estimates vehicle speeds using two virtual horizontal speed gates and logs overspeeding violations.

class SpeedDetector:
    def __init__(self, gate_1_y, gate_2_y, distance_meters, speed_limit_kmph):
        """
        Initialize SpeedDetector.
        Args:
            gate_1_y: Y-coordinate of the first speed gate line.
            gate_2_y: Y-coordinate of the second speed gate line.
            distance_meters: Real-world distance (meters) between the two gates.
            speed_limit_kmph: Speed limit threshold in km/h.
        """
        self.gate_1_y = gate_1_y
        self.gate_2_y = gate_2_y
        self.distance_meters = distance_meters
        self.speed_limit_kmph = speed_limit_kmph

        self.gate1_crossings = {}  # Track ID -> frame number when crossing gate 1
        self.gate2_crossings = {}  # Track ID -> frame number when crossing gate 2
        self.violated_tracks = set()  # Track IDs that already violated the speed limit
        self.centroid_history = {}  # Track ID -> previous centroid (cx, cy)

    def detect(self, track_id, bbox, frame_num, fps, confidence):
        """
        Estimate speed and detect overspeed violations.
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

        violation_event = None

        # Check if we have tracking history to determine line crossings
        if track_id in self.centroid_history:
            prev_centroid = self.centroid_history[track_id]
            prev_y = prev_centroid[1]
            curr_y = curr_centroid[1]

            # 1. Check crossing of Gate 1 (line y = gate_1_y)
            # Sign of displacement changes if they crossed the line
            crossed_gate1 = (prev_y - self.gate_1_y) * (curr_y - self.gate_1_y) <= 0

            if crossed_gate1:
                # If moving forward (downwards, Gate 1 -> Gate 2), Gate 1 is ENTRY.
                # If we haven't logged Gate 1 entry yet and haven't logged Gate 2 crossing:
                if track_id not in self.gate1_crossings and track_id not in self.gate2_crossings:
                    self.gate1_crossings[track_id] = frame_num
                
                # If moving in reverse (upwards, Gate 2 -> Gate 1), Gate 1 is EXIT.
                # Check if Gate 2 was already crossed
                elif track_id in self.gate2_crossings and track_id not in self.gate1_crossings:
                    self.gate1_crossings[track_id] = frame_num
                    violation_event = self._calculate_and_check_speed(
                        track_id, self.gate2_crossings[track_id], frame_num, fps, bbox, confidence
                    )

            # 2. Check crossing of Gate 2 (line y = gate_2_y)
            crossed_gate2 = (prev_y - self.gate_2_y) * (curr_y - self.gate_2_y) <= 0

            if crossed_gate2:
                # If moving in reverse (upwards, Gate 2 -> Gate 1), Gate 2 is ENTRY.
                if track_id not in self.gate2_crossings and track_id not in self.gate1_crossings:
                    self.gate2_crossings[track_id] = frame_num
                
                # If moving forward (downwards, Gate 1 -> Gate 2), Gate 2 is EXIT.
                # Check if Gate 1 was already crossed
                elif track_id in self.gate1_crossings and track_id not in self.gate2_crossings:
                    self.gate2_crossings[track_id] = frame_num
                    violation_event = self._calculate_and_check_speed(
                        track_id, self.gate1_crossings[track_id], frame_num, fps, bbox, confidence
                    )

        # Update centroid history
        self.centroid_history[track_id] = curr_centroid
        return violation_event

    def _calculate_and_check_speed(self, track_id, entry_frame, exit_frame, fps, bbox, confidence):
        """Helper to calculate velocity and construct violation structure."""
        if track_id in self.violated_tracks:
            return None

        # Calculate time difference in seconds
        frame_delta = abs(exit_frame - entry_frame)
        if frame_delta == 0:
            return None

        time_delta_sec = frame_delta / fps
        
        # Speed = Distance / Time
        speed_mps = self.distance_meters / time_delta_sec
        speed_kmph = speed_mps * 3.6

        # Check if speed exceeds limit
        if speed_kmph > self.speed_limit_kmph:
            self.violated_tracks.add(track_id)
            x1, y1, x2, y2 = bbox
            return {
                "vehicle_id": str(track_id),
                "violation_type": "Overspeeding",
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "confidence": float(confidence),
                "frame_number": int(exit_frame),
                "extra_data": {
                    "estimated_speed_kmph": round(speed_kmph, 1),
                    "speed_limit_kmph": self.speed_limit_kmph
                }
            }
        
        return None
