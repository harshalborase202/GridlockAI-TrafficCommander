# evidence_manager.py
# Case management module to index, store, load, and query violation ticket cases.
import json
import os

class EvidenceManager:
    def __init__(self, index_path="evidence/case_index.json"):
        """
        Initialize the EvidenceManager.
        Args:
            index_path: Filepath where the central cases index list is stored.
        """
        self.index_path = index_path
        self._initialize_index()

    def _initialize_index(self):
        """Creates the index file if not present."""
        dir_name = os.path.dirname(self.index_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
            
        if not os.path.exists(self.index_path):
            with open(self.index_path, 'w') as f:
                json.dump([], f, indent=4)

    def _load_index(self):
        """Loads and returns all indexed cases."""
        try:
            if os.path.exists(self.index_path):
                with open(self.index_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Evidence Manager] Failed to load index: {e}")
        return []

    def _save_index(self, index_data):
        """Saves the index data back to disk."""
        try:
            with open(self.index_path, 'w') as f:
                json.dump(index_data, f, indent=4)
        except Exception as e:
            print(f"[Evidence Manager] Failed to save index: {e}")

    def create_case(self, violation_id, ticket_data):
        """
        Register a new ticket case inside the central index.
        Args:
            violation_id: Unique violation ID.
            ticket_data: Ticket details dictionary.
        """
        index_data = self._load_index()
        
        # Check if case is already registered
        exists = False
        for idx, case in enumerate(index_data):
            if case["violation_id"] == violation_id:
                index_data[idx] = ticket_data  # Update case details
                exists = True
                break

        if not exists:
            index_data.append(ticket_data)

        self._save_index(index_data)

    def load_case(self, violation_id):
        """
        Loads case ticket details for a given violation ID.
        Args:
            violation_id: Unique violation ID.
        Returns:
            dict: Ticket details if found, else None.
        """
        # First attempt search through the central index
        index_data = self._load_index()
        for case in index_data:
            if case["violation_id"] == violation_id:
                return case

        # Fallback: Check directory filesystem direct read
        ticket_file_path = os.path.join("evidence", violation_id, "ticket.json")
        if os.path.exists(ticket_file_path):
            try:
                with open(ticket_file_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Evidence Manager] Failed to read ticket fallback file: {e}")
        
        return None

    def get_case_by_plate(self, plate_number):
        """
        Query the database index for cases matching a license plate.
        Args:
            plate_number: License plate string.
        Returns:
            list: List of matching case tickets.
        """
        index_data = self._load_index()
        target_plate = plate_number.replace(" ", "").upper()
        
        matches = []
        for case in index_data:
            cleaned_case_plate = case.get("plate_number", "").replace(" ", "").upper()
            if cleaned_case_plate == target_plate:
                matches.append(case)
                
        return matches

    def get_case_by_violation_type(self, violation_type):
        """
        Query the database index for cases matching an infraction category.
        Args:
            violation_type: Category name (e.g. "Wrong Way Driving").
        Returns:
            list: List of matching case tickets.
        """
        index_data = self._load_index()
        target_type = violation_type.lower().strip()
        
        matches = []
        for case in index_data:
            if case.get("violation_type", "").lower().strip() == target_type:
                matches.append(case)
                
        return matches
