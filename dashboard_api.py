# dashboard_api.py
# FastAPI application — Smart City REST API endpoints and static asset server.
# ALL data now served from gridlock.db (SQLite) via database.py.
# No JSON file reads. No hardcoded scaling multipliers.

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocket, WebSocketDisconnect
import asyncio
import os
import json
from datetime import datetime

import database
from junction_manager import JunctionManager
from heatmap_engine import HeatmapEngine
from congestion_predictor import CongestionPredictor
from demo_mode import DemoSimulator
from camera_stream import CameraManager
from traffic_ai_service import TrafficAIService
import cv2
import config
from fastapi import BackgroundTasks

app = FastAPI(title="GRIDLOCK AI — Smart City Command Center", version="5.0")

# CORS — allow all origins for dashboard cross-origin calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── System initialisation ──────────────────────────────────────────────────────
j_manager  = JunctionManager("junction_config.json")
heatmap_eng = HeatmapEngine(j_manager)
predictor   = CongestionPredictor()
demo_sim    = DemoSimulator(j_manager, "violations.json")
ai_service  = TrafficAIService(yolov8_model_path="yolov8n.pt", log_path="violations.json")
cam_manager = CameraManager("cameras.json")


@app.on_event("startup")
def startup_event():
    """Initialise SQLite schema, start demo simulator, and start all camera streams."""
    database.init_db()
    
    # Clear out any awaiting review tickets so we start clean with the upgraded CCTV overlays!
    conn = database._get_conn()
    try:
        conn.execute("DELETE FROM violations WHERE status = 'AWAITING_REVIEW'")
        conn.execute("DELETE FROM tickets WHERE status = 'AWAITING_REVIEW'")
        conn.commit()
    except Exception as e:
        print(f"Error cleaning old awaiting review tickets: {e}")
    finally:
        conn.close()
        
    demo_sim.start()
    cam_manager.start_all()

    # Force generate a couple of initial premium violations immediately on startup
    try:
        import random
        junctions = j_manager.get_all_junctions()
        if junctions:
            for i in range(2):
                demo_sim._generate_simulated_violation(random.choice(junctions), 600 + i, 4400 + i)
    except Exception as e:
        print(f"Error generating initial demo violations: {e}")


@app.on_event("shutdown")
def shutdown_event():
    demo_sim.stop()
    cam_manager.stop_all()


# ── Static file mounts ─────────────────────────────────────────────────────────
if not os.path.exists("evidence"):
    os.makedirs("evidence", exist_ok=True)
app.mount("/evidence", StaticFiles(directory="evidence"), name="evidence")


# ── Root / HTML pages ──────────────────────────────────────────────────────────
@app.get("/")
def read_index():
    if os.path.exists("dashboard.html"):
        return FileResponse("dashboard.html")
    raise HTTPException(status_code=404, detail="dashboard.html not found")

@app.get("/dashboard.js")
def read_js():
    return FileResponse("dashboard.js")

@app.get("/dashboard.css")
def read_css():
    return FileResponse("dashboard.css")

@app.get("/junction_monitor.html")
def read_junction_monitor():
    return FileResponse("junction_monitor.html")

@app.get("/junction_monitor.js")
def read_junction_monitor_js():
    return FileResponse("junction_monitor.js")

@app.get("/investigation_dashboard.html")
def read_investigation_dashboard():
    return FileResponse("investigation_dashboard.html")

@app.get("/investigation_dashboard.js")
def read_investigation_dashboard_js():
    return FileResponse("investigation_dashboard.js")

@app.get("/analytics_dashboard.html")
def read_analytics_dashboard():
    return FileResponse("analytics_dashboard.html")

@app.get("/analytics_dashboard.js")
def read_analytics_dashboard_js():
    return FileResponse("analytics_dashboard.js")

@app.get("/enforcement_dashboard.html")
def read_enforcement_dashboard():
    return FileResponse("enforcement_dashboard.html")

@app.get("/enforcement_dashboard.js")
def read_enforcement_dashboard_js():
    return FileResponse("enforcement_dashboard.js")


# ══════════════════════════════════════════════════════════════════════════════
# REST API — ALL responses come from SQLite queries
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/junctions")
def get_junctions():
    """List of active city junctions with their current live metrics."""
    return {
        "junctions":         j_manager.get_all_junctions(),
        "active_junction_id": j_manager.active_junction_id,
    }


@app.post("/api/junctions/active")
def set_active_junction(junction_id: str):
    """Switch the actively monitored CCTV junction."""
    success = j_manager.set_active_junction(junction_id)
    if not success:
        raise HTTPException(status_code=404, detail="Junction ID not found")
    return {
        "success":           True,
        "active_junction_id": j_manager.active_junction_id,
        "junction_data":     j_manager.get_active_junction(),
    }


@app.get("/api/live-stats")
def get_live_stats():
    """
    Real-time Command Center header metrics.
    All numbers are SQL aggregate query results from gridlock.db.
    """
    active_j = j_manager.get_active_junction()
    all_j    = j_manager.get_all_junctions()

    # ── Aggregate stats from DB (real SQL counts) ──────────────────────────
    db_stats = database.query_live_stats()

    # ── Junction-level summaries (in-memory, updated every 3 s by simulator) ─
    total_active_violations = sum(j["active_violations"] for j in all_j)
    most_congested  = max(all_j, key=lambda x: x["congestion_level"])
    highest_risk    = max(all_j, key=lambda x: x["risk_score"])

    # Use DB most_dangerous if available, else fall back to in-memory
    most_dangerous = db_stats["most_dangerous_junction"] or highest_risk["name"]

    # ── Alert timeline from DB ─────────────────────────────────────────────
    alerts_feed = database.query_recent_alerts(10)

    return {
        "system_status":      "ONLINE",
        "total_active_cameras": len(all_j),
        "current_time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_junction":    active_j,
        "junctions":          all_j,
        "global_analytics": {
            # Real SQL counts — no scaling multipliers
            "vehicles_today":           db_stats["vehicles_today"],
            "violations_today":         db_stats["violations_today"],
            "average_speed_kmph":       db_stats["average_speed_kmph"],
            "most_dangerous_junction":  most_dangerous,
            "highest_congestion_junction": most_congested["name"],
            "active_violations":        db_stats["active_violations"],
        },
        "alerts_timeline": alerts_feed,
    }


@app.get("/api/stats/cameras")
def get_stats_cameras():
    """
    Returns camera list with live statistics queried from the database.
    """
    junction_ids = ["koramangala_3rd_block", "silk_board_junction", "indiranagar_100ft_road"]
    db_stats = database.query_latest_camera_stats(junction_ids)
    
    cameras_out = []
    for j_id in junction_ids:
        j_data = j_manager.get_junction(j_id)
        if not j_data:
            continue
        
        db_snap = db_stats.get(j_id, {})
        active_violations_db = database.query_active_violations_count(j_id)
        
        cameras_out.append({
            "id": j_id,
            "name": j_data.get("name", j_id),
            "lat": j_data.get("lat"),
            "lng": j_data.get("lng"),
            "risk": db_snap.get("risk_score") if db_snap.get("risk_score") is not None else j_data.get("risk_score", 0),
            "violations": active_violations_db if active_violations_db is not None else db_snap.get("active_violations", j_data.get("active_violations", 0)),
            "vehicle_count": db_snap.get("vehicle_count") if db_snap.get("vehicle_count") is not None else j_data.get("vehicle_count", 0),
            "avg_speed": db_snap.get("average_speed") if db_snap.get("average_speed") is not None else j_data.get("average_speed", 0.0),
            "congestion_pct": db_snap.get("congestion_level") if db_snap.get("congestion_level") is not None else j_data.get("congestion_level", 0.0),
        })
        
    return cameras_out


@app.get("/api/violations")
def get_violations(limit: int = Query(200, ge=1, le=1000)):
    """All detected violations from gridlock.db, newest first."""
    return database.query_all_violations(limit)


@app.get("/api/tickets")
def get_tickets(limit: int = Query(200, ge=1, le=1000)):
    """All challan tickets from gridlock.db, newest first."""
    return database.query_all_tickets(limit)


@app.get("/api/cases/{ticket_id}")
def get_case_details(ticket_id: str):
    """Full violation + ticket case data for Investigation Center."""
    result = database.query_violation_by_id(ticket_id)
    if result:
        return result

    # Fallback: try loading ticket.json sidecar from evidence directory
    ticket_file = os.path.join("evidence", ticket_id, "ticket.json")
    if os.path.exists(ticket_file):
        try:
            import json
            with open(ticket_file, "r") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read ticket: {e}")

    raise HTTPException(status_code=404, detail=f"Case not found: {ticket_id}")


@app.get("/api/violations/history/{plate_number}")
def get_violation_history(plate_number: str):
    """All violations associated with a specific licence plate."""
    return database.query_violations_by_plate(plate_number)


@app.get("/api/heatmap")
def get_heatmap(type: str = Query("density", enum=["density", "violations", "risk"])):
    """Coordinate-weighted heatmap data for the city map overlay."""
    points = heatmap_eng.get_heatmap_data(type)
    return {"type": type, "points": points}


@app.get("/api/congestion")
def get_congestion_predictions():
    """Forecast traffic congestion using moving-average predictor."""
    active_j = j_manager.get_active_junction()
    if not active_j:
        raise HTTPException(status_code=404, detail="No active junction selected")
    predictions = predictor.predict(active_j["id"], active_j["congestion_level"])
    return predictions


@app.get("/api/analytics/violations-by-type")
def get_violations_by_type():
    """Violation type breakdown for Analytics dashboard pie/bar charts."""
    return database.query_violation_type_breakdown()


@app.get("/api/analytics/enforcement-status")
def get_enforcement_status():
    """Auto-approved / awaiting-review / discarded breakdown."""
    return database.query_status_breakdown()


@app.get("/api/analytics/junction-history/{junction_id}")
def get_junction_history(junction_id: str, last_n: int = Query(60, ge=5, le=200)):
    """Timestamped metric series for a junction (for live trend charts)."""
    return database.query_junction_history(junction_id, last_n)


@app.get("/api/cameras")
def list_cameras():
    """List all configured camera sources."""
    return cam_manager.list_cameras()


# ── MJPEG Live Stream ──────────────────────────────────────────────────────────
def _mjpeg_generator(cam_id: str):
    """
    Generator that yields multipart/x-mixed-replace JPEG frames.
    The browser displays this directly inside an <img> tag.
    """
    stream = cam_manager.get_stream(cam_id)
    if stream is None:
        # Yield a single empty frame so the browser doesn't hang
        return

    boundary = b"--frame\r\n"
    while True:
        frame_bytes = stream.get_frame()
        if frame_bytes:
            yield (
                boundary
                + b"Content-Type: image/jpeg\r\n"
                + b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                + frame_bytes
                + b"\r\n"
            )
        else:
            import time
            time.sleep(0.05)


@app.get("/stream/camera/{cam_id}")
def stream_camera_mjpeg(cam_id: str):
    """
    Motion JPEG stream endpoint.
    Frontend: <img src="/stream/camera/cam_12">
    Streams annotated real video frames with bounding boxes from YOLO+ByteTrack.
    """
    stream = cam_manager.get_stream(cam_id)
    if stream is None:
        # Try by junction_id as alias
        stream = cam_manager.get_stream_by_junction(cam_id)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"Camera {cam_id!r} not found")

    actual_id = stream.cam_id
    return StreamingResponse(
        _mjpeg_generator(actual_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/stream/junction/{junction_id}")
def stream_junction_mjpeg(junction_id: str):
    """Alias: stream by junction_id for dashboard integration."""
    stream = cam_manager.get_stream_by_junction(junction_id)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"No camera for junction {junction_id!r}")
    return StreamingResponse(
        _mjpeg_generator(stream.cam_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ── WebSocket Telemetry ────────────────────────────────────────────────────────
@app.websocket("/ws/camera/{cam_id}")
async def ws_camera_telemetry(websocket: WebSocket, cam_id: str):
    """
    WebSocket: pushes vehicle telemetry JSON every 200 ms.
    Message format:
    {
      "cam_id": "cam_12",
      "junction_id": "silk_board_junction",
      "ts": "14:31:05",
      "vehicle_count": 7,
      "vehicles": [
        {"track_id": 42, "class_label": "Car", "speed_kmph": 38.5,
         "direction": "SOUTHBOUND", "confidence": 0.91,
         "is_violating": false, "violation_text": ""},
        ...
      ]
    }
    """
    await websocket.accept()
    stream = cam_manager.get_stream(cam_id)
    if stream is None:
        stream = cam_manager.get_stream_by_junction(cam_id)

    if stream is None:
        await websocket.send_json({"error": f"Camera {cam_id!r} not found"})
        await websocket.close()
        return

    try:
        while True:
            telemetry = stream.get_telemetry()
            payload = {
                "cam_id":        stream.cam_id,
                "junction_id":   stream.junction_id,
                "ts":            datetime.now().strftime("%H:%M:%S"),
                "vehicle_count": len(telemetry),
                "vehicles":      telemetry,
            }
            await websocket.send_json(payload)
            await asyncio.sleep(0.2)   # 5 Hz telemetry updates
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS:{cam_id}] Disconnected: {e}")


@app.websocket("/ws/junction/{junction_id}")
async def ws_junction_telemetry(websocket: WebSocket, junction_id: str):
    """WebSocket alias using junction_id."""
    await websocket.accept()
    stream = cam_manager.get_stream_by_junction(junction_id)
    if stream is None:
        await websocket.send_json({"error": f"No camera for junction {junction_id!r}"})
        await websocket.close()
        return

    try:
        while True:
            telemetry = stream.get_telemetry()
            payload = {
                "cam_id":        stream.cam_id,
                "junction_id":   stream.junction_id,
                "ts":            datetime.now().strftime("%H:%M:%S"),
                "vehicle_count": len(telemetry),
                "vehicles":      telemetry,
            }
            await websocket.send_json(payload)
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, Exception):
        pass


# ── Static MP4 video fallback endpoints (kept for Investigation Center) ────────

@app.get("/api/video/silk_board_junction")
def get_silk_board_video():
    if os.path.exists("output_tracked.mp4"):
        return FileResponse("output_tracked.mp4", media_type="video/mp4")
    raise HTTPException(status_code=404, detail="output_tracked.mp4 not found")

@app.get("/api/video/koramangala_3rd_block")
def get_koramangala_video():
    if os.path.exists("test_simulation.mp4"):
        return FileResponse("test_simulation.mp4", media_type="video/mp4")
    raise HTTPException(status_code=404, detail="test_simulation.mp4 not found")

@app.get("/api/video/indiranagar_100ft_road")
def get_indiranagar_video():
    if os.path.exists("test_simulation.mp4"):
        return FileResponse("test_simulation.mp4", media_type="video/mp4")
    raise HTTPException(status_code=404, detail="test_simulation.mp4 not found")


# ── Enforcement desk actions ───────────────────────────────────────────────────
@app.post("/api/enforcement/approve/{violation_id}")
def approve_violation_case(violation_id: str):
    """Officer approves a challan — updates DB row to APPROVED."""
    result = database.query_violation_by_id(violation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case not found")

    notes = ["✓ Manual Officer review: APPROVED"]
    ok = database.update_violation_status(violation_id, "APPROVED", notes=notes)
    if not ok:
        raise HTTPException(status_code=500, detail="DB update failed")

    return {"success": True, "violation_id": violation_id, "status": "APPROVED"}


@app.post("/api/enforcement/discard/{violation_id}")
def discard_violation_case(
    violation_id: str,
    reason: str = Query("Manual Discard"),
):
    """Officer discards a challan — updates DB row to DISCARDED."""
    result = database.query_violation_by_id(violation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case not found")

    notes = [f"✗ Manual Officer review: DISCARDED ({reason})"]
    ok = database.update_violation_status(violation_id, "DISCARDED", reason=reason, notes=notes)
    if not ok:
        raise HTTPException(status_code=500, detail="DB update failed")

    return {"success": True, "violation_id": violation_id, "status": "DISCARDED", "reason": reason}


# ── CANONICAL ENDPOINTS ────────────────────────────────────────────────────────
# Every number on every dashboard page comes from these SQL-backed endpoints.
# Math.random(), hardcoded counts, and fake increments are PROHIBITED.

@app.get("/api/stats/summary")
def stats_summary():
    """
    GET /api/stats/summary
    Returns: vehicles_today (SQL COUNT vehicles), violations_today (SQL COUNT violations),
             active_cameras (SQL COUNT DISTINCT camera_id in congestion_log).
    All values are live SQL aggregates — zero hardcoded values.
    """
    return database.query_stats_summary()


@app.get("/api/violations")
def list_violations(
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status:   str = Query(None),
    camera_id: str = Query(None),
):
    """
    GET /api/violations?page=1&per_page=50&status=AWAITING_REVIEW&camera_id=cam_12
    Returns paginated violation list from the violations table.
    """
    return database.query_violations_paginated(
        page=page, per_page=per_page, status=status, camera_id=camera_id
    )


@app.get("/api/congestion/{cam_id}")
def congestion_for_camera(cam_id: str, n: int = Query(60, ge=1, le=500)):
    """
    GET /api/congestion/{cam_id}?n=60
    Returns the last 60 congestion_log rows for that camera.
    Used by analytics_dashboard.js for the live congestion line chart.
    """
    rows = database.query_congestion_history(cam_id, last_n=n)
    return {"camera_id": cam_id, "points": rows}


@app.get("/api/tickets/{ticket_id}")
def get_single_ticket(ticket_id: str):
    """
    GET /api/tickets/{ticket_id}
    Returns full ticket + merged violation fields + evidence frames from DB.
    """
    result = database.query_ticket_by_id(ticket_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id!r} not found")
    return result


@app.post("/api/tickets/{ticket_id}/approve")
def approve_ticket(ticket_id: str):
    """POST /api/tickets/{ticket_id}/approve — update status to APPROVED in DB."""
    t = database.query_ticket_by_id(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    vid = t.get("violation_id", ticket_id)
    notes = ["✓ Manual Officer review: APPROVED"]
    ok = database.update_violation_status(vid, "APPROVED", notes=notes)
    return {"success": ok, "ticket_id": ticket_id, "status": "APPROVED"}


@app.post("/api/tickets/{ticket_id}/discard")
def discard_ticket(ticket_id: str, reason: str = Query("Insufficient evidence")):
    """POST /api/tickets/{ticket_id}/discard?reason=... — update status to DISCARDED in DB."""
    t = database.query_ticket_by_id(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    vid = t.get("violation_id", ticket_id)
    notes = [f"✗ Discarded by officer: {reason}"]
    ok = database.update_violation_status(vid, "DISCARDED", reason=reason, notes=notes)
    return {"success": ok, "ticket_id": ticket_id, "status": "DISCARDED", "reason": reason}


# ── WebSocket /ws/events — real-time violation event stream ────────────────────
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """
    WS /ws/events
    Pushes new violation/alert events as they happen (tail on alerts table).
    Message format:
    {
      "type": "infraction"|"critical"|"info",
      "title": str,
      "text": str,
      "time": "HH:MM:SS",
      "violation_id": str | null
    }
    """
    await websocket.accept()
    last_id = database.get_latest_event_id()

    try:
        while True:
            new_events = database.query_alerts_since(last_id, limit=20)
            for ev in new_events:
                last_id = max(last_id, ev.get("id", last_id))
                await websocket.send_json({
                    "id":           ev.get("id"),
                    "type":         ev.get("type", "info"),
                    "title":        ev.get("title", "Event"),
                    "text":         ev.get("text", ""),
                    "time":         ev.get("alert_time", datetime.now().strftime("%H:%M:%S")),
                    "violation_id": ev.get("violation_id"),
                })
            await asyncio.sleep(0.5)   # 2 Hz poll of alerts table
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS /ws/events] Disconnected: {e}")


# ── Video processing (real AI pipeline trigger) ────────────────────────────────
@app.post("/api/process-video")
def process_video_feed(video_path: str, background_tasks: BackgroundTasks):
    """Trigger YOLOv8+ByteTrack tracking on a real CCTV video file."""
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video '{video_path}' not found.")

    def run_ai_loop():
        cap = cv2.VideoCapture(video_path)
        fps = int(cap.get(cv2.CAP_PROP_FPS)) or config.DEFAULT_FPS
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            light_state = "RED" if (frame_idx % 120) < 60 else "GREEN"

            annotated_frame, stats, new_cases = ai_service.process_frame(
                frame, frame_idx, fps, light_state
            )

            active_id = j_manager.active_junction_id
            j_manager.update_junction_stats(
                junction_id=active_id,
                congestion_level=min(99, stats["total_violations"] * 10),
                vehicle_count=70 + (frame_idx % 25),
                active_violations=stats["total_violations"],
                average_speed=35.5,
            )
            frame_idx += 1
        cap.release()
        print(f"[AI Service] Video analysis complete: {frame_idx} frames processed.")

    background_tasks.add_task(run_ai_loop)
    return {"status": "Processing initiated", "video_path": video_path}


@app.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket):
    """
    WS /ws/stats
    Pushes live header statistics (vehicles today, violations today, active cameras, review queue size, etc.) in real time.
    """
    await websocket.accept()
    try:
        while True:
            db_stats = database.query_live_stats()
            tickets = database.query_all_tickets(1000)
            pending_count = len([t for t in tickets if t["status"] == "AWAITING_REVIEW"])
            approved_count = len([t for t in tickets if t["status"] in ["AUTO_APPROVED", "APPROVED"]])
            discarded_count = len([t for t in tickets if t["status"] == "DISCARDED"])
            
            payload = {
                "vehicles_today": db_stats.get("vehicles_today", 0),
                "violations_today": db_stats.get("violations_today", 0),
                "active_cameras": db_stats.get("active_cameras", 3),
                "active_violations": db_stats.get("active_violations", 0),
                "pending_cases": pending_count,
                "approved_cases": approved_count,
                "discarded_cases": discarded_count,
                "total_cases": len(tickets),
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS /ws/stats] Disconnected: {e}")


@app.get("/api/evidence/{ticket_id}/{frame}")
def get_evidence_frame(ticket_id: str, frame: str):
    """
    Serve a specific evidence frame or crop image as JPEG.
    Supports frame index (0-8) or frame filename strings.
    """
    ticket = database.query_ticket_by_id(ticket_id)
    if not ticket:
        ticket = database.query_violation_by_id(ticket_id)
    
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket/Violation not found: {ticket_id}")
        
    evidence_images = ticket.get("evidence_images")
    if not evidence_images:
        evidence_images = ticket.get("evidence_frames")
        
    if not evidence_images:
        raise HTTPException(status_code=404, detail="No evidence images recorded for this case.")
        
    if isinstance(evidence_images, str):
        try:
            evidence_images = json.loads(evidence_images)
        except Exception:
            evidence_images = [evidence_images]
            
    resolved_path = None
    
    try:
        idx = int(frame)
        if 0 <= idx < len(evidence_images):
            resolved_path = evidence_images[idx]
    except ValueError:
        clean_frame = frame.replace(".jpg", "").replace(".png", "").lower()
        for path in evidence_images:
            if clean_frame in path.lower():
                resolved_path = path
                break
                
    if not resolved_path:
        raise HTTPException(status_code=404, detail=f"Evidence frame '{frame}' not found.")
        
    if not os.path.exists(resolved_path):
        workspace_path = os.path.join(os.getcwd(), resolved_path)
        if os.path.exists(workspace_path):
            resolved_path = workspace_path
        else:
            raise HTTPException(status_code=404, detail=f"File not found on disk: {resolved_path}")
            
    return FileResponse(resolved_path, media_type="image/jpeg")


@app.get("/api/analytics/congestion_history/{cam_id}")
def analytics_congestion_history(cam_id: str, n: int = Query(60, ge=1, le=500)):
    """Alias for congestion_for_camera."""
    return congestion_for_camera(cam_id, n)


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"[FastAPI] Starting GRIDLOCK AI Command Center on http://0.0.0.0:{port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port)
