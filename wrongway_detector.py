# wrongway_detector.py
# Tracks centroid motion vectors to detect vehicles driving against the lane flow.

class WrongWayDetector:
    def __init__(self, lane_rules):
        """
        Initialize WrongWayDetector.
        Args:
            lane_rules: Dict of lane definitions containing x ranges and allowed directions from config.py.
        """
        self.lane_rules = lane_rules
        self.centroid_history = {}  # Stores centroids over time: {track_id: [(cx, cy), ...]}
        self.violated_tracks = set()  # Remembers track IDs that have already violated
        self.history_limit = 15  # Number of frames to check for displacement vector calculation

    def detect(self, track_id, bbox, frame_num, confidence):
        """
        Check if the vehicle is driving in the wrong direction.
        Args:
            track_id: Unique track ID of the vehicle.
            bbox: Bounding box [x1, y1, x2, y2].
            frame_num: Current frame number.
            confidence: Confidence score of the detection.
        Returns:
            dict: Violation event details if a violation occurred, else None.
        """
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)
        curr_centroid = (cx, cy)

        # Update centroid history list
        if track_id not in self.centroid_history:
            self.centroid_history[track_id] = []
        self.centroid_history[track_id].append(curr_centroid)

        # Limit history buffer length to keep memory bounded
        if len(self.centroid_history[track_id]) > self.history_limit:
            self.centroid_history[track_id].pop(0)

        # Skip checking if we have already flagged this vehicle or have insufficient history
        if track_id in self.violated_tracks:
            return None

        if len(self.centroid_history[track_id]) < self.history_limit:
            return None

        # Calculate displacement vector over the history window
        start_centroid = self.centroid_history[track_id][0]
        dy = curr_centroid[1] - start_centroid[1]  # vertical movement (positive means going down)
        
        # Identify applicable lane rule based on current centroid x-coordinate
        applicable_rule = None
        for lane_name, rule in self.lane_rules.items():
            min_x, max_x = rule["x_range"]
            if min_x <= cx <= max_x:
                applicable_rule = rule
                break

        if applicable_rule is None:
            return None

        allowed = applicable_rule["allowed_direction"]
        threshold = applicable_rule["min_movement_threshold"]

        violation_event = None

        # Check for violation
        if allowed == "UP":
            # Allowed is UP (decreasing y, i.e., dy should be negative).
            # If dy is positive and exceeds noise threshold, it is going DOWN (wrong way).
            if dy > threshold:
                self.violated_tracks.add(track_id)
                violation_event = {
                    "vehicle_id": str(track_id),
                    "violation_type": "Wrong Way Driving",
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "confidence": float(confidence),
                    "frame_number": int(frame_num)
                }
        elif allowed == "DOWN":
            # Allowed is DOWN (increasing y, i.e., dy should be positive).
            # If dy is negative and absolute displacement exceeds threshold, it is going UP (wrong way).
            if dy < -threshold:
                self.violated_tracks.add(track_id)
                violation_event = {
                    "vehicle_id": str(track_id),
                    "violation_type": "Wrong Way Driving",
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "confidence": float(confidence),
                    "frame_number": int(frame_num)
                }

        return violation_event
