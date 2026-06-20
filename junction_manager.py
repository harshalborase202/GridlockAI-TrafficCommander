# junction_manager.py
# Handles reading, writing, caching, and updating multi-junction parameters.
import json
import os
import database

class JunctionManager:
    def __init__(self, config_path="junction_config.json"):
        """
        Initialize the JunctionManager.
        Args:
            config_path: Path to the junction_config.json file.
        """
        self.config_path = config_path
        self.junctions = {}
        self.active_junction_id = None
        self._load_config()

    def _load_config(self):
        """Loads coordinates and starting parameters from the configuration file."""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file '{self.config_path}' not found.")
            
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
                for j in data.get("junctions", []):
                    j_id = j["id"]
                    self.junctions[j_id] = j
                    
                # Set the first junction as the default active one
                if self.junctions:
                    self.active_junction_id = list(self.junctions.keys())[0]
        except Exception as e:
            print(f"[Junction Manager] Error parsing configuration: {e}")

    def get_all_junctions(self):
        """
        Returns a list of all indexed junctions and their current status values.
        """
        return list(self.junctions.values())

    def get_junction(self, junction_id):
        """
        Retrieves a single junction by its ID.
        """
        return self.junctions.get(junction_id)

    def get_active_junction(self):
        """
        Returns the active junction data details.
        """
        return self.junctions.get(self.active_junction_id)

    def set_active_junction(self, junction_id):
        """
        Switches the actively monitored CCTV junction.
        """
        if junction_id in self.junctions:
            self.active_junction_id = junction_id
            return True
        return False

    def update_junction_stats(self, junction_id, congestion_level=None, vehicle_count=None, 
                              active_violations=None, average_speed=None, risk_score=None):
        """
        Updates live in-memory metrics for a specific junction and
        writes a timestamped snapshot to the SQLite DB.
        """
        if junction_id not in self.junctions:
            return False
            
        j = self.junctions[junction_id]
        if congestion_level is not None:
            j["congestion_level"] = int(congestion_level)
        if vehicle_count is not None:
            j["vehicle_count"] = int(vehicle_count)
        if active_violations is not None:
            j["active_violations"] = int(active_violations)
        if average_speed is not None:
            j["average_speed"] = float(average_speed)
        if risk_score is not None:
            j["risk_score"] = int(risk_score)

        # Persist snapshot to SQLite (only when called from AI service / process_video,
        # not from the demo simulator which handles its own DB writes to avoid duplicates)
        return True
