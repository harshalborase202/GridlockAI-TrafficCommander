# traffic_ai_service.py
# Production-ready AI service wrapper integrating YOLOv8, ByteTrack,
# the Phase 2 Violation Engine, and the Phase 3 Evidence Generator.

import os
import cv2

from violation_engine import ViolationEngine
from evidence_generator import EvidenceGenerator
import config

class TrafficAIService:
    def __init__(self, yolov8_model_path="yolov8n.pt", log_path="violations.json"):
        """
        Initialize the TrafficAIService.
        Args:
            yolov8_model_path: Filename/path to YOLO weights.
            log_path: Filepath where violation events are logged in JSON.
        """
        # Load YOLOv8 detection model lazily
        try:
            from ultralytics import YOLO
            self.model = YOLO(yolov8_model_path)
            self.has_yolo = True
        except ImportError:
            print("[Warning] 'ultralytics' library not found. Running TrafficAIService in fallback/headless mode.")
            self.model = None
            self.has_yolo = False
        
        # Initialize Phase 2 Violation Detection Engine
        self.violation_engine = ViolationEngine(log_path=log_path)
        
        # Initialize Phase 3 Evidence dossier generator
        self.evidence_generator = EvidenceGenerator(fps=config.DEFAULT_FPS)
        
        # Filter vehicle classes (COCO dataset: 2=Car, 3=Motorcycle, 5=Bus, 7=Truck)
        self.target_classes = [2, 3, 5, 7]

    def process_frame(self, frame, frame_idx, fps, light_state):
        """
        Executes tracking, violation checks, overlays drawing, and evidence generation on a BGR frame.
        Args:
            frame: OpenCV image frame (numpy array).
            frame_idx: Index of the current frame in the stream.
            fps: Video frames per second.
            light_state: "RED" or "GREEN" signal state.
        Returns:
            numpy.ndarray: Fully annotated frame with boxes, trackers, stop lines, and HUD.
            dict: Current violation statistics count.
            list: Any completed ticket case dictionaries generated in this frame.
        """
        # 1. Update rolling frame buffer in Evidence Generator
        self.evidence_generator.fps = fps
        self.evidence_generator.add_stream_frame(frame_idx, frame)

        # 2. Run YOLOv8 Object Detection and Tracking (ByteTrack)
        # We run track with persist=True and stream=False here because we process frame by frame
        active_tracks = []
        results = None
        
        if self.has_yolo and self.model is not None:
            results = self.model.track(
                source=frame,
                tracker="bytetrack.yaml",
                persist=True,
                classes=self.target_classes,
                verbose=False
            )
        
        # Extract tracks if detections are active
        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes
            track_ids = boxes.id.int().cpu().tolist()
            class_ids = boxes.cls.int().cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            xyxys = boxes.xyxy.cpu().tolist()
            
            for t_id, c_id, conf, bbox in zip(track_ids, class_ids, confidences, xyxys):
                active_tracks.append((t_id, c_id, conf, bbox))

        # 3. Process frame through Phase 2 Violation Detection Engine
        # Returns the annotated BGR frame and cumulative statistics
        annotated_frame, stats = self.violation_engine.process_frame(
            frame, active_tracks, frame_idx, fps, light_state
        )

        # 4. Trigger evidence generation if a violation was newly registered in this frame
        # We cross-reference the active violations logged in this frame to start frame tasks
        # We check the violation engine's internal list
        recent_violations = self.violation_engine.violations
        for v in recent_violations:
            # If the violation occurred on the current frame, trigger evidence task
            if v["frame_number"] == frame_idx:
                v_id = v["violation_id"]
                t_id = int(v["vehicle_id"])
                
                # Retrieve bounding box from violation data
                bbox = v["bbox"]
                
                # Start evidence collection task
                self.evidence_generator.trigger_violation_evidence(v_id, frame_idx, bbox)

        # 5. Advance Evidence pipeline processing (crops, enhancements, ANPR, tickets)
        # Returns case tickets completed at frame_idx (i.e. if frame_idx is T+2 seconds)
        new_cases = self.evidence_generator.update_and_process(
            current_frame_idx=frame_idx,
            current_frame_img=frame,
            tracker_confidence=0.90
        )

        return annotated_frame, stats, new_cases
