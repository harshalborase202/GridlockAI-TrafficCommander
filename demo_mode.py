# demo_mode.py
# Drives realistic live data into the SQLite DB for hackathon demo.
# Simulates vehicle counts, congestion swings, violation events, and alerts -
# but ALL state is now persisted to gridlock.db, never to JSON files.

import time
import random
import threading
import os
import json
import cv2
import numpy as np
from datetime import datetime

import database
from analytics_engine import AnalyticsEngine
from congestion_predictor import CongestionPredictor


class DemoSimulator:
    def __init__(self, junction_manager, log_path="violations.json"):
        """
        Initialize the DemoSimulator.
        Args:
            junction_manager: Instance of JunctionManager.
            log_path: Retained for backward-compat; not used for storage anymore.
        """
        self.manager = junction_manager
        self.log_path = log_path
        self.analytics = AnalyticsEngine()
        self.predictor = CongestionPredictor()
        self.is_running = False
        self.thread = None
        database.init_db()

    def start(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[Demo Simulator] Background simulation started -- writing to gridlock.db")

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join()
        print("[Demo Simulator] Background simulation stopped.")

    def get_recent_alerts(self):
        return database.query_recent_alerts(10)

    def _run_loop(self):
        frame_idx = 100
        mock_track_counter = 500

        while self.is_running:
            try:
                junctions = self.manager.get_all_junctions()

                for j in junctions:
                    j_id = j["id"]
                    delta_count = random.randint(-5, 5)
                    new_count = max(10, min(300, j["vehicle_count"] + delta_count))

                    if j_id == "silk_board_junction":
                        new_congestion = max(75, min(99, int(new_count * 0.45)))
                        new_speed = max(8.0, min(22.0, 35.0 - (new_congestion * 0.25)))
                    elif j_id == "koramangala_3rd_block":
                        new_congestion = max(15, min(45, int(new_count * 0.45)))
                        new_speed = max(35.0, min(52.0, 60.0 - (new_congestion * 0.5)))
                    else:
                        new_congestion = max(35, min(70, int(new_count * 0.45)))
                        new_speed = max(25.0, min(42.0, 50.0 - (new_congestion * 0.35)))

                    self.predictor.add_history_point(j_id, new_congestion)
                    risk_info = self.analytics.calculate_risk_score(
                        new_congestion, j["active_violations"], new_speed
                    )

                    self.manager.update_junction_stats(
                        junction_id=j_id,
                        congestion_level=new_congestion,
                        vehicle_count=new_count,
                        average_speed=round(new_speed, 1),
                        risk_score=risk_info["risk_score"]
                    )

                    database.upsert_junction_stats(
                        junction_id=j_id,
                        junction_name=j["name"],
                        congestion_level=new_congestion,
                        vehicle_count=new_count,
                        active_violations=j["active_violations"],
                        average_speed=round(new_speed, 1),
                        risk_score=risk_info["risk_score"]
                    )

                    cam_id_map = {
                        "silk_board_junction":    "cam_12",
                        "koramangala_3rd_block":  "cam_13",
                        "indiranagar_100ft_road": "cam_14",
                    }
                    cam_id = cam_id_map.get(j_id, j_id)

                    database.insert_congestion_snapshot(
                        camera_id=cam_id,
                        vehicle_count=new_count,
                        avg_speed=round(new_speed, 1),
                        congestion_pct=float(new_congestion),
                    )

                    v_types = ["Car", "Motorcycle", "Bus", "Truck"]
                    directions = ["N", "S", "E", "W"]
                    for track_offset in range(min(5, new_count)):
                        vid = f"demo_{cam_id}_{(mock_track_counter + track_offset) % 200}"
                        database.upsert_vehicle(
                            vehicle_id=vid,
                            camera_id=cam_id,
                            v_type=random.choice(v_types),
                            speed_kmh=round(new_speed + random.uniform(-5, 5), 1),
                            direction=random.choice(directions),
                            plate_text="",
                        )

                if random.random() < 0.15:
                    target_junction = random.choice(junctions)
                    mock_track_counter += 1
                    frame_idx += random.randint(15, 60)
                    self._generate_simulated_violation(target_junction, mock_track_counter, frame_idx)

                if random.random() < 0.10:
                    self._generate_simulated_alert()

            except Exception as e:
                print(f"[Demo Simulator] Loop error: {e}")

            time.sleep(3)

    # =========================================================================
    # CCTV RENDERING HELPERS
    # =========================================================================

    def _apply_cctv_overlay(self, img, cam_name, timestamp_str, frame_label=""):
        """Apply professional CCTV-style HUD overlay to any frame."""
        h, w = img.shape[:2]

        # Subtle scanline texture
        overlay = img.copy()
        for y in range(0, h, 4):
            cv2.line(overlay, (0, y), (w, y), (0, 0, 0), 1)
        img = cv2.addWeighted(img, 0.92, overlay, 0.08, 0)

        # Top HUD bar
        bar_overlay = img.copy()
        cv2.rectangle(bar_overlay, (0, 0), (w, 28), (0, 0, 0), -1)
        img = cv2.addWeighted(img, 0.6, bar_overlay, 0.4, 0)

        cv2.putText(img, cam_name, (8, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 230, 180), 1, cv2.LINE_AA)

        # REC indicator
        rec_x = w - 58
        cv2.circle(img, (rec_x, 14), 5, (0, 0, 255), -1)
        cv2.putText(img, "REC", (rec_x + 9, 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 255), 1, cv2.LINE_AA)

        # Bottom HUD bar
        bot_y = h - 24
        bar_overlay2 = img.copy()
        cv2.rectangle(bar_overlay2, (0, bot_y), (w, h), (0, 0, 0), -1)
        img = cv2.addWeighted(img, 0.6, bar_overlay2, 0.4, 0)

        cv2.putText(img, timestamp_str, (8, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)
        if frame_label:
            cv2.putText(img, frame_label, (w // 2 - 40, h - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 255), 1, cv2.LINE_AA)

        # Corner crosshair markers
        cross_col = (80, 80, 80)
        cross_len = 12
        for (cx, cy) in [(8, 36), (w - 8, 36), (8, bot_y - 8), (w - 8, bot_y - 8)]:
            cv2.line(img, (cx - cross_len, cy), (cx + cross_len, cy), cross_col, 1)
            cv2.line(img, (cx, cy - cross_len), (cx, cy + cross_len), cross_col, 1)

        return img

    def _draw_road_scene(self, w=640, h=480, time_of_day="day"):
        """Renders a realistic road scene with lanes, markings, and ambient vehicles."""
        if time_of_day == "night":
            road_col = (18, 18, 18)
            lane_col = (80, 80, 80)
            divider_col = (0, 170, 220)
        else:
            road_col = (38, 38, 38)
            lane_col = (210, 210, 210)
            divider_col = (0, 215, 255)

        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = road_col

        sidewalk_col = (55, 50, 45)
        cv2.rectangle(img, (0, 0), (w, 35), sidewalk_col, -1)
        cv2.rectangle(img, (0, h - 35), (w, h), sidewalk_col, -1)

        for x in [w // 4, w // 2, 3 * w // 4]:
            for y in range(40, h - 40, 30):
                cv2.line(img, (x, y), (x, y + 15), lane_col, 1, cv2.LINE_AA)

        cv2.line(img, (w // 2 - 3, 35), (w // 2 - 3, h - 35), divider_col, 2)
        cv2.line(img, (w // 2 + 3, 35), (w // 2 + 3, h - 35), divider_col, 2)

        # Ambient background vehicles
        ambient_vehicles = [
            ((55, 120, 200), (70, 80), (50, 150)),
            ((40, 180, 80), (65, 75), (330, 180)),
            ((200, 80, 60), (80, 90), (460, 120)),
            ((150, 150, 150), (110, 65), (200, 280)),
            ((80, 60, 180), (70, 80), (520, 300)),
        ]
        for col, (vw, vh), (vx, vy) in ambient_vehicles:
            cv2.rectangle(img, (vx, vy), (vx + vw, vy + vh), col, -1)
            lighter = tuple(min(255, c + 60) for c in col)
            cv2.rectangle(img, (vx + 5, vy + 5), (vx + vw - 5, vy + 25), lighter, -1)
            for wx in [vx + 8, vx + vw - 8]:
                cv2.circle(img, (wx, vy + vh), 8, (10, 10, 10), -1)
                cv2.circle(img, (wx, vy + vh), 4, (40, 40, 40), -1)

        return img

    def _draw_vehicle_primitives(self, img, bx, by, bw, bh, v_type):
        """Draws a highly believable vector-style vehicle (Sedan, SUV, or Hatchback) inside the bounding box."""
        # Seed random based on coordinates to make it stable for the same case
        random.seed(bx + by)
        car_colors = [
            (60, 60, 200),   # Metallic Red
            (180, 110, 40),  # Metallic Blue
            (110, 110, 110), # Silver
            (50, 50, 50),     # Dark Gray
            (220, 220, 220), # Pearl White
            (30, 90, 230),   # Sunset Orange
            (120, 30, 150),  # Purple
        ]
        color = random.choice(car_colors)
        
        # Decide vehicle shape style based on bx
        car_style = bx % 3  # 0: Sedan, 1: SUV, 2: Hatchback
        
        # Determine direction: facing us or away
        facing_us = (v_type == "Wrong Way Driving") or (v_type == "Overspeeding" and (bx % 2 == 0))
        random.seed() # Reset seed
        
        # Draw ground shadow
        shadow_overlay = img.copy()
        cv2.ellipse(shadow_overlay, (bx + bw // 2, by + bh - 5), (int(bw * 0.5), int(bh * 0.08)), 0, 0, 360, (0, 0, 0), -1)
        cv2.addWeighted(img, 0.7, shadow_overlay, 0.3, 0, dst=img)
        
        # Draw wheels
        wheel_r = int(bh * 0.12)
        wheel_y = by + bh - wheel_r - 2
        wheel_x1 = bx + int(bw * 0.22)
        wheel_x2 = bx + int(bw * 0.78)
        
        for wx in [wheel_x1, wheel_x2]:
            cv2.circle(img, (wx, wheel_y), wheel_r, (15, 15, 15), -1)
            cv2.circle(img, (wx, wheel_y), wheel_r, (55, 55, 55), 2, cv2.LINE_AA)
            cv2.circle(img, (wx, wheel_y), wheel_r // 3, (130, 130, 130), -1)

        # Draw vehicle body & cabin depending on style
        cab_h = int(bh * 0.35)
        body_h = int(bh * 0.42)
        body_y = wheel_y - body_h + 8
        cab_y = body_y - cab_h + 3
        cab_w = int(bw * 0.75)
        cab_x = bx + (bw - cab_w) // 2

        if car_style == 0:  # Sedan
            # Cabin shape
            cab_pts = np.array([
                [cab_x + int(cab_w * 0.2), cab_y],
                [cab_x + int(cab_w * 0.8), cab_y],
                [cab_x + cab_w, body_y],
                [cab_x, body_y]
            ], np.int32)
            cv2.fillPoly(img, [cab_pts], color)
            cv2.polylines(img, [cab_pts], True, (25, 25, 25), 1, cv2.LINE_AA)
            
            # Windows
            win_col = (90, 75, 45) # Dark tint
            win_pts = np.array([
                [cab_x + int(cab_w * 0.25), cab_y + 4],
                [cab_x + int(cab_w * 0.75), cab_y + 4],
                [cab_x + int(cab_w * 0.92), body_y - 2],
                [cab_x + int(cab_w * 0.08), body_y - 2]
            ], np.int32)
            cv2.fillPoly(img, [win_pts], win_col)
            cv2.line(img, (cab_x + cab_w // 2, cab_y), (cab_x + cab_w // 2, body_y - 2), (20, 20, 20), 2)
            
            # Main chassis body
            cv2.rectangle(img, (bx, body_y), (bx + bw, body_y + body_h), color, -1)
            cv2.rectangle(img, (bx, body_y), (bx + bw, body_y + body_h), (25, 25, 25), 1, cv2.LINE_AA)
            
        elif car_style == 1:  # SUV
            # Cabin shape (boxy)
            cab_pts = np.array([
                [cab_x + int(cab_w * 0.08), cab_y],
                [cab_x + int(cab_w * 0.92), cab_y],
                [cab_x + cab_w, body_y],
                [cab_x, body_y]
            ], np.int32)
            cv2.fillPoly(img, [cab_pts], color)
            cv2.polylines(img, [cab_pts], True, (25, 25, 25), 1, cv2.LINE_AA)
            
            # Roof rack
            cv2.line(img, (cab_x + int(cab_w * 0.15), cab_y - 2), (cab_x + int(cab_w * 0.85), cab_y - 2), (50, 50, 50), 2)
            
            # Windows (boxy)
            win_col = (80, 70, 40)
            win_pts = np.array([
                [cab_x + int(cab_w * 0.12), cab_y + 4],
                [cab_x + int(cab_w * 0.88), cab_y + 4],
                [cab_x + int(cab_w * 0.94), body_y - 2],
                [cab_x + int(cab_w * 0.06), body_y - 2]
            ], np.int32)
            cv2.fillPoly(img, [win_pts], win_col)
            cv2.line(img, (cab_x + cab_w // 2, cab_y), (cab_x + cab_w // 2, body_y - 2), (20, 20, 20), 2)
            
            # Main chassis body (taller)
            cv2.rectangle(img, (bx, body_y), (bx + bw, body_y + body_h), color, -1)
            cv2.rectangle(img, (bx, body_y), (bx + bw, body_y + body_h), (25, 25, 25), 1, cv2.LINE_AA)
            
        else:  # Hatchback / Sports car
            # Sloped rear cabin
            cab_pts = np.array([
                [cab_x + int(cab_w * 0.3), cab_y],
                [cab_x + int(cab_w * 0.85), cab_y],
                [cab_x + cab_w, body_y],
                [cab_x + int(cab_w * 0.1), body_y]
            ], np.int32)
            cv2.fillPoly(img, [cab_pts], color)
            cv2.polylines(img, [cab_pts], True, (25, 25, 25), 1, cv2.LINE_AA)
            
            # Windows
            win_col = (95, 80, 50)
            win_pts = np.array([
                [cab_x + int(cab_w * 0.35), cab_y + 4],
                [cab_x + int(cab_w * 0.8), cab_y + 4],
                [cab_x + int(cab_w * 0.92), body_y - 2],
                [cab_x + int(cab_w * 0.2), body_y - 2]
            ], np.int32)
            cv2.fillPoly(img, [win_pts], win_col)
            
            # Main chassis body
            cv2.rectangle(img, (bx, body_y), (bx + bw, body_y + body_h), color, -1)
            cv2.rectangle(img, (bx, body_y), (bx + bw, body_y + body_h), (25, 25, 25), 1, cv2.LINE_AA)
            
        # Detailing based on direction
        if facing_us:
            # Front grill
            grill_y = body_y + int(body_h * 0.35)
            grill_w = int(bw * 0.55)
            grill_h = int(body_h * 0.3)
            grill_x = bx + (bw - grill_w) // 2
            cv2.rectangle(img, (grill_x, grill_y), (grill_x + grill_w, grill_y + grill_h), (20, 20, 20), -1)
            cv2.rectangle(img, (grill_x, grill_y), (grill_x + grill_w, grill_y + grill_h), (70, 70, 70), 1)
            
            # Headlights
            hl_r = int(body_h * 0.16)
            hl_y = grill_y + hl_r // 2
            hl_x1 = bx + int(bw * 0.12)
            hl_x2 = bx + int(bw * 0.88)
            for hx in [hl_x1, hl_x2]:
                cv2.circle(img, (hx, hl_y), hl_r, (180, 255, 255), -1)
                cv2.circle(img, (hx, hl_y), hl_r + 2, (50, 200, 255), 1, cv2.LINE_AA)
                
            # Side mirrors
            cv2.ellipse(img, (bx + 2, body_y + 4), (6, 3), 0, 0, 360, color, -1)
            cv2.ellipse(img, (bx + bw - 2, body_y + 4), (6, 3), 0, 0, 360, color, -1)
        else:
            # Taillights
            tl_h = int(body_h * 0.18)
            tl_w = int(bw * 0.2)
            tl_y = body_y + int(body_h * 0.28)
            tl_x1 = bx + int(bw * 0.08)
            tl_x2 = bx + int(bw * 0.92) - tl_w
            
            cv2.rectangle(img, (tl_x1, tl_y), (tl_x1 + tl_w, tl_y + tl_h), (0, 0, 240), -1)
            cv2.rectangle(img, (tl_x2, tl_y), (tl_x2 + tl_w, tl_y + tl_h), (0, 0, 240), -1)
            cv2.rectangle(img, (tl_x1, tl_y), (tl_x1 + tl_w, tl_y + tl_h), (50, 50, 255), 1, cv2.LINE_AA)
            cv2.rectangle(img, (tl_x2, tl_y), (tl_x2 + tl_w, tl_y + tl_h), (50, 50, 255), 1, cv2.LINE_AA)
            
            # Rear wiper line
            cv2.line(img, (cab_x + int(cab_w * 0.6), body_y - 4), (cab_x + int(cab_w * 0.75), body_y - 12), (10, 10, 10), 1)

        # License plate area
        plate_w = int(bw * 0.38)
        plate_h = int(body_h * 0.22)
        plate_x = bx + (bw - plate_w) // 2
        plate_y = body_y + int(body_h * 0.65)
        
        cv2.rectangle(img, (plate_x, plate_y), (plate_x + plate_w, plate_y + plate_h), (255, 255, 255), -1)
        cv2.rectangle(img, (plate_x, plate_y), (plate_x + plate_w, plate_y + plate_h), (20, 20, 20), 1)
        
        # Bumper shadow
        cv2.line(img, (bx + 5, body_y + int(body_h * 0.95)), (bx + bw - 5, body_y + int(body_h * 0.95)), (15, 15, 15), 2)
        
        return img

    def _draw_motorcycle_3_riders(self, img, bx, by, bw, bh):
        """Draw a motorcycle with 3 helmeted riders for Triple Riding violation."""
        mc_cx = bx + bw // 2
        mc_cy = by + int(bh * 0.65)
        mc_rx = int(bw * 0.42)
        mc_ry = int(bh * 0.18)

        # Motorcycle body
        cv2.ellipse(img, (mc_cx, mc_cy), (mc_rx, mc_ry), 0, 0, 360, (30, 30, 30), -1)
        cv2.ellipse(img, (mc_cx, mc_cy), (mc_rx, mc_ry), 0, 0, 360, (80, 80, 80), 2)

        # Wheels
        wheel_r = int(bh * 0.18)
        front_wx = bx + int(bw * 0.82)
        rear_wx  = bx + int(bw * 0.18)
        wheel_y  = mc_cy + int(bh * 0.1)
        for wx in [front_wx, rear_wx]:
            cv2.circle(img, (wx, wheel_y), wheel_r, (20, 20, 20), -1)
            cv2.circle(img, (wx, wheel_y), wheel_r, (70, 70, 70), 2)
            cv2.circle(img, (wx, wheel_y), wheel_r // 3, (50, 50, 50), -1)

        # Handlebar
        bar_y = by + int(bh * 0.38)
        cv2.line(img, (front_wx - 12, bar_y), (front_wx + 12, bar_y), (100, 100, 100), 3)

        # Three riders (driver, middle, rear)
        seat_y_base = by + int(bh * 0.45)
        rider_positions = [
            (bx + int(bw * 0.70), seat_y_base),
            (bx + int(bw * 0.50), seat_y_base),
            (bx + int(bw * 0.30), seat_y_base),
        ]
        helmet_colors = [
            (30, 60, 200),   # Blue - driver
            (200, 80, 30),   # Orange - middle
            (30, 160, 50),   # Green - rear
        ]

        for (rx, ry), hcol in zip(rider_positions, helmet_colors):
            head_r = max(8, int(bh * 0.10))
            # Torso
            cv2.rectangle(img,
                          (rx - head_r + 2, ry),
                          (rx + head_r - 2, ry + int(bh * 0.22)),
                          (60, 60, 80), -1)
            # Helmet
            cv2.ellipse(img, (rx, ry - head_r // 2),
                        (head_r, int(head_r * 1.1)), 0, 0, 360, hcol, -1)
            cv2.ellipse(img, (rx, ry - head_r // 2),
                        (head_r, int(head_r * 1.1)), 0, 0, 360, (200, 200, 200), 1)
            # Visor
            cv2.ellipse(img, (rx, ry - head_r // 2 + 2),
                        (int(head_r * 0.7), int(head_r * 0.3)), 0, 0, 180, (180, 220, 240), -1)
            # Arms
            arm_y = ry + int(bh * 0.08)
            cv2.line(img, (rx - head_r + 2, arm_y), (rx - head_r - 6, arm_y + 8), (50, 50, 70), 2)
            cv2.line(img, (rx + head_r - 2, arm_y), (rx + head_r + 6, arm_y + 8), (50, 50, 70), 2)

        # Alert label
        label_y = max(20, by - 5)
        cv2.rectangle(img, (bx, label_y - 16), (bx + 82, label_y + 2), (180, 0, 180), -1)
        cv2.putText(img, "3 RIDERS!", (bx + 3, label_y - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

        return img

    def _draw_violation_overlay(self, img, v_type, bx, by, bw, bh, junction_name, track_id, speed_kmh=None):
        """Draw violation-specific visual indicators on a frame."""
        h, w = img.shape[:2]

        if v_type == "Red Light Violation":
            stop_y = min(h - 30, by + bh + 15)
            cv2.line(img, (0, stop_y), (w, stop_y), (0, 0, 255), 3)
            cv2.putText(img, "STOP LINE", (10, stop_y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 255), 1, cv2.LINE_AA)
            # Traffic signal box
            sig_x, sig_y = w - 55, 40
            cv2.rectangle(img, (sig_x, sig_y), (sig_x + 30, sig_y + 80), (20, 20, 20), -1)
            cv2.rectangle(img, (sig_x, sig_y), (sig_x + 30, sig_y + 80), (60, 60, 60), 2)
            cv2.circle(img, (sig_x + 15, sig_y + 18), 10, (0, 0, 230), -1)  # Red ON
            cv2.circle(img, (sig_x + 15, sig_y + 18), 12, (0, 0, 180), 1)
            cv2.circle(img, (sig_x + 15, sig_y + 40), 10, (30, 30, 30), -1)  # Amber OFF
            cv2.circle(img, (sig_x + 15, sig_y + 62), 10, (30, 30, 30), -1)  # Green OFF
            cv2.putText(img, "SIGNAL: RED", (w - 100, sig_y + 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 80, 255), 1, cv2.LINE_AA)

        elif v_type == "Wrong Way Driving":
            arrow_y = by + bh // 2
            cv2.arrowedLine(img, (w - 100, 120), (w - 40, 120), (100, 100, 100), 2, tipLength=0.4)
            cv2.putText(img, "FLOW", (w - 105, 115),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28, (100, 100, 100), 1, cv2.LINE_AA)
            cv2.arrowedLine(img, (min(w - 10, bx + bw + 10), arrow_y),
                            (max(10, bx - 10), arrow_y), (0, 80, 255), 3, tipLength=0.35)
            cv2.putText(img, "WRONG WAY", (bx, max(20, arrow_y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 60, 255), 1, cv2.LINE_AA)

        elif v_type == "Overspeeding":
            spd = speed_kmh if speed_kmh else random.randint(82, 128)
            radar_x, radar_y = 12, 42
            cv2.rectangle(img, (radar_x, radar_y), (radar_x + 130, radar_y + 52), (10, 10, 10), -1)
            cv2.rectangle(img, (radar_x, radar_y), (radar_x + 130, radar_y + 52), (0, 200, 255), 1)
            cv2.putText(img, "SPEED RADAR", (radar_x + 5, radar_y + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 200, 255), 1, cv2.LINE_AA)
            cv2.putText(img, f"{int(spd)} km/h", (radar_x + 8, radar_y + 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 50, 255), 2, cv2.LINE_AA)
            cv2.putText(img, "LIMIT: 60", (radar_x + 72, radar_y + 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (120, 120, 120), 1, cv2.LINE_AA)

        elif v_type == "Illegal Parking":
            zone_overlay = img.copy()
            zone_x1 = max(0, bx - 20)
            zone_y1 = max(0, by - 20)
            zone_x2 = min(w, bx + bw + 20)
            zone_y2 = min(h, by + bh + 20)
            cv2.rectangle(zone_overlay, (zone_x1, zone_y1), (zone_x2, zone_y2), (0, 200, 255), -1)
            img = cv2.addWeighted(img, 0.8, zone_overlay, 0.2, 0)
            for i in range(zone_x1, zone_x2, 15):
                cv2.line(img, (i, zone_y1), (i + 20, zone_y2), (0, 160, 200), 1)
            cv2.rectangle(img, (zone_x1, zone_y1), (zone_x2, zone_y2), (0, 215, 255), 2)
            cv2.putText(img, "NO PARKING ZONE", (zone_x1, max(15, zone_y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 215, 255), 1, cv2.LINE_AA)

        elif v_type == "Triple Riding":
            img = self._draw_motorcycle_3_riders(img, bx, by, bw, bh)

        return img

    # =========================================================================
    # VIOLATION GENERATION
    # =========================================================================

    def _generate_simulated_violation(self, junction, track_id, frame_num):
        """Creates evidence file structure and writes violation + ticket to SQLite."""
        violation_types = [
            ("Red Light Violation",  "RED"),
            ("Wrong Way Driving",    "WRONG"),
            ("Illegal Parking",      "PARK"),
            ("Overspeeding",         "OVER"),
            ("Triple Riding",        "TRIPLE"),
        ]
        v_type, suffix = random.choice(violation_types)
        v_id = f"V_{frame_num}_{track_id}_{suffix}"

        if v_type == "Triple Riding":
            bx = random.randint(150, 380)
            by = random.randint(150, 280)
            bw = random.randint(90, 130)
            bh = random.randint(80, 120)
        else:
            bx = random.randint(120, 400)
            by = random.randint(130, 300)
            bw = random.randint(90, 160)
            bh = random.randint(80, 140)
        bbox = [bx, by, bx + bw, by + bh]

        confidence = round(random.uniform(0.70, 0.98), 2)
        timestamp  = datetime.now().isoformat()

        states = ["KA 03", "KA 05", "MH 12", "DL 03", "TS 09"]
        plate_no = f"{random.choice(states)} AB {random.randint(1000, 9999)}"

        hour = datetime.now().hour
        time_of_day = "night" if (hour < 6 or hour > 20) else "day"
        spd = round(random.uniform(82, 130), 1) if v_type == "Overspeeding" else None

        cam_map = {
            "silk_board_junction":    "CAM-12 | SILK BOARD JCN",
            "koramangala_3rd_block":  "CAM-13 | KORAMANGALA 3RD BLK",
            "indiranagar_100ft_road": "CAM-14 | INDIRANAGAR 100FT RD",
        }
        cam_display = cam_map.get(junction["id"], "CAM-XX | UNKNOWN")

        case_dir = os.path.join("evidence", v_id)
        os.makedirs(case_dir, exist_ok=True)

        video_src = "test_simulation.mp4"
        if junction["id"] == "silk_board_junction":
            video_src = "output_tracked.mp4"

        frames = {}
        read_success = False
        cap = cv2.VideoCapture(video_src)
        if cap.isOpened():
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            target_idx = random.randint(30, max(40, total_frames - 30))
            offsets = {
                "frame_minus2": -10,
                "frame_minus1": -5,
                "frame_0":       0,
                "frame_plus1":   5,
                "frame_plus2":  10,
            }
            try:
                for label, offset in offsets.items():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx + offset)
                    ret, f_img = cap.read()
                    if ret and f_img is not None:
                        frames[label] = cv2.resize(f_img, (640, 480))
                    else:
                        break
                if len(frames) == 5:
                    read_success = True
            except Exception as e:
                print(f"[Demo Simulator] Video frame extraction failed: {e}")
            finally:
                cap.release()

        if not read_success:
            base_scene = self._draw_road_scene(640, 480, time_of_day)
            for label in ["frame_minus2", "frame_minus1", "frame_0", "frame_plus1", "frame_plus2"]:
                frames[label] = base_scene.copy()

        frame_labels_map = {
            "frame_minus2": "T-2.0s APPROACH",
            "frame_minus1": "T-1.0s APPROACH",
            "frame_0":      "T+0.0s INFRACTION",
            "frame_plus1":  "T+1.0s DEPARTURE",
            "frame_plus2":  "T+2.0s DEPARTURE",
        }
        violation_colors = {
            "Red Light Violation": (0, 0, 255),
            "Wrong Way Driving":   (0, 100, 255),
            "Overspeeding":        (0, 140, 255),
            "Illegal Parking":     (0, 215, 255),
            "Triple Riding":       (180, 0, 200),
        }
        box_col = violation_colors.get(v_type, (0, 0, 255))

        # Motion animation setup for the 5-frame sequence
        frame_offsets = {
            "frame_minus2": -2,
            "frame_minus1": -1,
            "frame_0":       0,
            "frame_plus1":   1,
            "frame_plus2":   2,
        }
        
        speed_offset_mult = 16 if v_type == "Overspeeding" else 8
        if v_type == "Illegal Parking":
            speed_offset_mult = 0
            
        dx = -1 if v_type == "Wrong Way Driving" else 1
        dy = 0

        annotated_frames = {}

        for label, f_img in frames.items():
            annotated = f_img.copy()
            ts_str    = timestamp[11:19]
            frame_lbl = frame_labels_map.get(label, "")

            # Apply frame offsets to draw moving vehicles
            step = frame_offsets.get(label, 0)
            curr_bx = bx + step * dx * speed_offset_mult
            curr_by = by + step * dy * speed_offset_mult

            # Draw vehicle!
            if v_type == "Triple Riding":
                annotated = self._draw_motorcycle_3_riders(annotated, curr_bx, curr_by, bw, bh)
            else:
                annotated = self._draw_vehicle_primitives(annotated, curr_bx, curr_by, bw, bh, v_type)

            # Draw violation overlays
            annotated = self._draw_violation_overlay(
                annotated, v_type, curr_bx, curr_by, bw, bh, junction["name"], track_id, spd
            )

            # Draw bounding box and label
            if v_type != "Triple Riding":
                cv2.rectangle(annotated, (curr_bx, curr_by), (curr_bx + bw, curr_by + bh), box_col, 2)
                header_text = f"#{track_id} {v_type}"
                (tw, _), _ = cv2.getTextSize(header_text, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                lbl_y = max(20, curr_by)
                cv2.rectangle(annotated, (curr_bx, lbl_y - 18), (curr_bx + tw + 6, lbl_y), box_col, -1)
                cv2.putText(annotated, header_text, (curr_bx + 3, lbl_y - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

            annotated = self._apply_cctv_overlay(annotated, cam_display, ts_str, frame_lbl)
            cv2.imwrite(os.path.join(case_dir, f"{label}.jpg"), annotated,
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            annotated_frames[label] = annotated

        # Vehicle crop (frame_0 is step=0, so curr_bx = bx, curr_by = by)
        clean_frame_0 = frames["frame_0"].copy()
        if v_type == "Triple Riding":
            clean_frame_0 = self._draw_motorcycle_3_riders(clean_frame_0, bx, by, bw, bh)
        else:
            clean_frame_0 = self._draw_vehicle_primitives(clean_frame_0, bx, by, bw, bh, v_type)

        x1 = max(0, bx - 10)
        y1 = max(0, by - 10)
        x2 = min(640, bx + bw + 10)
        y2 = min(480, by + bh + 10)
        v_crop = clean_frame_0[y1:y2, x1:x2]
        if v_crop.size == 0:
            v_crop = np.zeros((150, 150, 3), dtype=np.uint8)
            v_crop[:] = (30, 80, 30)

        v_crop_resized = cv2.resize(v_crop, (200, 160))
        cv2.imwrite(os.path.join(case_dir, "cropped_vehicle.jpg"), v_crop_resized,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])

        enhanced = cv2.convertScaleAbs(v_crop_resized, alpha=1.25, beta=15)
        kernel   = np.array([[0, -0.3, 0], [-0.3, 2.2, -0.3], [0, -0.3, 0]])
        enhanced = cv2.filter2D(enhanced, -1, kernel)
        enhanced = np.clip(enhanced, 0, 255).astype(np.uint8)
        cv2.imwrite(os.path.join(case_dir, "enhanced_vehicle.jpg"), enhanced,
                    [cv2.IMWRITE_JPEG_QUALITY, 94])

        # ANPR plate crop
        plate_w, plate_h = 280, 80
        p_crop = np.zeros((plate_h, plate_w, 3), dtype=np.uint8)
        is_yellow = (v_type == "Triple Riding") or random.choice([True, False])
        p_crop[:] = (0, 215, 255) if is_yellow else (255, 255, 255)
        cv2.rectangle(p_crop, (0, 0), (32, plate_h), (140, 30, 30), -1)
        cv2.putText(p_crop, "IND",   (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(p_crop, "INDIA", (2, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.22, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.rectangle(p_crop, (0, 0), (plate_w - 1, plate_h - 1), (20, 20, 20), 3)
        txt_col = (0, 0, 0)
        cv2.putText(p_crop, plate_no, (40, 52), cv2.FONT_HERSHEY_DUPLEX, 0.72, txt_col, 2, cv2.LINE_AA)
        cv2.circle(p_crop, (plate_w - 18, 20), 10, (180, 120, 20), -1)
        cv2.putText(p_crop, "IND", (plate_w - 28, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.22, (255, 255, 200), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(case_dir, "plate_crop.jpg"), p_crop,
                    [cv2.IMWRITE_JPEG_QUALITY, 96])

        # Evidence summary collage using the annotated frames showing the moving car
        self._generate_evidence_collage(
            case_dir, v_id, v_type, junction["name"], plate_no,
            confidence, timestamp, cam_display, annotated_frames, bx, by, bw, bh, spd
        )

        evidence_images = [
            f"evidence/{v_id}/frame_minus2.jpg",
            f"evidence/{v_id}/frame_minus1.jpg",
            f"evidence/{v_id}/frame_0.jpg",
            f"evidence/{v_id}/frame_plus1.jpg",
            f"evidence/{v_id}/frame_plus2.jpg",
            f"evidence/{v_id}/cropped_vehicle.jpg",
            f"evidence/{v_id}/enhanced_vehicle.jpg",
            f"evidence/{v_id}/plate_crop.jpg",
            f"evidence/{v_id}/evidence_summary.jpg",
        ]

        ticket_id = f"TKT_{frame_num}_{track_id}_{suffix}"

        try:
            from enforcement_engine import EnforcementEngine
            ee_data = EnforcementEngine.evaluate_violation(v_type, confidence)
        except Exception as e:
            print(f"[Demo Simulator] EnforcementEngine error: {e}")
            ee_data = {
                "evidence_score":       confidence,
                "status":               "AUTO_APPROVED" if confidence > 0.94 else "AWAITING_REVIEW",
                "fine_amount":          1000,
                "discard_reason":       None,
                "tracking_confidence":  0.95,
                "ocr_confidence":       0.90,
                "explainability_notes": ["System default check"],
            }

        violation_row = {
            "violation_id":         v_id,
            "vehicle_id":           str(track_id),
            "violation_type":       v_type,
            "timestamp":            timestamp,
            "confidence":           confidence,
            "bbox":                 bbox,
            "frame_number":         frame_num,
            "plate_number":         plate_no,
            "ticket_id":            ticket_id,
            "location":             junction["name"],
            "junction_id":          junction["id"],
            "evidence_score":       ee_data["evidence_score"],
            "status":               ee_data["status"],
            "fine_amount":          ee_data["fine_amount"],
            "discard_reason":       ee_data["discard_reason"],
            "tracking_confidence":  ee_data["tracking_confidence"],
            "ocr_confidence":       ee_data["ocr_confidence"],
            "explainability_notes": ee_data["explainability_notes"],
        }
        database.insert_violation(violation_row)

        ticket_row = {**violation_row, "ticket_id": ticket_id, "evidence_images": evidence_images}
        database.insert_ticket(ticket_row)

        with open(os.path.join(case_dir, "ticket.json"), "w") as f:
            json.dump(ticket_row, f, indent=4)

        self.manager.update_junction_stats(
            junction_id=junction["id"],
            active_violations=junction["active_violations"] + 1
        )

        database.insert_alert(
            title="New Infraction",
            text=f"{v_type} (Plate: {plate_no}) flagged at {junction['name']}.",
            alert_type="infraction",
            violation_id=v_id,
        )

    def _generate_evidence_collage(self, case_dir, v_id, v_type, location,
                                   plate_no, confidence, timestamp, cam_display,
                                   frames, bx, by, bw, bh, speed_kmh=None):
        """Generates a professional evidence dossier collage image."""
        cw, ch = 1280, 520
        canvas = np.zeros((ch, cw, 3), dtype=np.uint8)
        canvas[:] = (12, 15, 25)

        fw, fh = 256, 192
        seq_keys   = ["frame_minus2", "frame_minus1", "frame_0", "frame_plus1", "frame_plus2"]
        seq_labels = ["T-2s APPROACH", "T-1s APPROACH", "T INFRACTION", "T+1s DEPART", "T+2s DEPART"]
        seq_borders = [(80,80,80), (100,100,100), (0,0,220), (80,80,80), (80,80,80)]

        for idx, (key, lbl, bcol) in enumerate(zip(seq_keys, seq_labels, seq_borders)):
            f_img   = frames.get(key, np.zeros((480, 640, 3), np.uint8))
            resized = cv2.resize(f_img, (fw, fh))
            ox      = idx * fw
            canvas[0:fh, ox:ox + fw] = resized
            cv2.rectangle(canvas, (ox, 0), (ox + fw - 1, fh - 1), bcol, 2)
            cv2.rectangle(canvas, (ox, fh - 18), (ox + fw, fh), (0, 0, 0), -1)
            cv2.putText(canvas, lbl, (ox + 5, fh - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (200, 200, 200), 1, cv2.LINE_AA)

        cv2.line(canvas, (0, fh), (cw, fh), (40, 45, 60), 2)

        crop_path = os.path.join(case_dir, "cropped_vehicle.jpg")
        if os.path.exists(crop_path):
            v_img = cv2.imread(crop_path)
            if v_img is not None:
                canvas[fh + 16:fh + 216, 12:242] = cv2.resize(v_img, (230, 200))
                cv2.rectangle(canvas, (12, fh + 16), (242, fh + 216), (60, 60, 80), 2)
                cv2.putText(canvas, "VEHICLE CROP", (14, fh + 13),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 200, 255), 1, cv2.LINE_AA)

        plate_path = os.path.join(case_dir, "plate_crop.jpg")
        if os.path.exists(plate_path):
            p_img = cv2.imread(plate_path)
            if p_img is not None:
                py_s = fh + 55
                canvas[py_s:py_s + 90, 255:575] = cv2.resize(p_img, (320, 90))
                cv2.rectangle(canvas, (255, py_s), (575, py_s + 90), (80, 80, 40), 2)
                cv2.putText(canvas, "ANPR PLATE CROP", (258, py_s - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.32, (200, 200, 100), 1, cv2.LINE_AA)
                cv2.putText(canvas, f"OCR READING: {plate_no}", (258, py_s + 108),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 215, 255), 1, cv2.LINE_AA)

        px, py = 590, fh + 8
        pw, ph = cw - px - 8, ch - py - 8
        cv2.rectangle(canvas, (px, py), (px + pw, py + ph), (18, 22, 36), -1)
        cv2.rectangle(canvas, (px, py), (px + pw, py + ph), (40, 50, 80), 2)

        cv2.putText(canvas, "GRIDLOCK AI  -  EVIDENCE DOSSIER", (px + 12, py + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)
        cv2.line(canvas, (px + 12, py + 30), (px + pw - 12, py + 30), (40, 50, 80), 1)

        vtype_colors = {
            "Red Light Violation": (0, 60, 255),
            "Wrong Way Driving":   (0, 120, 255),
            "Overspeeding":        (0, 160, 255),
            "Illegal Parking":     (0, 215, 255),
            "Triple Riding":       (200, 0, 220),
        }
        vc = vtype_colors.get(v_type, (0, 200, 255))
        cv2.putText(canvas, f"TYPE: {v_type.upper()}", (px + 12, py + 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, vc, 2, cv2.LINE_AA)

        meta_lines = [
            ("CASE ID",    v_id),
            ("TICKET",     f"TKT-{v_id[2:]}"),
            ("PLATE",      plate_no),
            ("LOCATION",   location[:28]),
            ("CAMERA",     cam_display[:28]),
            ("TIMESTAMP",  timestamp[:19].replace("T", " ")),
            ("CONFIDENCE", f"{int(confidence * 100)}%"),
        ]
        for i, (lbl, val) in enumerate(meta_lines):
            y = py + 82 + i * 26
            cv2.putText(canvas, f"{lbl}:", (px + 12, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, (100, 110, 140), 1, cv2.LINE_AA)
            cv2.putText(canvas, val, (px + 110, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (220, 225, 240), 1, cv2.LINE_AA)

        if speed_kmh:
            y = py + 82 + len(meta_lines) * 26
            cv2.putText(canvas, "DETECTED SPD:", (px + 12, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, (100, 110, 140), 1, cv2.LINE_AA)
            cv2.putText(canvas, f"{speed_kmh} km/h  (LIMIT 60)", (px + 110, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 80, 255), 1, cv2.LINE_AA)

        cv2.imwrite(os.path.join(case_dir, "evidence_summary.jpg"), canvas,
                    [cv2.IMWRITE_JPEG_QUALITY, 93])

    # =========================================================================
    # AMBIENT ALERTS
    # =========================================================================

    def _generate_simulated_alert(self):
        """Creates ambient operational alerts based on simulated junction limits."""
        junctions = self.manager.get_all_junctions()
        j = random.choice(junctions)

        choices = [
            ("Critical Overspeed",
             f"Speeding detected at {j['name']}.",
             "critical"),
            ("Traffic Jam Detected",
             f"Congestion peaked at {j['congestion_level']}% in {j['name']}.",
             "warning"),
            ("Congestion Risk",
             f"Risk index surged to {j['risk_score']} near {j['name']}.",
             "info"),
        ]
        title, text, atype = random.choice(choices)
        database.insert_alert(title=title, text=text, alert_type=atype)
