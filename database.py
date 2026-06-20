# database.py
# Central SQLite persistence layer for GRIDLOCK AI.
# All violations, tickets, junction metrics, and alerts are stored here.
# Usage:
#   import database
#   database.init_db()
#   database.insert_violation(...)
#   database.query_live_stats()

import sqlite3
import json
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gridlock.db")

# ─────────────────────────────────────────────
# CONNECTION HELPER
# ─────────────────────────────────────────────

def _get_conn():
    """Open a connection with row_factory for dict-style access."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")   # Workaround for OneDrive file locking
    conn.execute("PRAGMA synchronous=NORMAL") # Faster writes, safe enough for demo
    return conn

# ─────────────────────────────────────────────
# SCHEMA INIT
# ─────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist. Safe to call multiple times."""
    conn = _get_conn()
    cur = conn.cursor()

    cur.executescript("""
        -- ── Original tables ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS violations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_id        TEXT UNIQUE NOT NULL,
            vehicle_id          TEXT,
            violation_type      TEXT,
            timestamp           TEXT,
            confidence          REAL,
            bbox                TEXT,
            frame_number        INTEGER,
            plate_number        TEXT,
            ticket_id           TEXT,
            location            TEXT,
            junction_id         TEXT,
            evidence_score      REAL,
            status              TEXT DEFAULT 'AWAITING_REVIEW',
            fine_amount         INTEGER DEFAULT 1000,
            discard_reason      TEXT,
            tracking_confidence REAL,
            ocr_confidence      REAL,
            explainability_notes TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id       TEXT UNIQUE NOT NULL,
            violation_id    TEXT NOT NULL,
            vehicle_id      TEXT,
            plate_number    TEXT,
            violation_type  TEXT,
            timestamp       TEXT,
            location        TEXT,
            confidence      REAL,
            evidence_score  REAL,
            status          TEXT DEFAULT 'AWAITING_REVIEW',
            fine_amount     INTEGER DEFAULT 1000,
            discard_reason  TEXT,
            tracking_confidence REAL,
            ocr_confidence  REAL,
            explainability_notes TEXT,
            evidence_images TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS junction_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            junction_id     TEXT NOT NULL,
            junction_name   TEXT,
            congestion_level INTEGER,
            vehicle_count   INTEGER,
            active_violations INTEGER,
            average_speed   REAL,
            risk_score      INTEGER,
            recorded_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_time  TEXT,
            title       TEXT,
            text        TEXT,
            type        TEXT,
            violation_id TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- ── Canonical schema (user-specified) ────────────────────────────────
        CREATE TABLE IF NOT EXISTS vehicles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id  TEXT,
            camera_id   TEXT,
            type        TEXT,
            speed_kmh   REAL,
            direction   TEXT,
            plate_text  TEXT,
            first_seen  TIMESTAMP DEFAULT (datetime('now')),
            last_seen   TIMESTAMP DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS congestion_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id       TEXT,
            vehicle_count   INTEGER,
            avg_speed       REAL,
            congestion_pct  REAL,
            recorded_at     TIMESTAMP DEFAULT (datetime('now'))
        );

        -- ── Indexes ───────────────────────────────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_violations_timestamp ON violations(timestamp);
        CREATE INDEX IF NOT EXISTS idx_violations_status ON violations(status);
        CREATE INDEX IF NOT EXISTS idx_violations_junction ON violations(junction_id);
        CREATE INDEX IF NOT EXISTS idx_tickets_violation ON tickets(violation_id);
        CREATE INDEX IF NOT EXISTS idx_junction_stats_id ON junction_stats(junction_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
        CREATE INDEX IF NOT EXISTS idx_vehicles_camera ON vehicles(camera_id);
        CREATE INDEX IF NOT EXISTS idx_vehicles_first_seen ON vehicles(first_seen);
        CREATE INDEX IF NOT EXISTS idx_congestion_camera ON congestion_log(camera_id);
        CREATE INDEX IF NOT EXISTS idx_congestion_recorded ON congestion_log(recorded_at);
    """)

    conn.commit()
    conn.close()
    print(f"[Database] SQLite initialized at: {DB_PATH}")


# ─────────────────────────────────────────────
# VIOLATION WRITES
# ─────────────────────────────────────────────

def insert_violation(data: dict):
    """
    Insert a new violation row. Silently ignores duplicate violation_id.
    Args:
        data: dict with keys matching violations table columns.
    """
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO violations (
                violation_id, vehicle_id, violation_type, timestamp,
                confidence, bbox, frame_number, plate_number, ticket_id,
                location, junction_id, evidence_score, status, fine_amount,
                discard_reason, tracking_confidence, ocr_confidence, explainability_notes
            ) VALUES (
                :violation_id, :vehicle_id, :violation_type, :timestamp,
                :confidence, :bbox, :frame_number, :plate_number, :ticket_id,
                :location, :junction_id, :evidence_score, :status, :fine_amount,
                :discard_reason, :tracking_confidence, :ocr_confidence, :explainability_notes
            )
        """, {
            "violation_id":          data.get("violation_id", ""),
            "vehicle_id":            data.get("vehicle_id", ""),
            "violation_type":        data.get("violation_type", ""),
            "timestamp":             data.get("timestamp", datetime.now().isoformat()),
            "confidence":            data.get("confidence", 0.0),
            "bbox":                  json.dumps(data.get("bbox", [])),
            "frame_number":          data.get("frame_number", 0),
            "plate_number":          data.get("plate_number", ""),
            "ticket_id":             data.get("ticket_id", ""),
            "location":              data.get("location", ""),
            "junction_id":           data.get("junction_id", ""),
            "evidence_score":        data.get("evidence_score", 0.0),
            "status":                data.get("status", "AWAITING_REVIEW"),
            "fine_amount":           data.get("fine_amount", 1000),
            "discard_reason":        data.get("discard_reason", None),
            "tracking_confidence":   data.get("tracking_confidence", 0.0),
            "ocr_confidence":        data.get("ocr_confidence", 0.0),
            "explainability_notes":  json.dumps(data.get("explainability_notes", [])),
        })
        conn.commit()
    except Exception as e:
        print(f"[Database] insert_violation error: {e}")
    finally:
        conn.close()


def update_violation_status(violation_id: str, status: str, reason: str = None, notes: list = None):
    """Update status (APPROVED/DISCARDED/AWAITING_REVIEW) for a violation + ticket row."""
    conn = _get_conn()
    try:
        # Fetch current notes
        row = conn.execute(
            "SELECT explainability_notes FROM violations WHERE violation_id=?",
            (violation_id,)
        ).fetchone()
        current_notes = json.loads(row["explainability_notes"]) if row else []
        if notes:
            current_notes.extend(notes)

        conn.execute("""
            UPDATE violations
            SET status=?, discard_reason=?, explainability_notes=?
            WHERE violation_id=?
        """, (status, reason, json.dumps(current_notes), violation_id))

        conn.execute("""
            UPDATE tickets
            SET status=?, discard_reason=?, explainability_notes=?
            WHERE violation_id=?
        """, (status, reason, json.dumps(current_notes), violation_id))

        conn.commit()
        return True
    except Exception as e:
        print(f"[Database] update_violation_status error: {e}")
        return False
    finally:
        conn.close()


# ─────────────────────────────────────────────
# TICKET WRITES
# ─────────────────────────────────────────────

def insert_ticket(data: dict):
    """
    Insert a ticket row. Silently ignores duplicate ticket_id.
    """
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO tickets (
                ticket_id, violation_id, vehicle_id, plate_number,
                violation_type, timestamp, location, confidence,
                evidence_score, status, fine_amount, discard_reason,
                tracking_confidence, ocr_confidence, explainability_notes, evidence_images
            ) VALUES (
                :ticket_id, :violation_id, :vehicle_id, :plate_number,
                :violation_type, :timestamp, :location, :confidence,
                :evidence_score, :status, :fine_amount, :discard_reason,
                :tracking_confidence, :ocr_confidence, :explainability_notes, :evidence_images
            )
        """, {
            "ticket_id":             data.get("ticket_id", ""),
            "violation_id":          data.get("violation_id", ""),
            "vehicle_id":            data.get("vehicle_id", ""),
            "plate_number":          data.get("plate_number", ""),
            "violation_type":        data.get("violation_type", ""),
            "timestamp":             data.get("timestamp", datetime.now().isoformat()),
            "location":              data.get("location", ""),
            "confidence":            data.get("confidence", 0.0),
            "evidence_score":        data.get("evidence_score", 0.0),
            "status":                data.get("status", "AWAITING_REVIEW"),
            "fine_amount":           data.get("fine_amount", 1000),
            "discard_reason":        data.get("discard_reason", None),
            "tracking_confidence":   data.get("tracking_confidence", 0.0),
            "ocr_confidence":        data.get("ocr_confidence", 0.0),
            "explainability_notes":  json.dumps(data.get("explainability_notes", [])),
            "evidence_images":       json.dumps(data.get("evidence_images", [])),
        })
        conn.commit()
    except Exception as e:
        print(f"[Database] insert_ticket error: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# JUNCTION STATS WRITES
# ─────────────────────────────────────────────

def upsert_junction_stats(junction_id: str, junction_name: str,
                          congestion_level: int = None, vehicle_count: int = None,
                          active_violations: int = None, average_speed: float = None,
                          risk_score: int = None):
    """Insert a timestamped junction snapshot row (history)."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO junction_stats
                (junction_id, junction_name, congestion_level, vehicle_count,
                 active_violations, average_speed, risk_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (junction_id, junction_name, congestion_level, vehicle_count,
              active_violations, average_speed, risk_score))
        conn.commit()
    except Exception as e:
        print(f"[Database] upsert_junction_stats error: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# ALERT WRITES
# ─────────────────────────────────────────────

def insert_alert(title: str, text: str, alert_type: str, violation_id: str = None):
    """Add an alert to the DB-backed alert timeline."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO alerts (alert_time, title, text, type, violation_id)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%H:%M:%S"), title, text, alert_type, violation_id))
        conn.commit()
    except Exception as e:
        print(f"[Database] insert_alert error: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# QUERY FUNCTIONS
# ─────────────────────────────────────────────

def _row_to_dict(row):
    """Convert sqlite3.Row to a plain dict."""
    if row is None:
        return None
    d = dict(row)
    # Deserialize JSON text fields
    for field in ("bbox", "explainability_notes", "evidence_images"):
        if field in d and d[field]:
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


def query_live_stats():
    """
    Aggregate query for the Command Center header stats.
    Returns real counts from the DB.
    """
    conn = _get_conn()
    today = date.today().isoformat()
    try:
        vehicles_today = conn.execute(
            "SELECT COALESCE(SUM(vehicle_count), 0) FROM junction_stats WHERE DATE(recorded_at)=?",
            (today,)
        ).fetchone()[0]

        violations_today = conn.execute(
            "SELECT COUNT(*) FROM violations WHERE DATE(timestamp)=?",
            (today,)
        ).fetchone()[0]

        avg_speed = conn.execute(
            "SELECT COALESCE(AVG(average_speed), 0.0) FROM junction_stats WHERE DATE(recorded_at)=?",
            (today,)
        ).fetchone()[0]

        # Most dangerous junction today (most violations)
        dangerous_row = conn.execute("""
            SELECT location, COUNT(*) as cnt
            FROM violations
            WHERE DATE(timestamp)=?
            GROUP BY location
            ORDER BY cnt DESC
            LIMIT 1
        """, (today,)).fetchone()
        most_dangerous = dangerous_row["location"] if dangerous_row else "Silk Board Junction"

        # Active violation counts
        active_violations = conn.execute(
            "SELECT COUNT(*) FROM violations WHERE status='AWAITING_REVIEW'"
        ).fetchone()[0]

        return {
            "vehicles_today":         int(vehicles_today),
            "violations_today":       int(violations_today),
            "average_speed_kmph":     round(float(avg_speed), 1),
            "most_dangerous_junction": most_dangerous,
            "active_violations":      int(active_violations),
        }
    except Exception as e:
        print(f"[Database] query_live_stats error: {e}")
        return {
            "vehicles_today": 0,
            "violations_today": 0,
            "average_speed_kmph": 0.0,
            "most_dangerous_junction": "N/A",
            "active_violations": 0,
        }
    finally:
        conn.close()


def query_recent_alerts(n: int = 10):
    """Return the N most recent alerts as list of dicts."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [_row_to_dict(r) for r in reversed(rows)]
    except Exception as e:
        print(f"[Database] query_recent_alerts error: {e}")
        return []
    finally:
        conn.close()


def query_all_violations(limit: int = 200):
    """Return recent violations as list of dicts."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM violations ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[Database] query_all_violations error: {e}")
        return []
    finally:
        conn.close()


def query_all_tickets(limit: int = 200):
    """Return recent tickets as list of dicts."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[Database] query_all_tickets error: {e}")
        return []
    finally:
        conn.close()


def query_violation_by_id(violation_id: str):
    """Return a single violation + its ticket data merged, as a dict."""
    conn = _get_conn()
    try:
        v_row = conn.execute(
            "SELECT * FROM violations WHERE violation_id=?", (violation_id,)
        ).fetchone()
        if not v_row:
            # Try by ticket_id
            v_row = conn.execute(
                "SELECT * FROM violations WHERE ticket_id=?", (violation_id,)
            ).fetchone()
        if not v_row:
            return None

        result = _row_to_dict(v_row)

        # Merge ticket data if available
        t_row = conn.execute(
            "SELECT * FROM tickets WHERE violation_id=? OR ticket_id=?",
            (result["violation_id"], violation_id)
        ).fetchone()
        if t_row:
            t_dict = _row_to_dict(t_row)
            # Merge ticket fields that aren't already in violation
            for k, v in t_dict.items():
                if k not in result or result[k] is None:
                    result[k] = v

        return result
    except Exception as e:
        print(f"[Database] query_violation_by_id error: {e}")
        return None
    finally:
        conn.close()


def query_violations_by_plate(plate_number: str):
    """Return all violations for a given plate number."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM violations WHERE plate_number=? ORDER BY id DESC",
            (plate_number,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[Database] query_violations_by_plate error: {e}")
        return []
    finally:
        conn.close()


def query_junction_history(junction_id: str, last_n: int = 60):
    """Return last N metric snapshots for a junction (for trend charts)."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM junction_stats
            WHERE junction_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (junction_id, last_n)).fetchall()
        return [_row_to_dict(r) for r in reversed(rows)]
    except Exception as e:
        print(f"[Database] query_junction_history error: {e}")
        return []
    finally:
        conn.close()


def query_violation_type_breakdown():
    """Return COUNT per violation_type for analytics charts."""
    conn = _get_conn()
    today = date.today().isoformat()
    try:
        rows = conn.execute("""
            SELECT violation_type, COUNT(*) as count
            FROM violations
            WHERE DATE(timestamp)=?
            GROUP BY violation_type
            ORDER BY count DESC
        """, (today,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[Database] query_violation_type_breakdown error: {e}")
        return []
    finally:
        conn.close()


def query_status_breakdown():
    """Return COUNT per enforcement status."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM tickets
            GROUP BY status
        """).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[Database] query_status_breakdown error: {e}")
        return []
    finally:
        conn.close()


# ─────────────────────────────────────────────
# VEHICLES TABLE WRITES
# ─────────────────────────────────────────────

def upsert_vehicle(vehicle_id: str, camera_id: str, v_type: str,
                   speed_kmh: float, direction: str, plate_text: str = ""):
    """
    Insert a new vehicle detection or update its last_seen + speed if it already exists
    in this session (same vehicle_id + camera_id).
    """
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM vehicles WHERE vehicle_id=? AND camera_id=?",
            (str(vehicle_id), camera_id)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE vehicles
                SET last_seen=datetime('now'), speed_kmh=?, direction=?
                WHERE vehicle_id=? AND camera_id=?
            """, (speed_kmh, direction, str(vehicle_id), camera_id))
        else:
            conn.execute("""
                INSERT INTO vehicles (vehicle_id, camera_id, type, speed_kmh, direction, plate_text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(vehicle_id), camera_id, v_type, speed_kmh, direction, plate_text))
        conn.commit()
    except Exception as e:
        print(f"[Database] upsert_vehicle error: {e}")
    finally:
        conn.close()


def insert_congestion_snapshot(camera_id: str, vehicle_count: int,
                               avg_speed: float, congestion_pct: float):
    """Write a congestion_log row for a single camera at the current timestamp."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO congestion_log (camera_id, vehicle_count, avg_speed, congestion_pct)
            VALUES (?, ?, ?, ?)
        """, (camera_id, vehicle_count, avg_speed, congestion_pct))
        conn.commit()
    except Exception as e:
        print(f"[Database] insert_congestion_snapshot error: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# CANONICAL QUERY FUNCTIONS
# ─────────────────────────────────────────────

def query_stats_summary():
    """
    GET /api/stats/summary
    Returns vehicles_today (from vehicles table), violations_today (COUNT from violations),
    and active_cameras (DISTINCT camera_ids seen in congestion_log today).
    All numbers are live SQL aggregates — zero hardcoded values.
    """
    conn = _get_conn()
    today = date.today().isoformat()
    try:
        # Count distinct vehicles observed today across all cameras
        vehicles_today = conn.execute(
            "SELECT COUNT(*) FROM vehicles WHERE DATE(first_seen)=?",
            (today,)
        ).fetchone()[0]

        violations_today = conn.execute(
            "SELECT COUNT(*) FROM violations WHERE DATE(timestamp)=?",
            (today,)
        ).fetchone()[0]

        active_cameras = conn.execute(
            "SELECT COUNT(DISTINCT camera_id) FROM congestion_log WHERE DATE(recorded_at)=?",
            (today,)
        ).fetchone()[0]

        return {
            "vehicles_today":  int(vehicles_today),
            "violations_today": int(violations_today),
            "active_cameras":  int(active_cameras),
        }
    except Exception as e:
        print(f"[Database] query_stats_summary error: {e}")
        return {"vehicles_today": 0, "violations_today": 0, "active_cameras": 0}
    finally:
        conn.close()


def query_violations_paginated(page: int = 1, per_page: int = 50,
                                status: str = None, camera_id: str = None):
    """
    GET /api/violations
    Returns paginated violations from the violations table.
    Optional filters: status, camera_id (mapped from junction_id).
    """
    conn = _get_conn()
    offset = (page - 1) * per_page
    where_clauses = []
    params: list = []

    if status:
        where_clauses.append("status=?")
        params.append(status)
    if camera_id:
        # camera_id maps to junction_id in the legacy violations table
        where_clauses.append("(junction_id=? OR violation_id LIKE ?)")
        params.extend([camera_id, f"%{camera_id}%"])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM violations {where_sql}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM violations {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()

        return {
            "page":         page,
            "per_page":     per_page,
            "total":        int(total),
            "total_pages":  max(1, -(-total // per_page)),  # ceil div
            "violations":   [_row_to_dict(r) for r in rows],
        }
    except Exception as e:
        print(f"[Database] query_violations_paginated error: {e}")
        return {"page": 1, "per_page": per_page, "total": 0, "total_pages": 1, "violations": []}
    finally:
        conn.close()


def query_congestion_history(camera_id: str, last_n: int = 60):
    """
    GET /api/congestion/{cam_id}
    Returns last_n congestion_log rows for the given camera.
    Falls back to junction_stats if congestion_log is empty for backward compat.
    """
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT camera_id, vehicle_count, avg_speed, congestion_pct, recorded_at
            FROM congestion_log
            WHERE camera_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (camera_id, last_n)).fetchall()

        if rows:
            result = [dict(r) for r in reversed(rows)]
        else:
            # Fallback: read from junction_stats (old data)
            rows2 = conn.execute("""
                SELECT junction_id AS camera_id, vehicle_count,
                       average_speed AS avg_speed,
                       congestion_level AS congestion_pct,
                       recorded_at
                FROM junction_stats
                WHERE junction_id=?
                ORDER BY id DESC
                LIMIT ?
            """, (camera_id, last_n)).fetchall()
            result = [dict(r) for r in reversed(rows2)]

        return result
    except Exception as e:
        print(f"[Database] query_congestion_history error: {e}")
        return []
    finally:
        conn.close()


def query_ticket_by_id(ticket_id: str):
    """
    GET /api/tickets/{ticket_id}
    Returns a single ticket + merged violation data.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id=? OR violation_id=?",
            (ticket_id, ticket_id)
        ).fetchone()
        if not row:
            return None
        result = _row_to_dict(row)
        # Merge violation fields
        v_row = conn.execute(
            "SELECT * FROM violations WHERE violation_id=?",
            (result.get("violation_id", ticket_id),)
        ).fetchone()
        if v_row:
            for k, v in _row_to_dict(v_row).items():
                if k not in result or result[k] is None:
                    result[k] = v
        return result
    except Exception as e:
        print(f"[Database] query_ticket_by_id error: {e}")
        return None
    finally:
        conn.close()


def get_latest_event_id():
    """Return the id of the most recent alert row. Used by WebSocket event tail."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT MAX(id) FROM alerts").fetchone()
        return row[0] or 0
    except Exception:
        return 0
    finally:
        conn.close()


def query_alerts_since(last_id: int, limit: int = 20):
    """Return alert rows with id > last_id (for WebSocket event push)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE id > ? ORDER BY id ASC LIMIT ?",
            (last_id, limit)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[Database] query_alerts_since error: {e}")
        return []
    finally:
        conn.close()


def query_latest_camera_stats(junction_ids: list):
    """
    Query the database for the latest junction_stats snapshot of each junction.
    """
    conn = _get_conn()
    stats = {}
    try:
        for j_id in junction_ids:
            row = conn.execute("""
                SELECT * FROM junction_stats
                WHERE junction_id = ?
                ORDER BY id DESC LIMIT 1
            """, (j_id,)).fetchone()
            if row:
                stats[j_id] = dict(row)
    except Exception as e:
        print(f"[Database] query_latest_camera_stats error: {e}")
    finally:
        conn.close()
    return stats


def query_active_violations_count(junction_id: str):
    """Count active violations AWAITING_REVIEW for a given junction."""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT COUNT(*) FROM violations
            WHERE (junction_id=? OR location LIKE ?) AND status='AWAITING_REVIEW'
        """, (junction_id, f"%{junction_id}%")).fetchone()
        return row[0] if row else 0
    except Exception as e:
        print(f"[Database] query_active_violations_count error: {e}")
        return 0
    finally:
        conn.close()

