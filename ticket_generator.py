# ticket_generator.py
# Compiles evidence data and serializes automated digital traffic tickets.
import json
import os

class TicketGenerator:
    def __init__(self):
        pass

    def generate_ticket(self, violation_id, vehicle_id, plate_number, violation_type, timestamp, 
                        confidence, evidence_images, location="Command Center Intersection Alpha", 
                        output_path="ticket.json"):
        """
        Build structural ticket parameters and save as JSON.
        Args:
            violation_id: Unique violation ID.
            vehicle_id: Tracking ID of the vehicle.
            plate_number: Recognized license plate text.
            violation_type: Type of violation (e.g. "Overspeeding").
            timestamp: ISO format violation timestamp.
            confidence: Float value of overall confidence.
            evidence_images: List of relative filepaths to evidence frames/crops.
            location: Intersection name or camera location.
            output_path: Filepath to save the ticket JSON.
        Returns:
            dict: The generated ticket dictionary.
        """
        # Formulate a clean, unique ticket identifier
        # TKT_ + Violation Details (excluding V_)
        suffix = violation_id.replace("V_", "")
        ticket_id = f"TKT_{suffix}"

        ticket_data = {
            "ticket_id": ticket_id,
            "violation_id": violation_id,
            "vehicle_id": str(vehicle_id),
            "plate_number": str(plate_number),
            "violation_type": str(violation_type),
            "timestamp": str(timestamp),
            "location": str(location),
            "confidence": round(float(confidence), 2),
            "evidence_images": [str(path) for path in evidence_images]
        }

        # Write to JSON file
        try:
            # Create directories if they do not exist
            dir_name = os.path.dirname(output_path)
            if dir_name and not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)
                
            with open(output_path, 'w') as f:
                json.dump(ticket_data, f, indent=4)
        except Exception as e:
            print(f"[Ticket Generator] Failed to write ticket file: {e}")

        return ticket_data
