# camera_stream.py
# Real-time per-camera worker: reads any OpenCV-compatible source
# (RTSP URL, YouTube stream URL, MP4 file on loop, webcam index),
# runs YOLOv8 + ByteTrack inference on every frame, computes speed
# from centroid displacement history, renders annotated JPEG frames,
# and exposes them for MJPEG streaming + WebSocket telemetry.

import cv2
import json
import time
import math
import threading
import numpy as np
from collections import defaultdict, deque
from datetime import datetime

# Lazy-import database to avoid circular at module load
_db = None
def _get_db():
    global _db
    if _db is None:
        import database as _db_mod
        _db = _db_mod
    return _db

# COCO class ids we track
TARGET_CLASSES = {2: "Car", 3: "Motorcycle", 5: "Bus", 7: "Truck"}

# Colour palette per class (BGR for OpenCV)
CLASS_COLOURS = {
    2: (0, 200, 255),    # cyan   — Car
    3: (50, 220, 50),    # green  — Motorcycle
    5: (180, 60, 220),   # purple — Bus
    7: (30, 140, 255),   # orange — Truck
}

VIOLATION_COLOUR = (0, 0, 255)  # red

# ─────────────────────────────────────────────────────────────────────────────
# Speed estimator
# ─────────────────────────────────────────────────────────────────────────────
class SpeedEstimator:
    """
    Estimates vehicle speed from centroid displacement between frames.
    pixel_displacement_per_frame × scale_m_per_px × fps × 3.6 = km/h
    """
    def __init__(self, fps: float, scale_m_per_px: float, history: int = 10):
        self.fps = max(fps, 1.0)
        self.scale = scale_m_per_px   # real-world metres per pixel
        self.history = history
        self._pos: dict[int, deque] = defaultdict(lambda: deque(maxlen=history))

    def update(self, track_id: int, cx: float, cy: float) -> float:
        """Push new centroid and return smoothed km/h estimate."""
        buf = self._pos[track_id]
        buf.append((cx, cy))
        if len(buf) < 2:
            return 0.0
        # Average displacement over last N frames
        dists = []
        pts = list(buf)
        for i in range(1, len(pts)):
            dx = pts[i][0] - pts[i-1][0]
            dy = pts[i][1] - pts[i-1][1]
            dists.append(math.hypot(dx, dy))
        avg_px = sum(dists) / len(dists)
        speed_kmh = avg_px * self.scale * self.fps * 3.6
        return round(speed_kmh, 1)

    def purge(self, active_ids: set):
        stale = [k for k in self._pos if k not in active_ids]
        for k in stale:
            del self._pos[k]


# ─────────────────────────────────────────────────────────────────────────────
# HUD drawing helpers
# ─────────────────────────────────────────────────────────────────────────────
def _draw_box(frame, x1, y1, x2, y2, track_id, label, speed_kmh,
              speed_limit, colour):
    """Draw filled-header bounding box on frame."""
    is_over = speed_kmh > speed_limit and speed_kmh > 5
    box_col = VIOLATION_COLOUR if is_over else colour

    # Box
    cv2.rectangle(frame, (x1, y1), (x2, y2), box_col, 2)

    # Header pill
    header_text = f"#{track_id} {label}  {speed_kmh} km/h"
    if is_over:
        header_text += " !"
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.45
    (tw, th), _ = cv2.getTextSize(header_text, font, fs, 1)
    pill_y = max(y1 - 20, th + 4)
    cv2.rectangle(frame, (x1, pill_y - th - 4), (x1 + tw + 6, pill_y + 2), box_col, -1)
    cv2.putText(frame, header_text, (x1 + 3, pill_y - 2), font, fs, (255, 255, 255), 1)


def _draw_hud_overlay(frame, cam_name, vehicle_count, ts):
    """Top-left HUD bar."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 32), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, f"GRIDLOCK AI  |  {cam_name}  |  {vehicle_count} vehicles  |  {ts}",
                (8, 20), font, 0.48, (0, 220, 255), 1)

    # REC indicator (blinks)
    sec = int(time.time()) % 2
    if sec == 0:
        cv2.circle(frame, (w - 18, 16), 6, (0, 0, 255), -1)
    cv2.putText(frame, "REC", (w - 50, 20), font, 0.4, (0, 0, 255), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Per-camera worker thread
# ─────────────────────────────────────────────────────────────────────────────
class CameraStream:
    """
    Reads a video source in a background thread, runs YOLO+ByteTrack,
    and exposes the latest annotated JPEG frame + telemetry dict.

    Thread-safe reads: latest_frame (bytes), latest_telemetry (list[dict])
    """

    def __init__(self, cam_config: dict, model=None):
        self.cam_id        = cam_config["id"]
        self.junction_id   = cam_config.get("junction_id", self.cam_id)
        self.name          = cam_config["name"]
        self.source        = cam_config["source"]
        self.speed_limit   = cam_config.get("speed_limit_kmph", 60)
        self.scale         = cam_config.get("scale_meters_per_pixel", 0.08)
        self.coords        = cam_config.get("coords", "")
        self.model         = model  # shared YOLO model (or None → headless)

        self.latest_frame: bytes = b""          # JPEG bytes of latest annotated frame
        self.latest_telemetry: list  = []       # list of vehicle dicts
        self._lock = threading.Lock()

        self._running = False
        self._thread: threading.Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[CameraStream:{self.cam_id}] Started: source={self.source}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print(f"[CameraStream:{self.cam_id}] Stopped.")

    def get_frame(self) -> bytes:
        with self._lock:
            return self.latest_frame

    def get_telemetry(self) -> list:
        with self._lock:
            return list(self.latest_telemetry)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _open_capture(self):
        """Open the video source with automatic fallback chain."""
        src = self.source

        # Try to get real stream URL via yt-dlp for YouTube/RTSP
        if "youtube.com" in src or "youtu.be" in src:
            try:
                import subprocess
                result = subprocess.run(
                    ["yt-dlp", "-f", "best[ext=mp4]/best", "-g", src],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    src = result.stdout.strip().split("\n")[0]
                    print(f"[CameraStream:{self.cam_id}] yt-dlp resolved: {src[:80]}...")
            except Exception as e:
                print(f"[CameraStream:{self.cam_id}] yt-dlp failed: {e}")

        cap = cv2.VideoCapture(src)
        if cap.isOpened():
            return cap, src

        # Fallback: webcam
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            print(f"[CameraStream:{self.cam_id}] Using webcam (source unavailable: {self.source})")
            return cap, "webcam:0"

        print(f"[CameraStream:{self.cam_id}] ERROR: No video source available.")
        return None, None

    def _loop(self):
        cap, resolved_src = self._open_capture()
        if cap is None:
            self._generate_fallback_frames()
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        speed_est = SpeedEstimator(fps=fps, scale_m_per_px=self.scale)
        target_classes = list(TARGET_CLASSES.keys())

        frame_idx = 0
        prev_time = time.time()

        while self._running:
            ret, frame = cap.read()
            if not ret:
                # Loop video file
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret:
                    break

            # Throttle to ~15 fps for streaming efficiency
            now = time.time()
            elapsed = now - prev_time
            if elapsed < 0.066:   # ~15 fps
                time.sleep(0.066 - elapsed)
            prev_time = time.time()

            # ── YOLO + ByteTrack ─────────────────────────────────────────
            tracks = []
            if self.model is not None:
                try:
                    results = self.model.track(
                        source=frame,
                        tracker="bytetrack.yaml",
                        persist=True,
                        classes=target_classes,
                        verbose=False,
                        imgsz=640,
                    )
                    if (results and results[0].boxes is not None
                            and results[0].boxes.id is not None):
                        boxes = results[0].boxes
                        for tid, cls, conf, xyxy in zip(
                            boxes.id.int().cpu().tolist(),
                            boxes.cls.int().cpu().tolist(),
                            boxes.conf.cpu().tolist(),
                            boxes.xyxy.cpu().tolist(),
                        ):
                            tracks.append((int(tid), int(cls), float(conf), xyxy))
                except Exception as e:
                    print(f"[CameraStream:{self.cam_id}] YOLO error: {e}")

            # ── Annotate frame ───────────────────────────────────────────
            annotated = frame.copy()
            telemetry = []
            active_ids = set()

            for tid, cls_id, conf, bbox in tracks:
                x1, y1, x2, y2 = map(int, bbox)
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                speed_kmh = speed_est.update(tid, cx, cy)
                active_ids.add(tid)

                label     = TARGET_CLASSES.get(cls_id, "Vehicle")
                colour    = CLASS_COLOURS.get(cls_id, (200, 200, 200))
                is_over   = speed_kmh > self.speed_limit and speed_kmh > 5
                direction = "NORTHBOUND" if cy < annotated.shape[0] / 2 else "SOUTHBOUND"

                _draw_box(annotated, x1, y1, x2, y2,
                          tid, label, speed_kmh, self.speed_limit, colour)

                telemetry.append({
                    "track_id":   tid,
                    "class_label": label,
                    "speed_kmph": speed_kmh,
                    "direction":  direction,
                    "confidence": round(conf, 2),
                    "bbox":       [x1, y1, x2, y2],
                    "is_violating": is_over,
                    "violation_text": "OVERSPEEDING!" if is_over else "",
                })

            speed_est.purge(active_ids)

            # ── Write to DB (throttled: once per 30 frames ≈ every 2s at 15fps) ───
            if frame_idx % 30 == 0 and telemetry:
                db = _get_db()
                # 1. Upsert each tracked vehicle
                for v in telemetry:
                    db.upsert_vehicle(
                        vehicle_id=str(v["track_id"]),
                        camera_id=self.cam_id,
                        v_type=v["class_label"],
                        speed_kmh=v["speed_kmph"],
                        direction=v["direction"],
                        plate_text="",
                    )
                # 2. Congestion snapshot: pct = vehicles / assumed max capacity (20)
                speeds = [v["speed_kmph"] for v in telemetry if v["speed_kmph"] > 0]
                avg_spd = round(sum(speeds) / len(speeds), 1) if speeds else 0.0
                cong_pct = round(min(100.0, len(telemetry) / 20.0 * 100.0), 1)
                db.insert_congestion_snapshot(
                    camera_id=self.cam_id,
                    vehicle_count=len(telemetry),
                    avg_speed=avg_spd,
                    congestion_pct=cong_pct,
                )

            # HUD
            ts = datetime.now().strftime("%H:%M:%S")
            _draw_hud_overlay(annotated, self.name, len(tracks), ts)

            # Encode JPEG
            ok, jpeg = cv2.imencode(".jpg", annotated,
                                    [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                with self._lock:
                    self.latest_frame = jpeg.tobytes()
                    self.latest_telemetry = telemetry

            frame_idx += 1

        cap.release()
        print(f"[CameraStream:{self.cam_id}] Capture loop exited.")

    def _generate_fallback_frames(self):
        """
        If no video source is available at all, generate informational frames
        so the stream endpoint always returns *something* rather than stalling.
        """
        print(f"[CameraStream:{self.cam_id}] Generating placeholder frames (no source).")
        w, h = 854, 480
        while self._running:
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (15, 15, 25)

            # Grid lines
            for gx in range(0, w, 80):
                cv2.line(frame, (gx, 0), (gx, h), (30, 30, 50), 1)
            for gy in range(0, h, 60):
                cv2.line(frame, (0, gy), (w, gy), (30, 30, 50), 1)

            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(frame, "GRIDLOCK AI", (w//2 - 120, h//2 - 40),
                        font, 1.2, (0, 200, 255), 2)
            cv2.putText(frame, f"{self.name}", (w//2 - 140, h//2),
                        font, 0.7, (180, 180, 180), 1)
            cv2.putText(frame, "Awaiting camera source...", (w//2 - 130, h//2 + 35),
                        font, 0.55, (100, 100, 100), 1)

            ts = datetime.now().strftime("%H:%M:%S")
            cv2.putText(frame, ts, (10, 25), font, 0.55, (0, 200, 255), 1)

            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                with self._lock:
                    self.latest_frame = jpeg.tobytes()
                    self.latest_telemetry = []

            time.sleep(0.1)


# ─────────────────────────────────────────────────────────────────────────────
# Camera manager — owns all CameraStream instances
# ─────────────────────────────────────────────────────────────────────────────
class CameraManager:
    def __init__(self, cameras_json_path: str = "cameras.json"):
        self._streams: dict[str, CameraStream] = {}
        self._load(cameras_json_path)

    def _load(self, path: str):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[CameraManager] Failed to load {path}: {e}")
            return

        # Try to load shared YOLO model once
        model = None
        try:
            from ultralytics import YOLO
            model = YOLO("yolov8n.pt")
            print("[CameraManager] YOLOv8n model loaded successfully.")
        except Exception as e:
            print(f"[CameraManager] YOLO unavailable ({e}) — streaming without inference.")

        for cam in data.get("cameras", []):
            stream = CameraStream(cam, model=model)
            self._streams[cam["id"]] = stream

        print(f"[CameraManager] Loaded {len(self._streams)} camera(s).")

    def start_all(self):
        for s in self._streams.values():
            s.start()

    def stop_all(self):
        for s in self._streams.values():
            s.stop()

    def get_stream(self, cam_id: str) -> CameraStream | None:
        return self._streams.get(cam_id)

    def get_stream_by_junction(self, junction_id: str) -> CameraStream | None:
        for s in self._streams.values():
            if s.junction_id == junction_id:
                return s
        return None

    def list_cameras(self) -> list:
        return [
            {
                "id":           s.cam_id,
                "junction_id":  s.junction_id,
                "name":         s.name,
                "source":       s.source,
                "speed_limit":  s.speed_limit,
                "coords":       s.coords,
            }
            for s in self._streams.values()
        ]
