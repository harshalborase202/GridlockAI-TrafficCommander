# redlight_detector.py
# Detects vehicles that cross the stop line when the traffic light state is RED.

class RedLightDetector:
    def __init__(self, stop_line_coords):
        """
        Initialize RedLightDetector.
        Args:
            stop_line_coords: Tuple of two points ((x1, y1), (x2, y2)) representing the stop line segment.
        """
        self.stop_line_coords = stop_line_coords
        self.violated_tracks = set()  # Remembers track IDs that have already violated to prevent double-logging
        self.centroid_history = {}  # Stores previous centroids: {track_id: (cx, cy)}

    def _ccw(self, A, B, C):
        """Check if points A, B, C are in counter-clockwise order."""
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

    def _intersect(self, A, B, C, D):
        """Return True if line segment AB intersects line segment CD."""
        return self._ccw(A, C, D) != self._ccw(B, C, D) and self._ccw(A, B, C) != self._ccw(A, B, D)

    def detect(self, track_id, bbox, frame_num, current_light_state, confidence):
        """
        Check if the vehicle crossed the stop line during a Red light.
        Args:
            track_id: Unique track ID of the vehicle.
            bbox: Bounding box [x1, y1, x2, y2].
            frame_num: Current frame number.
            current_light_state: "RED" or "GREEN".
            confidence: Confidence score of the detection.
        Returns:
            dict: Violation event details if a violation occurred, else None.
        """
        # Calculate centroid of the bounding box
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)
        curr_centroid = (cx, cy)

        violation_event = None

        # If already flagged, just update the tracker state history and exit
        if track_id in self.violated_tracks:
            self.centroid_history[track_id] = curr_centroid
            return None

        # Check crossing if we have historical trace
        if track_id in self.centroid_history:
            prev_centroid = self.centroid_history[track_id]
            line_a, line_b = self.stop_line_coords

            # Check if trajectory intersects stop line segment
            if self._intersect(prev_centroid, curr_centroid, line_a, line_b):
                # Ensure the crossing direction is moving forward (y coordinate increasing)
                # and the traffic light is RED at that moment
                if current_light_state == "RED" and curr_centroid[1] > prev_centroid[1]:
                    self.violated_tracks.add(track_id)
                    violation_event = {
                        "vehicle_id": str(track_id),
                        "violation_type": "Red Light Violation",
                        "bbox": [int(x1), int(y1), int(x2), int(y2)],
                        "confidence": float(confidence),
                        "frame_number": int(frame_num)
                    }

        # Keep history updated
        self.centroid_history[track_id] = curr_centroid
        return violation_event
