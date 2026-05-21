"""
Local HTTP bridge — exposes MCP tool logic as REST endpoints and proxies
the Claude API so the API key never touches the browser.

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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Logging setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("antrenor.api")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# DB_PATH can be overridden via env var — point to a Railway persistent volume,
# e.g. DB_PATH=/data/trainer.db when a volume is mounted at /data.
_default_db = Path(__file__).parent.parent / "db" / "trainer.db"
DB_PATH     = Path(os.getenv("DB_PATH", str(_default_db)))
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"

app = FastAPI(title="Antrenör API")

# CORS_ORIGINS: comma-separated list of allowed origins.
# Dev default covers Vite dev server + preview.
# In production set CORS_ORIGINS=https://your-app.vercel.app in Railway env vars.
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
    return conn


def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


# ─── Tool implementations ─────────────────────────────────────────────────────


_DAY_MAP = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}


def tool_get_students(args: dict):
    include_inactive = bool(args.get("include_inactive", False))
    conn = _db()
    try:
        if include_inactive:
            students = _rows(conn.execute(
                "SELECT id, name, lesson_price, active FROM students ORDER BY active DESC, name"
            ).fetchall())
        else:
            students = _rows(conn.execute(
                "SELECT id, name, lesson_price, active FROM students WHERE active=1 ORDER BY name"
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
                   l.scheduled_at, l.happened, l.paid
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
                   l.scheduled_at, l.happened, l.paid
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
    conn = _db()
    try:
        conn.execute(
            "UPDATE lessons SET happened=? WHERE id=?",
            (1 if args["happened"] else 0, args["lesson_id"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (args["lesson_id"],)).fetchone()
        if row is None:
            raise ValueError(f"Lesson {args['lesson_id']} not found")
        result = dict(row)
        if not args["happened"]:
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
            """
            INSERT INTO pending_requests
                (student_id, requested_date, requested_time, flexible_time, notes)
            VALUES (?,?,?,?,?)
            """,
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
    student_id  = args["student_id"]
    lesson_ids  = args["lesson_ids"]
    session_count = len(lesson_ids)
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM students WHERE id=?", (student_id,)).fetchone():
            raise ValueError(f"Student {student_id} not found")
        now = datetime.utcnow().isoformat(timespec="seconds")
        # Store session count (not currency) in payments.amount
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
        return {
            "payment_id":    payment_id,
            "student_id":    student_id,
            "lesson_ids":    lesson_ids,
            "session_count": session_count,
        }
    except Exception:
        conn.rollback()
        raise
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
            return {"status": "permanent_schedule_updated", "student_id": student_id, "day": day, "time": time}
        cur = conn.execute(
            "INSERT INTO schedule_overrides (student_id, day_of_week, lesson_time, override_week) VALUES (?,?,?,?)",
            (student_id, day, time, override_week),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM schedule_overrides WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


def tool_generate_balance(args: dict):
    student_id = args["student_id"]
    conn = _db()
    try:
        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            raise ValueError(f"Student {student_id} not found")
        # All counts are in session units — no price multiplication
        credits_total = int(conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM credits WHERE student_id=?", (student_id,)
        ).fetchone()[0])
        confirmed_paid = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened=1 AND paid=1", (student_id,)
        ).fetchone()[0]
        confirmed_unpaid = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened=1 AND paid=0", (student_id,)
        ).fetchone()[0]
        unconfirmed = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened IS NULL", (student_id,)
        ).fetchone()[0]
        sessions_occurred = confirmed_paid + confirmed_unpaid
        balance = credits_total - sessions_occurred   # session units
        unpaid_lesson_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM lessons WHERE student_id=? AND happened=1 AND paid=0"
                " ORDER BY scheduled_at ASC",
                (student_id,),
            ).fetchall()
        ]
        return {
            "student_id": student_id,
            "student_name": student["name"],
            "credits_total": credits_total,       # sessions of credit
            "sessions_occurred": sessions_occurred,
            "balance": balance,                   # session units (+ = credit, − = owes)
            "balance_status": "credit" if balance > 0 else ("owed" if balance < 0 else "settled"),
            "lessons": {
                "confirmed_paid": confirmed_paid,
                "confirmed_unpaid": confirmed_unpaid,
                "unconfirmed": unconfirmed,
            },
            "unpaid_lesson_ids": unpaid_lesson_ids,
        }
    finally:
        conn.close()


def tool_get_week_lessons(args: dict):
    from datetime import timedelta

    week_date = args.get("week_date")
    if not week_date:
        raise ValueError("week_date required")
    try:
        d = datetime.fromisoformat(week_date)
    except ValueError:
        raise ValueError(f"Invalid week_date: {week_date!r}")

    # Monday of the requested week
    monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6)
    week_start = monday.strftime("%Y-%m-%dT00:00:00")
    week_end   = sunday.strftime("%Y-%m-%dT23:59:59")

    conn = _db()
    try:
        return _rows(conn.execute(
            """
            SELECT l.id, l.student_id, s.name AS student_name, s.lesson_price,
                   l.scheduled_at, l.happened, l.paid
              FROM lessons l
              JOIN students s ON s.id = l.student_id
             WHERE l.scheduled_at >= ? AND l.scheduled_at <= ?
             ORDER BY l.scheduled_at
            """,
            (week_start, week_end),
        ).fetchall())
    finally:
        conn.close()


def tool_add_student(args: dict):
    name     = (args.get("name") or "").strip()
    schedule = args.get("schedule") or {}   # {"Mon": "09:00", ...}
    if not name:
        raise ValueError("name is required")
    conn = _db()
    try:
        cur = conn.execute("INSERT INTO students (name) VALUES (?)", (name,))
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
        raise ValueError(f"Lesson already exists for student {args['student_id']} at {args['scheduled_datetime']}")
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
        return {
            "cancelled": True,
            "lesson_id": lesson_id,
            "freed_slot_matches": freed_slot_matches,
        }
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
            "UPDATE lessons SET scheduled_at=?, happened=NULL, paid=0, paid_at=NULL WHERE id=?",
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
    day = args.get("day")
    if student_id is None or day is None:
        raise HTTPException(status_code=400, detail="student_id and day are required")
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
        raise HTTPException(status_code=400, detail="request_id is required")
    conn = _db()
    try:
        row = conn.execute("SELECT 1 FROM pending_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
        conn.execute("DELETE FROM pending_requests WHERE id=?", (request_id,))
        conn.commit()
        return {"deleted": True, "request_id": request_id}
    finally:
        conn.close()


def tool_update_pending_request(args: dict):
    request_id     = args.get("request_id")
    requested_date = args.get("requested_date")
    if request_id is None:
        raise HTTPException(status_code=400, detail="request_id is required")
    if not requested_date:
        raise HTTPException(status_code=400, detail="requested_date is required")
    requested_time = args.get("requested_time")
    flexible_time  = 1 if args.get("flexible_time") else 0
    notes          = args.get("notes", "")
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM pending_requests WHERE id=?", (request_id,)).fetchone():
            raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
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
    """Insert lesson rows for each active student's recurring schedule,
    going `weeks_ahead` weeks into the future, skipping rows that already exist."""
    weeks_ahead = int(args.get("weeks_ahead", 8))
    today = _date.today()
    conn = _db()
    try:
        students = _rows(conn.execute(
            "SELECT id FROM students WHERE active=1"
        ).fetchall())
        generated = 0
        for s in students:
            sid = s["id"]
            schedules = _rows(conn.execute(
                "SELECT day_of_week, lesson_time FROM schedules "
                "WHERE student_id=? AND active=1",
                (sid,),
            ).fetchall())
            for sched in schedules:
                dow         = sched["day_of_week"]   # 0=Mon … 6=Sun
                lesson_time = sched["lesson_time"]   # "HH:MM"
                # First occurrence from today (0 → today if matching)
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


TOOLS = {
    "get_students":           tool_get_students,
    "get_pending_lessons":    tool_get_pending_lessons,
    "get_pending_overrides":  tool_get_pending_overrides,
    "get_todays_lessons":     tool_get_todays_lessons,
    "mark_lesson":            tool_mark_lesson,
    "add_credit":             tool_add_credit,
    "apply_payment":          tool_apply_payment,
    "update_schedule":        tool_update_schedule,
    "generate_balance":       tool_generate_balance,
    "add_lesson":             tool_add_lesson,
    "add_pending_request":    tool_add_pending_request,
    "check_pending_requests": tool_check_pending_requests,
    "get_pending_requests":   tool_get_pending_requests,
    "get_week_lessons":       tool_get_week_lessons,
    "add_student":            tool_add_student,
    "update_student":         tool_update_student,
    "deactivate_student":     tool_deactivate_student,
    "reactivate_student":     tool_reactivate_student,
    "cancel_lesson":              tool_cancel_lesson,
    "reschedule_lesson":          tool_reschedule_lesson,
    "generate_upcoming_lessons":  tool_generate_upcoming_lessons,
    "remove_schedule_day":        tool_remove_schedule_day,
    "delete_pending_request":     tool_delete_pending_request,
    "update_pending_request":     tool_update_pending_request,
}


# ─── Routes ───────────────────────────────────────────────────────────────────


class ToolRequest(BaseModel):
    arguments: dict = {}


class ChatRequest(BaseModel):
    messages: list[dict]
    system: str = ""
    tools: list[dict] = []
    max_tokens: int = 4096


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
    # Pre-populate upcoming lessons from recurring schedules
    try:
        result = tool_generate_upcoming_lessons({})
        logger.info(f"Upcoming lessons: {result['generated']} new rows inserted ({result['weeks_ahead']} weeks ahead)")
    except Exception as exc:
        logger.warning(f"generate_upcoming_lessons failed at startup: {exc}")


@app.get("/api/debug/tools")
async def list_tools():
    return {"tools": list(TOOLS.keys())}


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
    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY is not set — add it to .env")
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured in .env")

    logger.info(
        f"→ /api/chat | messages={len(req.messages)} | tools={len(req.tools)} "
        f"| system={len(req.system)} chars | max_tokens={req.max_tokens}"
    )

    # Log the last user turn for traceability (truncated)
    last_user = next(
        (m for m in reversed(req.messages) if m.get("role") == "user"), None
    )
    if last_user:
        content = last_user.get("content", "")
        preview = (content[:120] + "…") if isinstance(content, str) and len(content) > 120 else content
        logger.debug(f"  last user turn: {preview!r}")

    # ── Build payload ─────────────────────────────────────────────────────────
    payload: dict = {
        "model": CLAUDE_MODEL,
        "max_tokens": req.max_tokens,
        "messages": req.messages,
    }
    if req.system:
        payload["system"] = req.system
    if req.tools:
        payload["tools"] = req.tools

    logger.debug(f"  payload keys: {list(payload.keys())}")

    # ── Call Anthropic (retry once on 429) ───────────────────────────────────
    try:
        for attempt in range(2):
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    ANTHROPIC_URL,
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )

            logger.info(
                f"← Anthropic {resp.status_code} | {len(resp.content)} bytes"
                + (f" (attempt {attempt + 1})" if attempt else "")
            )

            if resp.status_code == 429 and attempt == 0:
                logger.warning("  Rate limited — retrying in 10 s …")
                await asyncio.sleep(10)
                continue
            break  # success or non-retryable error

        if resp.status_code != 200:
            logger.error(
                f"  Anthropic error — HTTP {resp.status_code}\n"
                f"  Headers: {dict(resp.headers)}\n"
                f"  Body:    {resp.text}"
            )
            # Surface Anthropic's own error structure to the caller
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise HTTPException(status_code=resp.status_code, detail=detail)

        body = resp.json()
        logger.debug(
            f"  stop_reason={body.get('stop_reason')} | "
            f"input_tokens={body.get('usage', {}).get('input_tokens')} | "
            f"output_tokens={body.get('usage', {}).get('output_tokens')}"
        )
        return body

    except HTTPException:
        raise  # already logged above

    except httpx.TimeoutException as exc:
        logger.error(f"  Anthropic API timed out after 90 s: {exc}")
        raise HTTPException(status_code=504, detail=f"Anthropic API timeout: {exc}")

    except httpx.ConnectError as exc:
        logger.error(f"  Cannot reach Anthropic (ConnectError): {exc}")
        raise HTTPException(status_code=502, detail=f"Cannot reach Anthropic API: {exc}")

    except httpx.RequestError as exc:
        logger.error(f"  HTTP transport error: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=502, detail=f"HTTP transport error: {exc}")

    except Exception as exc:
        logger.error(f"  Unexpected error in /api/chat:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(exc))
