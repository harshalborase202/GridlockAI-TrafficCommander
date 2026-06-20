# evidence_generator.py
# Orchestrates Phase 3 evidence compilation, layout collaging, ticketing, and database case registration.

import os
import cv2
import numpy as np
from datetime import datetime

from frame_extractor import FrameExtractor
from image_enhancer import ImageEnhancer
from anpr_ocr import ANPROCR
from ticket_generator import TicketGenerator
from evidence_manager import EvidenceManager

class EvidenceGenerator:
    def __init__(self, fps=30):
        """
        Initialize the EvidenceGenerator orchestrator.
        Args:
            fps: Video frames per second.
        """
        self.fps = fps
        self.extractor = FrameExtractor(fps)
        self.enhancer = ImageEnhancer()
        self.ocr = ANPROCR()
        self.ticket_gen = TicketGenerator()
        self.manager = EvidenceManager()
        self.padding_pct = 0.15  # Configurable padding margin to expand vehicle bounding boxes

    def add_stream_frame(self, frame_idx, frame_img):
        """
        Stream handler: forwards frame to extractor rolling buffer.
        """
        self.extractor.add_frame(frame_idx, frame_img)

    def trigger_violation_evidence(self, violation_id, violation_frame_idx, bbox):
        """
        Create a collection task when a violation is detected.
        """
        self.extractor.start_extraction_task(violation_id, violation_frame_idx, bbox)

    def update_and_process(self, current_frame_idx, current_frame_img, tracker_confidence=0.90):
        """
        Check for task completion, process evidence outputs, and register cases.
        Args:
            current_frame_idx: Frame index in the video loop.
            current_frame_img: BGR image frame.
            tracker_confidence: Confidence score of tracking step.
        Returns:
            list: List of completed ticket case dictionaries.
        """
        completed_tasks = self.extractor.update_tasks(current_frame_idx, current_frame_img)
        new_cases = []

        for task in completed_tasks:
            case_data = self._process_evidence_pipeline(task, tracker_confidence)
            if case_data:
                new_cases.append(case_data)

        return new_cases

    def _process_evidence_pipeline(self, task, tracker_confidence):
        """Runs the processing pipeline on a completed extraction task."""
        v_id = task["violation_id"]
        bbox = task["bbox"]
        frame_0 = task["frames"]["frame_0"]

        # 1. Setup Evidence Directory
        case_dir = os.path.join("evidence", v_id)
        os.makedirs(case_dir, exist_ok=True)

        # 2. Save Sequence Frames
        frame_paths = {}
        for key, img in task["frames"].items():
            path = os.path.join(case_dir, f"{key}.jpg")
            cv2.imwrite(path, img)
            frame_paths[key] = path

        # 3. Crop Vehicle with Margin
        h_f, w_f, _ = frame_0.shape
        x1, y1, x2, y2 = bbox
        bw, bh = x2 - x1, y2 - y1

        # Apply margins
        mx = int(bw * self.padding_pct)
        my = int(bh * self.padding_pct)

        cx1 = max(0, int(x1 - mx))
        cy1 = max(0, int(y1 - my))
        cx2 = min(w_f, int(x2 + mx))
        cy2 = min(h_f, int(y2 + my))

        vehicle_crop = frame_0[cy1:cy2, cx1:cx2]
        crop_path = os.path.join(case_dir, "cropped_vehicle.jpg")
        cv2.imwrite(crop_path, vehicle_crop)

        # 4. Enhance Crop
        enhanced_crop = self.enhancer.enhance(vehicle_crop)
        enhanced_path = os.path.join(case_dir, "enhanced_vehicle.jpg")
        cv2.imwrite(enhanced_path, enhanced_crop)

        # 5. Extract Plate via OCR
        plate_path = os.path.join(case_dir, "plate_crop.jpg")
        plate_number, ocr_confidence = self.ocr.process(enhanced_crop, task["violation_id"].split("_")[2], plate_path)

        # 6. Calculate Confidence Score
        # Formula: Violation (0.90 default) * 0.4 + Tracker * 0.3 + OCR * 0.3
        violation_type = self._infer_violation_type(v_id)
        violation_confidence = 0.95
        overall_confidence = (violation_confidence * 0.4) + (tracker_confidence * 0.3) + (ocr_confidence * 0.3)

        # 7. Generate Collage Summary Image
        summary_path = os.path.join(case_dir, "evidence_summary.jpg")
        self._create_collage(task["frames"], vehicle_crop, enhanced_path, plate_path, 
                              violation_type, v_id, plate_number, overall_confidence, summary_path)

        # 8. Create digital ticket
        timestamp = datetime.now().isoformat()
        evidence_images = [
            frame_paths["frame_minus2"],
            frame_paths["frame_minus1"],
            frame_paths["frame_0"],
            frame_paths["frame_plus1"],
            frame_paths["frame_plus2"],
            crop_path,
            enhanced_path,
            plate_path,
            summary_path
        ]
        
        ticket_path = os.path.join(case_dir, "ticket.json")
        ticket_data = self.ticket_gen.generate_ticket(
            violation_id=v_id,
            vehicle_id=task["violation_id"].split("_")[2],
            plate_number=plate_number,
            violation_type=violation_type,
            timestamp=timestamp,
            confidence=overall_confidence,
            evidence_images=evidence_images,
            output_path=ticket_path
        )

        # 9. Register Case in Manager Index
        self.manager.create_case(v_id, ticket_data)

        return ticket_data

    def _infer_violation_type(self, violation_id):
        """Extracts violation type string based on suffix of ID."""
        parts = violation_id.split("_")
        if len(parts) < 4:
            return "Traffic Infraction"
            
        suffix = parts[3].upper()
        if "RED" in suffix:
            return "Red Light Violation"
        elif "WRONG" in suffix:
            return "Wrong Way Driving"
        elif "ILLEGAL" in suffix or "PARK" in suffix:
            return "Illegal Parking"
        elif "OVER" in suffix or "SPEED" in suffix:
            return "Overspeeding"
        return "Traffic Violation"

    def _create_collage(self, frames, vehicle_crop, enhanced_path, plate_path, 
                        violation_type, violation_id, plate_number, confidence, output_path):
        """Compiles a single summary image collage of all evidence assets."""
        # Main Canvas dimensions: 1200 width x 500 height
        canvas_w, canvas_h = 1200, 500
        canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

        # 1. Draw Top Row: 5 sequence frames (width 240 each, height 180)
        fw, fh = 240, 180
        sequence_keys = ["frame_minus2", "frame_minus1", "frame_0", "frame_plus1", "frame_plus2"]
        for idx, key in enumerate(sequence_keys):
            frame_img = frames[key]
            resized = cv2.resize(frame_img, (fw, fh))
            x_offset = idx * fw
            canvas[0:fh, x_offset:x_offset+fw] = resized
            # Draw vertical divider line
            if idx > 0:
                cv2.line(canvas, (x_offset, 0), (x_offset, fh), (255, 255, 255), 2)
                
        # Draw horizontal divider
        cv2.line(canvas, (0, fh), (canvas_w, fh), (255, 255, 255), 2)

        # 2. Draw Bottom Row: Vehicle Crop, Plate Crop, and Text Metadata Dashboard
        # Bottom area is from y=180 to 500 (320px high)
        # Left: Vehicle Crop (resized to 380x280)
        v_resized = cv2.resize(vehicle_crop, (380, 280))
        canvas[200:480, 20:400] = v_resized
        cv2.rectangle(canvas, (20, 200), (400, 480), (150, 150, 150), 2)
        cv2.putText(canvas, "VEHICLE CROP", (25, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # Center: Enhanced Plate Crop (resized to 340x110)
        plate_img = cv2.imread(plate_path)
        if plate_img is not None:
            p_resized = cv2.resize(plate_img, (340, 110))
            canvas[285:395, 430:770] = p_resized
            cv2.rectangle(canvas, (430, 285), (770, 395), (200, 200, 200), 2)
            cv2.putText(canvas, "ANPR PLATE CROP", (435, 275), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        # Right: Dark Grey Metadata panel (from x=800 to 1180, y=200 to 480)
        px, py = 800, 200
        pw, ph = 380, 280
        cv2.rectangle(canvas, (px, py), (px + pw, py + ph), (30, 30, 30), -1)  # Fill dark grey
        cv2.rectangle(canvas, (px, py), (px + pw, py + ph), (100, 100, 100), 2) # Border

        # Print Text Data
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(canvas, "SMART EVIDENCE DOSSIER", (px + 15, py + 30), font, 0.6, (255, 255, 255), 2)
        cv2.line(canvas, (px + 15, py + 38), (px + pw - 15, py + 38), (150, 150, 150), 1)

        cv2.putText(canvas, f"Case ID: {violation_id}", (px + 15, py + 70), font, 0.45, (200, 200, 200), 1)
        cv2.putText(canvas, f"Violation: {violation_type.upper()}", (px + 15, py + 105), font, 0.5, (0, 0, 255), 2)
        cv2.putText(canvas, f"Plate No: {plate_number}", (px + 15, py + 140), font, 0.55, (255, 255, 0), 2)
        cv2.putText(canvas, f"Location: COMMAND CENTER", (px + 15, py + 175), font, 0.45, (200, 200, 200), 1)
        cv2.putText(canvas, f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", (px + 15, py + 210), font, 0.45, (200, 200, 200), 1)
        cv2.putText(canvas, f"System Conf: {round(confidence * 100, 1)}%", (px + 15, py + 250), font, 0.55, (0, 255, 0), 2)

        # Write Canvas to file
        cv2.imwrite(output_path, canvas)
