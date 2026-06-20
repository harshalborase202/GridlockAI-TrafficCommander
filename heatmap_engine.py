# heatmap_engine.py
# Generates Leaflet-compatible heatmap coordinate data with varying intensity maps.
import random

class HeatmapEngine:
    def __init__(self, junction_manager):
        """
        Initialize the HeatmapEngine.
        Args:
            junction_manager: Instance of JunctionManager to poll live metrics.
        """
        self.manager = junction_manager

    def get_heatmap_data(self, heatmap_type="density"):
        """
        Generate coordinate arrays: [[lat, lng, intensity], ...]
        Args:
            heatmap_type: Can be "density", "violations", or "risk".
        """
        junctions = self.manager.get_all_junctions()
        heatmap_points = []

        for j in junctions:
            lat = j["lat"]
            lng = j["lng"]

            # 1. Determine baseline intensity based on type
            if heatmap_type == "violations":
                # Scale active violations (e.g. 5 active violations = 1.0 intensity max)
                intensity = min(1.0, float(j["active_violations"]) / 5.0)
            elif heatmap_type == "risk":
                # Scale risk score (0 to 100 -> 0.0 to 1.0)
                intensity = float(j["risk_score"]) / 100.0
            else:  # default to "density"
                # Scale congestion level (0 to 100 -> 0.0 to 1.0)
                intensity = float(j["congestion_level"]) / 100.0

            # 2. Add the primary central junction point
            heatmap_points.append([lat, lng, intensity])

            # 3. Synthesize a radius dispersion cluster surrounding the junction.
            # This creates a visually impressive gradient blob on Leaflet maps.
            # We generate 5 offset points with slightly decaying intensity.
            offsets = [
                (0.0006, 0.0006),
                (-0.0006, -0.0006),
                (0.0006, -0.0006),
                (-0.0006, 0.0006),
                (0.0, 0.0009),
                (0.0009, 0.0)
            ]
            
            for d_lat, d_lng in offsets:
                # Add slight random wiggles to keep the dashboard map feeling "alive"
                wiggle_lat = d_lat + random.uniform(-0.0001, 0.0001)
                wiggle_lng = d_lng + random.uniform(-0.0001, 0.0001)
                
                # Decayed intensity for outer blobs (between 60% and 80% of center)
                outer_intensity = intensity * random.uniform(0.6, 0.8)
                
                heatmap_points.append([
                    lat + wiggle_lat,
                    lng + wiggle_lng,
                    round(outer_intensity, 3)
                ])

        return heatmap_points
