# config.py
# Configuration settings and thresholds for the Traffic Violation Detection Engine.
# All dimensions are relative to video frame pixel coordinates.

# Video Parameters
DEFAULT_FPS = 30

# 1. Red Light Violation Configuration
# Stop line segment: ((x1, y1), (x2, y2))
# The line crossing calculation checks if a vehicle intersects this segment.
STOP_LINE_COORDINATES = ((100, 500), (1180, 500))
DEFAULT_RED_LIGHT_STATE = "RED"  # Can be "RED" or "GREEN"

# 2. Wrong Way Detection Configuration
# Specifies allowed movement direction in defined horizontal lanes.
# Lane bounds are represented by min_x and max_x.
# Allowed directions: "UP" (movement towards top of screen, decreasing y)
# or "DOWN" (movement towards bottom of screen, increasing y).
LANE_RULES = {
    "left_lane": {
        "x_range": (0, 600),
        "allowed_direction": "UP",
        "min_movement_threshold": 15.0  # Pixels of displacement required to filter noise
    },
    "right_lane": {
        "x_range": (600, 1280),
        "allowed_direction": "DOWN",
        "min_movement_threshold": 15.0
    }
}

# 3. Illegal Parking Configuration
# Polygon defining the restricted/no-parking zone: [[x1, y1], [x2, y2], [x3, y3], [x4, y4], ...]
PARKING_ZONE_POLYGON = [
    [100, 550],  # Top-left
    [450, 550],  # Top-right
    [400, 700],  # Bottom-right
    [50, 700]    # Bottom-left
]
PARKING_TIME_LIMIT_SEC = 5.0  # Time in seconds a vehicle must be stationary to flag a violation

# 4. Overspeed Detection Configuration
# Virtual speed gates (horizontal crossing lines)
# Entry Gate (Speed Gate 1) and Exit Gate (Speed Gate 2)
SPEED_GATE_1_Y = 320
SPEED_GATE_2_Y = 480
SPEED_GATES_DISTANCE_METERS = 20.0  # Real-world distance in meters between Gate 1 and Gate 2
SPEED_LIMIT_KMPH = 60.0  # Speed limit threshold
