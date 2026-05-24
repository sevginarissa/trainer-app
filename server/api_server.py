"""
Antrenör API server
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• REST bridge  — /api/mcp/{tool_name}  (direct tool calls from browser/app)
• Claude proxy — /api/chat             (raw Anthropic proxy; client handles loop)
• Agent run    — /api/chat/run         (server-side agentic loop; returns final text)
• WhatsApp     — /whatsapp/webhook     (Twilio webhook; processes async via BackgroundTasks)
• Static       — /                     (serves app/ directory for Lightsail deployment)

Run: uvicorn server.api_server:app --reload --port 8000
     (from the trainer-app/ root)
"""

import asyncio
import json
import logging
import os
import sqlite3
import traceback
from datetime import datetime, date as _date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("antrenor.api")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# ─── Config ───────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY    = os.getenv('ANTHROPIC_API_KEY')
ANTHROPIC_URL        = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL         = "claude-sonnet-4-20250514"

TWILIO_ACCOUNT_SID   = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN    = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_FROM = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')

_default_db = Path(__file__).parent.parent / "db" / "trainer.db"
DB_PATH     = Path(os.getenv("DB_PATH", str(_default_db)))
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"
APP_DIR     = Path(__file__).parent.parent / "app"

# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="Antrenör API")

_cors_env = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:4173,http://localhost:3000",
)
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── DB helpers ───────────────────────────────────────────────────────────────


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


def _migrate_db() -> None:
    """Apply schema migrations for existing DBs (ADD COLUMN is idempotent)."""
    migrations = [
        "ALTER TABLE students ADD COLUMN price_per_lesson INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE lessons ADD COLUMN late_cancel INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE lessons ADD COLUMN is_free INTEGER NOT NULL DEFAULT 0",
    ]
    conn = _db()
    try:
        for stmt in migrations:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
    finally:
        conn.close()


# ─── Time helpers (for open-slot arithmetic) ──────────────────────────────────


def _time_to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _min_to_time(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _subtract_intervals(avail: list, blocked: list) -> list:
    """Return avail minus blocked. Each interval is (start_min, end_min)."""
    result = list(avail)
    for bs, be in blocked:
        new_result = []
        for s, e in result:
            if be <= s or bs >= e:
                new_result.append((s, e))
            else:
                if s < bs:
                    new_result.append((s, bs))
                if be < e:
                    new_result.append((be, e))
        result = new_result
    return result


# ─── Tool implementations ─────────────────────────────────────────────────────

_DAY_MAP = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}


def tool_get_students(args: dict):
    include_inactive = bool(args.get("include_inactive", False))
    conn = _db()
    try:
        if include_inactive:
            students = _rows(conn.execute(
                "SELECT id, name, lesson_price, price_per_lesson, active FROM students ORDER BY active DESC, name"
            ).fetchall())
        else:
            students = _rows(conn.execute(
                "SELECT id, name, lesson_price, price_per_lesson, active FROM students WHERE active=1 ORDER BY name"
            ).fetchall())
        for s in students:
            s["schedules"] = _rows(conn.execute(
                "SELECT day_of_week, lesson_time FROM schedules "
                "WHERE student_id=? AND active=1 ORDER BY day_of_week",
                (s["id"],),
            ).fetchall())
        return students
    finally:
        conn.close()


def tool_get_pending_lessons(args: dict):
    since = args.get("since_datetime", "2000-01-01T00:00:00")
    conn = _db()
    try:
        return _rows(conn.execute(
            """
            SELECT l.id, l.student_id, s.name AS student_name,
                   l.scheduled_at, l.happened, l.late_cancel, l.paid
              FROM lessons l
              JOIN students s ON s.id = l.student_id
             WHERE l.scheduled_at >= ?
               AND l.scheduled_at <= datetime('now')
               AND l.happened IS NULL
             ORDER BY l.scheduled_at
            """,
            (since,),
        ).fetchall())
    finally:
        conn.close()


def tool_get_pending_overrides(_: dict):
    conn = _db()
    try:
        return _rows(conn.execute(
            """
            SELECT so.id, so.student_id, s.name AS student_name,
                   so.day_of_week, so.lesson_time, so.override_week, so.applied
              FROM schedule_overrides so
              JOIN students s ON s.id = so.student_id
             WHERE so.applied = 0
             ORDER BY so.override_week, so.created_at
            """
        ).fetchall())
    finally:
        conn.close()


def tool_get_todays_lessons(_: dict):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _db()
    try:
        return _rows(conn.execute(
            """
            SELECT l.id, l.student_id, s.name AS student_name,
                   l.scheduled_at, l.happened, l.late_cancel, l.paid
              FROM lessons l
              JOIN students s ON s.id = l.student_id
             WHERE DATE(l.scheduled_at) = ?
             ORDER BY l.scheduled_at
            """,
            (today,),
        ).fetchall())
    finally:
        conn.close()


def _query_pending_requests(freed_date: str, freed_time: str, conn) -> list:
    return _rows(conn.execute(
        """
        SELECT pr.id, pr.student_id, s.name AS student_name,
               pr.requested_date, pr.requested_time, pr.flexible_time, pr.notes
          FROM pending_requests pr
          JOIN students s ON s.id = pr.student_id
         WHERE pr.fulfilled = 0
           AND pr.requested_date = ?
           AND (pr.flexible_time = 1 OR pr.requested_time = ?)
         ORDER BY pr.created_at
        """,
        (freed_date, freed_time),
    ).fetchall())


def tool_mark_lesson(args: dict):
    """
    3-state status model:
      status="happened"     → happened=1, late_cancel=0
      status="late_cancel"  → happened=0, late_cancel=1  (counts as session)
      status="cancelled"    → happened=0, late_cancel=0  (doesn't count)
    Legacy boolean 'happened' field still accepted for backwards compat.
    """
    lesson_id = args.get("lesson_id")
    if lesson_id is None:
        raise ValueError("lesson_id is required")

    status = args.get("status")
    if status is not None:
        if status == "happened":
            happened, late_cancel = 1, 0
        elif status == "late_cancel":
            happened, late_cancel = 0, 1
        else:
            happened, late_cancel = 0, 0
    else:
        # Legacy boolean
        happened = 1 if args.get("happened") else 0
        late_cancel = 0

    conn = _db()
    try:
        conn.execute(
            "UPDATE lessons SET happened=?, late_cancel=? WHERE id=?",
            (happened, late_cancel, lesson_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if row is None:
            raise ValueError(f"Lesson {lesson_id} not found")
        result = dict(row)
        if not happened:
            scheduled_at = result.get("scheduled_at", "")
            result["freed_slot_matches"] = _query_pending_requests(
                scheduled_at[:10], scheduled_at[11:16], conn
            )
        return result
    finally:
        conn.close()


def tool_add_pending_request(args: dict):
    student_id     = args["student_id"]
    requested_date = args["requested_date"]
    requested_time = args.get("requested_time")
    flexible_time  = 1 if args.get("flexible_time") else 0
    notes          = args.get("notes", "")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO pending_requests (student_id, requested_date, requested_time, flexible_time, notes)"
            " VALUES (?,?,?,?,?)",
            (student_id, requested_date, requested_time, flexible_time, notes),
        )
        conn.commit()
        row = conn.execute(
            "SELECT pr.*, s.name AS student_name FROM pending_requests pr "
            "JOIN students s ON s.id = pr.student_id WHERE pr.id=?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def tool_check_pending_requests(args: dict):
    freed_date = args["freed_date"]
    freed_time = args.get("freed_time", "")
    conn = _db()
    try:
        return _query_pending_requests(freed_date, freed_time, conn)
    finally:
        conn.close()


def tool_get_pending_requests(_: dict):
    conn = _db()
    try:
        return _rows(conn.execute(
            """
            SELECT pr.id, pr.student_id, s.name AS student_name,
                   pr.requested_date, pr.requested_time, pr.flexible_time,
                   pr.notes, pr.fulfilled, pr.created_at
              FROM pending_requests pr
              JOIN students s ON s.id = pr.student_id
             WHERE pr.fulfilled = 0
             ORDER BY pr.requested_date, pr.created_at
            """
        ).fetchall())
    finally:
        conn.close()


def tool_add_credit(args: dict):
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO credits (student_id, amount, reason) VALUES (?,?,?)",
            (args["student_id"], args["amount"], args.get("reason", "")),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM credits WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


def tool_apply_payment(args: dict):
    """Mark specific lessons as paid (legacy; use record_payment for lira-based payments)."""
    student_id    = args["student_id"]
    lesson_ids    = args["lesson_ids"]
    session_count = len(lesson_ids)
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM students WHERE id=?", (student_id,)).fetchone():
            raise ValueError(f"Student {student_id} not found")
        now = datetime.utcnow().isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO payments (student_id, amount) VALUES (?,?)",
            (student_id, session_count),
        )
        payment_id = cur.lastrowid
        for lid in lesson_ids:
            conn.execute(
                "UPDATE lessons SET paid=1, paid_at=? WHERE id=? AND student_id=?",
                (now, lid, student_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO lesson_payments (payment_id, lesson_id) VALUES (?,?)",
                (payment_id, lid),
            )
        conn.commit()
        return {"payment_id": payment_id, "student_id": student_id,
                "lesson_ids": lesson_ids, "session_count": session_count}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def tool_record_payment(args: dict):
    """
    Record a cash payment in lira. Automatically marks the oldest unpaid lessons as paid.
    amount_lira / price_per_lesson = number of lessons to mark paid.
    """
    student_id  = args["student_id"]
    amount_lira = int(args["amount_lira"])
    conn = _db()
    try:
        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            raise ValueError(f"Student {student_id} not found")
        price = int(student["price_per_lesson"])
        if price <= 0:
            raise ValueError(
                "price_per_lesson is 0 — call update_student_price first to set the per-session rate."
            )
        lessons_to_pay = amount_lira // price
        if lessons_to_pay <= 0:
            raise ValueError(f"amount_lira={amount_lira} is less than price_per_lesson={price}")

        # Oldest unpaid confirmed/late-cancel lessons first
        unpaid = conn.execute(
            "SELECT id FROM lessons "
            "WHERE student_id=? AND (happened=1 OR late_cancel=1) AND paid=0 AND is_free=0"
            " ORDER BY scheduled_at ASC LIMIT ?",
            (student_id, lessons_to_pay),
        ).fetchall()
        lesson_ids = [r[0] for r in unpaid]
        now = datetime.utcnow().isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO payments (student_id, amount) VALUES (?,?)",
            (student_id, len(lesson_ids)),
        )
        payment_id = cur.lastrowid
        for lid in lesson_ids:
            conn.execute("UPDATE lessons SET paid=1, paid_at=? WHERE id=?", (now, lid))
            conn.execute(
                "INSERT OR IGNORE INTO lesson_payments (payment_id, lesson_id) VALUES (?,?)",
                (payment_id, lid),
            )
        conn.commit()
        return {
            "payment_id":      payment_id,
            "amount_lira":     amount_lira,
            "price_per_lesson": price,
            "lessons_paid":    len(lesson_ids),
            "lesson_ids":      lesson_ids,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def tool_update_student_price(args: dict):
    """Set the per-session price (in lira) for a student."""
    student_id       = args["student_id"]
    price_per_lesson = int(args["price_per_lesson"])
    conn = _db()
    try:
        conn.execute(
            "UPDATE students SET price_per_lesson=? WHERE id=?",
            (price_per_lesson, student_id),
        )
        conn.commit()
        return {"student_id": student_id, "price_per_lesson": price_per_lesson}
    finally:
        conn.close()


def tool_update_schedule(args: dict):
    student_id, day, time = args["student_id"], args["day"], args["time"]
    override_week = args.get("override_week")
    conn = _db()
    try:
        if override_week is None:
            conn.execute(
                "UPDATE schedules SET active=0 WHERE student_id=? AND day_of_week=? AND active=1",
                (student_id, day),
            )
            conn.execute(
                "INSERT INTO schedules (student_id, day_of_week, lesson_time) VALUES (?,?,?)",
                (student_id, day, time),
            )
            conn.commit()
            return {"status": "permanent_schedule_updated",
                    "student_id": student_id, "day": day, "time": time}
        cur = conn.execute(
            "INSERT INTO schedule_overrides (student_id, day_of_week, lesson_time, override_week) VALUES (?,?,?,?)",
            (student_id, day, time, override_week),
        )
        conn.commit()
        return dict(conn.execute(
            "SELECT * FROM schedule_overrides WHERE id=?", (cur.lastrowid,)
        ).fetchone())
    finally:
        conn.close()


def tool_generate_balance(args: dict):
    student_id = args["student_id"]
    conn = _db()
    try:
        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            raise ValueError(f"Student {student_id} not found")

        credits_total = int(conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM credits WHERE student_id=?", (student_id,)
        ).fetchone()[0])

        # Sessions that count for billing: happened OR late_cancel (and not free)
        sessions_occurred = conn.execute(
            "SELECT COUNT(*) FROM lessons "
            "WHERE student_id=? AND (happened=1 OR late_cancel=1) AND is_free=0",
            (student_id,),
        ).fetchone()[0]

        confirmed_paid = conn.execute(
            "SELECT COUNT(*) FROM lessons "
            "WHERE student_id=? AND happened=1 AND paid=1 AND is_free=0",
            (student_id,),
        ).fetchone()[0]
        confirmed_unpaid = conn.execute(
            "SELECT COUNT(*) FROM lessons "
            "WHERE student_id=? AND happened=1 AND paid=0 AND is_free=0",
            (student_id,),
        ).fetchone()[0]
        late_cancel_count = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND late_cancel=1",
            (student_id,),
        ).fetchone()[0]
        unconfirmed = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened IS NULL",
            (student_id,),
        ).fetchone()[0]

        balance = credits_total - sessions_occurred
        unpaid_lesson_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM lessons "
                "WHERE student_id=? AND (happened=1 OR late_cancel=1) AND paid=0 AND is_free=0"
                " ORDER BY scheduled_at ASC",
                (student_id,),
            ).fetchall()
        ]
        return {
            "student_id":       student_id,
            "student_name":     student["name"],
            "price_per_lesson": student["price_per_lesson"],
            "credits_total":    credits_total,
            "sessions_occurred": sessions_occurred,
            "balance":          balance,
            "balance_status":   "credit" if balance > 0 else ("owed" if balance < 0 else "settled"),
            "lessons": {
                "confirmed_paid":   confirmed_paid,
                "confirmed_unpaid": confirmed_unpaid,
                "late_cancel":      late_cancel_count,
                "unconfirmed":      unconfirmed,
            },
            "unpaid_lesson_ids": unpaid_lesson_ids,
        }
    finally:
        conn.close()


def tool_get_week_lessons(args: dict):
    week_date = args.get("week_date")
    if not week_date:
        raise ValueError("week_date required")
    try:
        d = datetime.fromisoformat(week_date)
    except ValueError:
        raise ValueError(f"Invalid week_date: {week_date!r}")
    monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6)
    conn = _db()
    try:
        return _rows(conn.execute(
            """
            SELECT l.id, l.student_id, s.name AS student_name, s.lesson_price,
                   l.scheduled_at, l.happened, l.late_cancel, l.is_free, l.paid
              FROM lessons l
              JOIN students s ON s.id = l.student_id
             WHERE l.scheduled_at >= ? AND l.scheduled_at <= ?
             ORDER BY l.scheduled_at
            """,
            (monday.strftime("%Y-%m-%dT00:00:00"), sunday.strftime("%Y-%m-%dT23:59:59")),
        ).fetchall())
    finally:
        conn.close()


def tool_add_student(args: dict):
    name     = (args.get("name") or "").strip()
    schedule = args.get("schedule") or {}
    price    = int(args.get("price_per_lesson", 0))
    if not name:
        raise ValueError("name is required")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO students (name, price_per_lesson) VALUES (?,?)", (name, price)
        )
        student_id = cur.lastrowid
        for day_str, time_str in schedule.items():
            dow = _DAY_MAP.get(day_str)
            if dow is None:
                raise ValueError(f"Unknown day key: {day_str!r}. Use Mon/Tue/Wed/Thu/Fri/Sat/Sun")
            conn.execute(
                "INSERT INTO schedules (student_id, day_of_week, lesson_time) VALUES (?,?,?)",
                (student_id, dow, time_str),
            )
        conn.commit()
        student = dict(conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone())
        student["schedules"] = _rows(conn.execute(
            "SELECT day_of_week, lesson_time FROM schedules "
            "WHERE student_id=? AND active=1 ORDER BY day_of_week",
            (student_id,),
        ).fetchall())
        return student
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"A student named '{name}' already exists")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def tool_update_student(args: dict):
    student_id = args.get("student_id")
    name       = (args.get("name") or "").strip()
    if student_id is None:
        raise ValueError("student_id is required")
    if not name:
        raise ValueError("name is required")
    conn = _db()
    try:
        conn.execute("UPDATE students SET name=? WHERE id=?", (name, student_id))
        conn.commit()
        row = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if row is None:
            raise ValueError(f"Student {student_id} not found")
        return dict(row)
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"A student named '{name}' already exists")
    finally:
        conn.close()


def tool_deactivate_student(args: dict):
    student_id = args.get("student_id")
    if student_id is None:
        raise ValueError("student_id is required")
    conn = _db()
    try:
        conn.execute("UPDATE students SET active=0 WHERE id=?", (student_id,))
        conn.commit()
        return {"student_id": student_id, "active": 0}
    finally:
        conn.close()


def tool_reactivate_student(args: dict):
    student_id = args.get("student_id")
    if student_id is None:
        raise ValueError("student_id is required")
    conn = _db()
    try:
        conn.execute("UPDATE students SET active=1 WHERE id=?", (student_id,))
        conn.commit()
        return {"student_id": student_id, "active": 1}
    finally:
        conn.close()


def tool_add_lesson(args: dict):
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO lessons (student_id, scheduled_at) VALUES (?,?)",
            (args["student_id"], args["scheduled_datetime"]),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM lessons WHERE id=?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        raise ValueError(
            f"Lesson already exists for student {args['student_id']} at {args['scheduled_datetime']}"
        )
    finally:
        conn.close()


def tool_cancel_lesson(args: dict):
    lesson_id = args.get("lesson_id")
    if lesson_id is None:
        raise ValueError("lesson_id is required")
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if row is None:
            raise ValueError(f"Lesson {lesson_id} not found")
        scheduled_at = dict(row).get("scheduled_at", "")
        conn.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
        conn.commit()
        freed_slot_matches = _query_pending_requests(
            scheduled_at[:10], scheduled_at[11:16], conn
        )
        return {"cancelled": True, "lesson_id": lesson_id,
                "freed_slot_matches": freed_slot_matches}
    finally:
        conn.close()


def tool_reschedule_lesson(args: dict):
    lesson_id    = args.get("lesson_id")
    new_datetime = args.get("new_datetime")
    if lesson_id is None:
        raise ValueError("lesson_id is required")
    if not new_datetime:
        raise ValueError("new_datetime is required")
    conn = _db()
    try:
        conn.execute(
            "UPDATE lessons SET scheduled_at=?, happened=NULL, late_cancel=0, paid=0, paid_at=NULL WHERE id=?",
            (new_datetime, lesson_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if row is None:
            raise ValueError(f"Lesson {lesson_id} not found")
        return dict(row)
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"A lesson already exists at {new_datetime}")
    finally:
        conn.close()


def tool_remove_schedule_day(args: dict):
    student_id = args.get("student_id")
    day        = args.get("day")
    if student_id is None or day is None:
        raise ValueError("student_id and day are required")
    conn = _db()
    try:
        conn.execute(
            "UPDATE schedules SET active=0 WHERE student_id=? AND day_of_week=? AND active=1",
            (student_id, day),
        )
        conn.commit()
        return {"student_id": student_id, "day": day, "active": 0}
    finally:
        conn.close()


def tool_delete_pending_request(args: dict):
    request_id = args.get("request_id")
    if request_id is None:
        raise ValueError("request_id is required")
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM pending_requests WHERE id=?", (request_id,)).fetchone():
            raise ValueError(f"Request {request_id} not found")
        conn.execute("DELETE FROM pending_requests WHERE id=?", (request_id,))
        conn.commit()
        return {"deleted": True, "request_id": request_id}
    finally:
        conn.close()


def tool_update_pending_request(args: dict):
    request_id     = args.get("request_id")
    requested_date = args.get("requested_date")
    if request_id is None:
        raise ValueError("request_id is required")
    if not requested_date:
        raise ValueError("requested_date is required")
    requested_time = args.get("requested_time")
    flexible_time  = 1 if args.get("flexible_time") else 0
    notes          = args.get("notes", "")
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM pending_requests WHERE id=?", (request_id,)).fetchone():
            raise ValueError(f"Request {request_id} not found")
        conn.execute(
            "UPDATE pending_requests SET requested_date=?, requested_time=?, flexible_time=?, notes=? WHERE id=?",
            (requested_date, requested_time, flexible_time, notes, request_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT pr.*, s.name AS student_name FROM pending_requests pr "
            "JOIN students s ON s.id = pr.student_id WHERE pr.id=?",
            (request_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def tool_generate_upcoming_lessons(args: dict):
    """Insert lesson rows for each active student's recurring schedule for the next N weeks."""
    weeks_ahead = int(args.get("weeks_ahead", 8))
    today = _date.today()
    conn = _db()
    try:
        students = _rows(conn.execute("SELECT id FROM students WHERE active=1").fetchall())
        generated = 0
        for s in students:
            sid = s["id"]
            schedules = _rows(conn.execute(
                "SELECT day_of_week, lesson_time FROM schedules WHERE student_id=? AND active=1",
                (sid,),
            ).fetchall())
            for sched in schedules:
                dow         = sched["day_of_week"]
                lesson_time = sched["lesson_time"]
                days_until  = (dow - today.weekday()) % 7
                first_date  = today + timedelta(days=days_until)
                for week in range(weeks_ahead):
                    lesson_date  = first_date + timedelta(weeks=week)
                    scheduled_at = f"{lesson_date.isoformat()}T{lesson_time}:00"
                    if not conn.execute(
                        "SELECT 1 FROM lessons WHERE student_id=? AND scheduled_at=?",
                        (sid, scheduled_at),
                    ).fetchone():
                        conn.execute(
                            "INSERT INTO lessons (student_id, scheduled_at) VALUES (?,?)",
                            (sid, scheduled_at),
                        )
                        generated += 1
        conn.commit()
        return {"generated": generated, "weeks_ahead": weeks_ahead}
    finally:
        conn.close()


# ─── Trainer availability / blocks ────────────────────────────────────────────


def tool_get_trainer_availability(_: dict):
    conn = _db()
    try:
        return _rows(conn.execute(
            "SELECT id, day_of_week, start_time, end_time, active "
            "FROM trainer_availability ORDER BY day_of_week, start_time"
        ).fetchall())
    finally:
        conn.close()


def tool_set_trainer_availability(args: dict):
    """Replace the availability window for a given day of week."""
    day   = args["day_of_week"]
    start = args["start_time"]
    end   = args["end_time"]
    conn = _db()
    try:
        conn.execute(
            "UPDATE trainer_availability SET active=0 WHERE day_of_week=?", (day,)
        )
        conn.execute(
            "INSERT INTO trainer_availability (day_of_week, start_time, end_time) VALUES (?,?,?)",
            (day, start, end),
        )
        conn.commit()
        return {"day_of_week": day, "start_time": start, "end_time": end}
    finally:
        conn.close()


def tool_add_trainer_block(args: dict):
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO trainer_blocks (description, day_of_week, start_time, end_time) VALUES (?,?,?,?)",
            (args.get("description", ""), args["day_of_week"], args["start_time"], args["end_time"]),
        )
        conn.commit()
        return dict(conn.execute(
            "SELECT * FROM trainer_blocks WHERE id=?", (cur.lastrowid,)
        ).fetchone())
    finally:
        conn.close()


def tool_remove_trainer_block(args: dict):
    block_id = args.get("block_id")
    if block_id is None:
        raise ValueError("block_id is required")
    conn = _db()
    try:
        conn.execute("UPDATE trainer_blocks SET active=0 WHERE id=?", (block_id,))
        conn.commit()
        return {"block_id": block_id, "active": 0}
    finally:
        conn.close()


def tool_get_open_slots(args: dict):
    """
    Return available lesson slots for a given date.
    Subtracts trainer blocks and already-booked lessons from availability windows.
    """
    date_str         = args.get("date")
    lesson_duration  = int(args.get("lesson_duration_minutes", 60))
    if not date_str:
        raise ValueError("date is required (YYYY-MM-DD)")
    try:
        d = _date.fromisoformat(date_str)
    except ValueError:
        raise ValueError(f"Invalid date: {date_str!r}")
    dow = d.weekday()
    conn = _db()
    try:
        avail_rows = _rows(conn.execute(
            "SELECT start_time, end_time FROM trainer_availability WHERE day_of_week=? AND active=1",
            (dow,),
        ).fetchall())
        if not avail_rows:
            return {"date": date_str, "open_slots": []}

        avail_mins = [
            (_time_to_min(r["start_time"]), _time_to_min(r["end_time"]))
            for r in avail_rows
        ]

        # Recurring blocks
        block_rows = _rows(conn.execute(
            "SELECT start_time, end_time FROM trainer_blocks WHERE day_of_week=? AND active=1",
            (dow,),
        ).fetchall())
        blocked_mins = [
            (_time_to_min(r["start_time"]), _time_to_min(r["end_time"]))
            for r in block_rows
        ]

        # Lessons already booked that day (unconfirmed = still occupies slot)
        lesson_rows = _rows(conn.execute(
            "SELECT scheduled_at FROM lessons WHERE DATE(scheduled_at)=? AND happened IS NULL",
            (date_str,),
        ).fetchall())
        for lr in lesson_rows:
            t = lr["scheduled_at"][11:16]
            s = _time_to_min(t)
            blocked_mins.append((s, s + lesson_duration))

        free = _subtract_intervals(avail_mins, blocked_mins)

        open_slots = []
        for s, e in free:
            cur = s
            while cur + lesson_duration <= e:
                open_slots.append(_min_to_time(cur))
                cur += lesson_duration

        return {"date": date_str, "open_slots": open_slots}
    finally:
        conn.close()


# ─── Tools registry ───────────────────────────────────────────────────────────

TOOLS = {
    "get_students":            tool_get_students,
    "get_pending_lessons":     tool_get_pending_lessons,
    "get_pending_overrides":   tool_get_pending_overrides,
    "get_todays_lessons":      tool_get_todays_lessons,
    "mark_lesson":             tool_mark_lesson,
    "add_credit":              tool_add_credit,
    "apply_payment":           tool_apply_payment,
    "record_payment":          tool_record_payment,
    "update_student_price":    tool_update_student_price,
    "update_schedule":         tool_update_schedule,
    "generate_balance":        tool_generate_balance,
    "add_lesson":              tool_add_lesson,
    "add_pending_request":     tool_add_pending_request,
    "check_pending_requests":  tool_check_pending_requests,
    "get_pending_requests":    tool_get_pending_requests,
    "get_week_lessons":        tool_get_week_lessons,
    "add_student":             tool_add_student,
    "update_student":          tool_update_student,
    "deactivate_student":      tool_deactivate_student,
    "reactivate_student":      tool_reactivate_student,
    "cancel_lesson":           tool_cancel_lesson,
    "reschedule_lesson":       tool_reschedule_lesson,
    "generate_upcoming_lessons": tool_generate_upcoming_lessons,
    "remove_schedule_day":     tool_remove_schedule_day,
    "delete_pending_request":  tool_delete_pending_request,
    "update_pending_request":  tool_update_pending_request,
    "get_trainer_availability": tool_get_trainer_availability,
    "set_trainer_availability": tool_set_trainer_availability,
    "add_trainer_block":       tool_add_trainer_block,
    "remove_trainer_block":    tool_remove_trainer_block,
    "get_open_slots":          tool_get_open_slots,
}


# ─── Claude tool manifest (Anthropic API format) ──────────────────────────────
# Used by the server-side agentic loop (_run_agent_loop).

CLAUDE_TOOLS = [
    {
        "name": "get_students",
        "description": "List all active students with their default weekly schedules.",
        "input_schema": {"type": "object", "properties": {
            "include_inactive": {"type": "boolean"},
        }},
    },
    {
        "name": "get_pending_lessons",
        "description": "Return lessons scheduled before now that have not yet been confirmed.",
        "input_schema": {"type": "object", "properties": {
            "since_datetime": {"type": "string"},
        }, "required": ["since_datetime"]},
    },
    {
        "name": "get_pending_overrides",
        "description": "Return one-off schedule override requests not yet applied.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_todays_lessons",
        "description": "Return all lessons scheduled for today.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "mark_lesson",
        "description": "Set the status of a lesson. status: 'happened' | 'late_cancel' | 'cancelled'",
        "input_schema": {"type": "object", "properties": {
            "lesson_id": {"type": "integer"},
            "status":    {"type": "string", "enum": ["happened", "late_cancel", "cancelled"]},
        }, "required": ["lesson_id", "status"]},
    },
    {
        "name": "add_credit",
        "description": "Add prepaid or makeup credit (session units) to a student's account.",
        "input_schema": {"type": "object", "properties": {
            "student_id": {"type": "integer"},
            "amount":     {"type": "number"},
            "reason":     {"type": "string"},
        }, "required": ["student_id", "amount"]},
    },
    {
        "name": "apply_payment",
        "description": "Mark specific lessons as paid by lesson ID list.",
        "input_schema": {"type": "object", "properties": {
            "student_id":  {"type": "integer"},
            "lesson_ids":  {"type": "array", "items": {"type": "integer"}},
        }, "required": ["student_id", "lesson_ids"]},
    },
    {
        "name": "record_payment",
        "description": "Record a cash payment in lira. Automatically marks the oldest unpaid lessons paid.",
        "input_schema": {"type": "object", "properties": {
            "student_id":  {"type": "integer"},
            "amount_lira": {"type": "integer"},
        }, "required": ["student_id", "amount_lira"]},
    },
    {
        "name": "update_student_price",
        "description": "Set the per-session price in lira for a student.",
        "input_schema": {"type": "object", "properties": {
            "student_id":       {"type": "integer"},
            "price_per_lesson": {"type": "integer"},
        }, "required": ["student_id", "price_per_lesson"]},
    },
    {
        "name": "update_schedule",
        "description": "Change a student's schedule permanently or for a single week.",
        "input_schema": {"type": "object", "properties": {
            "student_id":    {"type": "integer"},
            "day":           {"type": "integer"},
            "time":          {"type": "string"},
            "override_week": {"type": "string"},
        }, "required": ["student_id", "day", "time"]},
    },
    {
        "name": "generate_balance",
        "description": "Compute credit/payment balance summary for a student.",
        "input_schema": {"type": "object", "properties": {
            "student_id": {"type": "integer"},
        }, "required": ["student_id"]},
    },
    {
        "name": "add_lesson",
        "description": "Manually schedule a one-off lesson for a student.",
        "input_schema": {"type": "object", "properties": {
            "student_id":         {"type": "integer"},
            "scheduled_datetime": {"type": "string"},
        }, "required": ["student_id", "scheduled_datetime"]},
    },
    {
        "name": "add_pending_request",
        "description": "Record that a student wants a lesson on a specific date.",
        "input_schema": {"type": "object", "properties": {
            "student_id":     {"type": "integer"},
            "requested_date": {"type": "string"},
            "requested_time": {"type": "string"},
            "flexible_time":  {"type": "boolean"},
            "notes":          {"type": "string"},
        }, "required": ["student_id", "requested_date"]},
    },
    {
        "name": "check_pending_requests",
        "description": "Return unfulfilled requests that match a newly freed slot.",
        "input_schema": {"type": "object", "properties": {
            "freed_date": {"type": "string"},
            "freed_time": {"type": "string"},
        }, "required": ["freed_date"]},
    },
    {
        "name": "get_pending_requests",
        "description": "Return all unfulfilled lesson-slot requests across all students.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_week_lessons",
        "description": "Return all lessons for the week containing week_date.",
        "input_schema": {"type": "object", "properties": {
            "week_date": {"type": "string"},
        }, "required": ["week_date"]},
    },
    {
        "name": "add_student",
        "description": "Create a new student with an optional weekly schedule.",
        "input_schema": {"type": "object", "properties": {
            "name":             {"type": "string"},
            "price_per_lesson": {"type": "integer"},
            "schedule": {"type": "object", "additionalProperties": {"type": "string"}},
        }, "required": ["name"]},
    },
    {
        "name": "update_student",
        "description": "Rename an existing student.",
        "input_schema": {"type": "object", "properties": {
            "student_id": {"type": "integer"},
            "name":       {"type": "string"},
        }, "required": ["student_id", "name"]},
    },
    {
        "name": "deactivate_student",
        "description": "Soft-delete a student (preserves history).",
        "input_schema": {"type": "object", "properties": {
            "student_id": {"type": "integer"},
        }, "required": ["student_id"]},
    },
    {
        "name": "reactivate_student",
        "description": "Re-enable a previously deactivated student.",
        "input_schema": {"type": "object", "properties": {
            "student_id": {"type": "integer"},
        }, "required": ["student_id"]},
    },
    {
        "name": "cancel_lesson",
        "description": "Delete a scheduled lesson and return any pending requests matching the freed slot.",
        "input_schema": {"type": "object", "properties": {
            "lesson_id": {"type": "integer"},
        }, "required": ["lesson_id"]},
    },
    {
        "name": "reschedule_lesson",
        "description": "Move a lesson to a new datetime and reset its status.",
        "input_schema": {"type": "object", "properties": {
            "lesson_id":    {"type": "integer"},
            "new_datetime": {"type": "string"},
        }, "required": ["lesson_id", "new_datetime"]},
    },
    {
        "name": "generate_upcoming_lessons",
        "description": "Auto-populate lessons table from recurring schedules for the next N weeks.",
        "input_schema": {"type": "object", "properties": {
            "weeks_ahead": {"type": "integer"},
        }},
    },
    {
        "name": "remove_schedule_day",
        "description": "Deactivate a student's recurring schedule for a given day.",
        "input_schema": {"type": "object", "properties": {
            "student_id": {"type": "integer"},
            "day":        {"type": "integer"},
        }, "required": ["student_id", "day"]},
    },
    {
        "name": "delete_pending_request",
        "description": "Permanently delete a pending lesson request.",
        "input_schema": {"type": "object", "properties": {
            "request_id": {"type": "integer"},
        }, "required": ["request_id"]},
    },
    {
        "name": "update_pending_request",
        "description": "Update the date, time, flexibility, or notes of a pending request.",
        "input_schema": {"type": "object", "properties": {
            "request_id":     {"type": "integer"},
            "requested_date": {"type": "string"},
            "requested_time": {"type": "string"},
            "flexible_time":  {"type": "boolean"},
            "notes":          {"type": "string"},
        }, "required": ["request_id", "requested_date"]},
    },
    {
        "name": "get_trainer_availability",
        "description": "Return the trainer's weekly availability windows.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_trainer_availability",
        "description": "Set the trainer's availability window for a day of week.",
        "input_schema": {"type": "object", "properties": {
            "day_of_week": {"type": "integer"},
            "start_time":  {"type": "string"},
            "end_time":    {"type": "string"},
        }, "required": ["day_of_week", "start_time", "end_time"]},
    },
    {
        "name": "add_trainer_block",
        "description": "Add a recurring block (e.g. group class) within availability.",
        "input_schema": {"type": "object", "properties": {
            "description": {"type": "string"},
            "day_of_week": {"type": "integer"},
            "start_time":  {"type": "string"},
            "end_time":    {"type": "string"},
        }, "required": ["day_of_week", "start_time", "end_time"]},
    },
    {
        "name": "remove_trainer_block",
        "description": "Deactivate a recurring trainer block by ID.",
        "input_schema": {"type": "object", "properties": {
            "block_id": {"type": "integer"},
        }, "required": ["block_id"]},
    },
    {
        "name": "get_open_slots",
        "description": "Return open lesson slots for a date (availability minus blocks minus booked lessons).",
        "input_schema": {"type": "object", "properties": {
            "date":                    {"type": "string"},
            "lesson_duration_minutes": {"type": "integer"},
        }, "required": ["date"]},
    },
]


# ─── Anthropic helpers ────────────────────────────────────────────────────────


async def _call_anthropic(
    messages: list[dict],
    system: str = "",
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
) -> dict:
    """Call Anthropic with one retry on 429."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    payload: dict = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    for attempt in range(2):
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
        logger.info(
            f"← Anthropic {resp.status_code} | {len(resp.content)} bytes"
            + (f" (attempt {attempt + 1})" if attempt else "")
        )
        if resp.status_code == 429 and attempt == 0:
            logger.warning("  Rate limited — retrying in 10 s …")
            await asyncio.sleep(10)
            continue
        break

    if resp.status_code != 200:
        logger.error(f"  Anthropic error — HTTP {resp.status_code}\n  Body: {resp.text}")
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


async def _run_agent_loop(
    messages: list[dict],
    system: str = "",
    tools: list[dict] | None = None,
    max_rounds: int = 10,
) -> tuple[str, list[dict]]:
    """
    Run the full agentic loop to completion.
    Returns (final_text, updated_messages).
    Tools default to CLAUDE_TOOLS (all registered tools).
    """
    if tools is None:
        tools = CLAUDE_TOOLS

    msgs = list(messages)  # don't mutate caller's list

    for _ in range(max_rounds):
        body = await _call_anthropic(msgs, system, tools)
        content      = body.get("content", [])
        stop_reason  = body.get("stop_reason")

        msgs.append({"role": "assistant", "content": content})

        if stop_reason != "tool_use":
            text = " ".join(
                b["text"] for b in content if b.get("type") == "text"
            ).strip()
            return text, msgs

        # Execute all tool calls
        tool_results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            name = block["name"]
            args = block.get("input", {})
            logger.debug(f"  tool_use: {name}({json.dumps(args)[:120]})")
            fn = TOOLS.get(name)
            if fn is None:
                result_content = json.dumps({"error": f"Unknown tool: {name}"})
                is_error = True
            else:
                try:
                    result = fn(args)
                    result_content = json.dumps(result, default=str)
                    is_error = False
                except Exception as exc:
                    result_content = json.dumps({"error": str(exc)})
                    is_error = True
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block["id"],
                "content":     result_content,
                **({"is_error": True} if is_error else {}),
            })

        msgs.append({"role": "user", "content": tool_results})

    return "Üzgünüm, yanıt oluşturulamadı.", msgs


# ─── WhatsApp helpers ─────────────────────────────────────────────────────────


def _wa_system_prompt() -> str:
    today = _date.today().isoformat()
    return f"""Sen bir kişisel antrenörün WhatsApp asistanısın. Bugün: {today}.

Sana gelen mesajlar öğrencilerden geliyor. Her zaman Türkçe yanıt ver.

İlk mesajda öğrencinin kim olduğunu bilmiyorsan, adını kibarca sor.
Adı öğrendikten sonra get_students aracıyla kişiyi sisteme bak.

Yapabileceklerin:
- Program bilgisi ver (hangi günler, saatler)
- Bakiye ve ödeme bilgisi ver
- Ek ders veya erteleme talebini add_pending_request ile kaydet
- Müsait saatleri get_open_slots ile göster

Önemli: Sadece öğrencinin kendi bilgilerini paylaş. Diğer öğrenci bilgilerini verme.
Kısa ve net yanıtlar ver."""


def _load_wa_session(phone_number: str) -> list[dict]:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT messages FROM whatsapp_sessions WHERE phone_number=?",
            (phone_number,),
        ).fetchone()
        if row is None:
            return []
        return json.loads(row["messages"])
    finally:
        conn.close()


def _save_wa_session(phone_number: str, messages: list[dict]) -> None:
    # Keep last 30 messages (15 turns)
    trimmed = messages[-30:]
    payload = json.dumps(trimmed, default=str)
    now     = datetime.utcnow().isoformat(timespec="seconds")
    conn = _db()
    try:
        conn.execute(
            """
            INSERT INTO whatsapp_sessions (phone_number, messages, updated_at) VALUES (?,?,?)
            ON CONFLICT(phone_number) DO UPDATE SET messages=excluded.messages, updated_at=excluded.updated_at
            """,
            (phone_number, payload, now),
        )
        conn.commit()
    finally:
        conn.close()


def _send_whatsapp(to: str, body: str) -> None:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.warning("Twilio credentials not set — skipping send")
        return
    try:
        from twilio.rest import Client
        Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to,
            body=body,
        )
        logger.info(f"  WhatsApp sent to {to} ({len(body)} chars)")
    except Exception as exc:
        logger.error(f"  Twilio send failed: {exc}")


async def _process_whatsapp_message(phone_number: str, message_text: str) -> None:
    logger.info(f"WhatsApp ← {phone_number}: {message_text[:80]!r}")
    try:
        history  = _load_wa_session(phone_number)
        history.append({"role": "user", "content": message_text})
        system   = _wa_system_prompt()
        reply, updated_msgs = await _run_agent_loop(history, system)
        _save_wa_session(phone_number, updated_msgs)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_whatsapp, phone_number, reply)
    except Exception as exc:
        logger.error(f"  WhatsApp processing failed: {exc}\n{traceback.format_exc()}")


# ─── Routes ───────────────────────────────────────────────────────────────────


class ToolRequest(BaseModel):
    arguments: dict = {}


class ChatRequest(BaseModel):
    messages:   list[dict]
    system:     str       = ""
    tools:      list[dict] = []
    max_tokens: int       = 4096


class ChatRunRequest(BaseModel):
    messages:   list[dict]
    system:     str = ""
    max_tokens: int = 4096


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    key_preview = (
        f"{ANTHROPIC_API_KEY[:8]}…{ANTHROPIC_API_KEY[-4:]} ({len(ANTHROPIC_API_KEY)} chars)"
        if ANTHROPIC_API_KEY else "NOT SET"
    )
    logger.info(f"Starting Antrenör API — model={CLAUDE_MODEL} | api_key={key_preview}")
    if not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.executescript(SCHEMA_PATH.read_text())
        logger.info(f"DB initialised at {DB_PATH}")
    else:
        logger.info(f"DB found at {DB_PATH}")
        _migrate_db()
        logger.info("DB migration check done")
    try:
        result = tool_generate_upcoming_lessons({})
        logger.info(
            f"Upcoming lessons: {result['generated']} new rows ({result['weeks_ahead']} weeks ahead)"
        )
    except Exception as exc:
        logger.warning(f"generate_upcoming_lessons failed at startup: {exc}")


# ── Static frontend (Lightsail / standalone deployment) ───────────────────────

@app.get("/", include_in_schema=False)
async def serve_root():
    index = APP_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"status": "Antrenör API running — no frontend found in app/"})


@app.get("/app.js", include_in_schema=False)
async def serve_app_js():
    f = APP_DIR / "app.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/debug/tools")
async def list_tools():
    return {"tools": list(TOOLS.keys()), "count": len(TOOLS)}


@app.post("/api/mcp/{tool_name}")
async def call_tool(tool_name: str, req: ToolRequest):
    fn = TOOLS.get(tool_name)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    try:
        return {"result": fn(req.arguments)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Raw Anthropic proxy — client handles the agentic loop (React frontend)."""
    logger.info(
        f"→ /api/chat | messages={len(req.messages)} | tools={len(req.tools)} "
        f"| system={len(req.system)} chars"
    )
    last_user = next((m for m in reversed(req.messages) if m.get("role") == "user"), None)
    if last_user:
        content = last_user.get("content", "")
        preview = (content[:120] + "…") if isinstance(content, str) and len(content) > 120 else content
        logger.debug(f"  last user turn: {preview!r}")
    try:
        body = await _call_anthropic(req.messages, req.system, req.tools or None, req.max_tokens)
        logger.debug(
            f"  stop_reason={body.get('stop_reason')} | "
            f"input_tokens={body.get('usage', {}).get('input_tokens')} | "
            f"output_tokens={body.get('usage', {}).get('output_tokens')}"
        )
        return body
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"Anthropic API timeout: {exc}")
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach Anthropic API: {exc}")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"HTTP transport error: {exc}")
    except Exception as exc:
        logger.error(f"  Unexpected error:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/chat/run")
async def chat_run(req: ChatRunRequest):
    """
    Server-side agentic loop — runs tools automatically and returns the final text.
    Used by the vanilla frontend and WhatsApp channel.
    """
    logger.info(f"→ /api/chat/run | messages={len(req.messages)} | system={len(req.system)} chars")
    try:
        reply, updated_msgs = await _run_agent_loop(req.messages, req.system)
        return {"response": reply, "message_count": len(updated_msgs)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"  /api/chat/run error:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── WhatsApp webhook ──────────────────────────────────────────────────────────

@app.post("/whatsapp/webhook", response_class=PlainTextResponse, include_in_schema=False)
async def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(...),
):
    """Twilio sends POST form data. Return empty TwiML immediately; process async."""
    background_tasks.add_task(_process_whatsapp_message, From, Body)
    return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
