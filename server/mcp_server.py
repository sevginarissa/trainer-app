"""
Trainer Scheduling & Lesson Ledger — MCP stdio server
Pure stdlib: no external packages required. Python 3.7+.
Implements the MCP JSON-RPC 2.0 stdio protocol directly.
"""

import json
import sqlite3
import sys
from datetime import datetime, date as _date, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "db" / "trainer.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


# ─── DB helpers ───────────────────────────────────────────────────────────────


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _rows(rs):
    return [dict(r) for r in rs]


def _ok(data):
    return json.dumps(data, default=str)


def _err(msg):
    return json.dumps({"error": msg})


# ─── Tool implementations ─────────────────────────────────────────────────────


_DAY_MAP = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}


def tool_get_students(args):
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
        return _ok(students)
    finally:
        conn.close()


def tool_get_pending_lessons(args):
    since = args.get("since_datetime", "2000-01-01T00:00:00")
    conn = _db()
    try:
        rows = _rows(conn.execute(
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
        return _ok(rows)
    finally:
        conn.close()


def tool_get_pending_overrides(_args):
    conn = _db()
    try:
        rows = _rows(conn.execute(
            """
            SELECT so.id, so.student_id, s.name AS student_name,
                   so.day_of_week, so.lesson_time, so.override_week, so.applied
              FROM schedule_overrides so
              JOIN students s ON s.id = so.student_id
             WHERE so.applied = 0
             ORDER BY so.override_week, so.created_at
            """
        ).fetchall())
        return _ok(rows)
    finally:
        conn.close()


def tool_get_todays_lessons(_args):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _db()
    try:
        rows = _rows(conn.execute(
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
        return _ok(rows)
    finally:
        conn.close()


def _query_pending_requests(freed_date, freed_time, conn):
    """Return unfulfilled requests that match a freed slot (shared helper)."""
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


def tool_mark_lesson(args):
    lesson_id = args.get("lesson_id")
    happened = args.get("happened")
    if lesson_id is None or happened is None:
        return _err("lesson_id and happened are required")
    conn = _db()
    try:
        conn.execute(
            "UPDATE lessons SET happened=? WHERE id=?",
            (1 if happened else 0, lesson_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if row is None:
            return _err(f"Lesson {lesson_id} not found")
        result = dict(row)
        if not happened:
            scheduled_at = result.get("scheduled_at", "")
            freed_date = scheduled_at[:10]
            freed_time = scheduled_at[11:16]
            result["freed_slot_matches"] = _query_pending_requests(freed_date, freed_time, conn)
        return _ok(result)
    finally:
        conn.close()


def tool_add_pending_request(args):
    student_id    = args.get("student_id")
    requested_date = args.get("requested_date")
    if not student_id or not requested_date:
        return _err("student_id and requested_date are required")
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
        return _ok(dict(row))
    finally:
        conn.close()


def tool_check_pending_requests(args):
    freed_date = args.get("freed_date")
    freed_time = args.get("freed_time", "")
    if not freed_date:
        return _err("freed_date is required")
    conn = _db()
    try:
        return _ok(_query_pending_requests(freed_date, freed_time, conn))
    finally:
        conn.close()


def tool_get_pending_requests(_args):
    conn = _db()
    try:
        rows = _rows(conn.execute(
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
        return _ok(rows)
    finally:
        conn.close()


def tool_add_credit(args):
    student_id = args.get("student_id")
    amount = args.get("amount")
    if student_id is None or amount is None:
        return _err("student_id and amount are required")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO credits (student_id, amount, reason) VALUES (?,?,?)",
            (student_id, amount, args.get("reason", "")),
        )
        conn.commit()
        return _ok(dict(conn.execute("SELECT * FROM credits WHERE id=?", (cur.lastrowid,)).fetchone()))
    finally:
        conn.close()


def tool_apply_payment(args):
    student_id    = args.get("student_id")
    lesson_ids    = args.get("lesson_ids", [])
    if not student_id or not lesson_ids:
        return _err("student_id and lesson_ids are required")
    session_count = len(lesson_ids)
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM students WHERE id=?", (student_id,)).fetchone():
            return _err(f"Student {student_id} not found")
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
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
        return _ok({
            "payment_id":    payment_id,
            "student_id":    student_id,
            "lesson_ids":    lesson_ids,
            "session_count": session_count,
            "paid_at":       now,
        })
    except Exception as e:
        conn.rollback()
        return _err(str(e))
    finally:
        conn.close()


def tool_update_schedule(args):
    student_id = args.get("student_id")
    day = args.get("day")
    time = args.get("time")
    override_week = args.get("override_week")
    if student_id is None or day is None or time is None:
        return _err("student_id, day, and time are required")
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
            return _ok({"status": "permanent_schedule_updated",
                         "student_id": student_id, "day": day, "time": time})
        cur = conn.execute(
            "INSERT INTO schedule_overrides (student_id, day_of_week, lesson_time, override_week) VALUES (?,?,?,?)",
            (student_id, day, time, override_week),
        )
        conn.commit()
        return _ok(dict(conn.execute("SELECT * FROM schedule_overrides WHERE id=?", (cur.lastrowid,)).fetchone()))
    finally:
        conn.close()


def tool_generate_balance(args):
    student_id = args.get("student_id")
    if student_id is None:
        return _err("student_id is required")
    conn = _db()
    try:
        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            return _err(f"Student {student_id} not found")
        credits_total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM credits WHERE student_id=?", (student_id,)
        ).fetchone()[0]
        confirmed_paid = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened=1 AND paid=1", (student_id,)
        ).fetchone()[0]
        confirmed_unpaid = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened=1 AND paid=0", (student_id,)
        ).fetchone()[0]
        unconfirmed = conn.execute(
            "SELECT COUNT(*) FROM lessons WHERE student_id=? AND happened IS NULL", (student_id,)
        ).fetchone()[0]
        # All counts are in session units — no price multiplication
        sessions_occurred = confirmed_paid + confirmed_unpaid
        balance = int(credits_total) - sessions_occurred  # session units
        unpaid_lesson_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM lessons WHERE student_id=? AND happened=1 AND paid=0"
                " ORDER BY scheduled_at ASC",
                (student_id,),
            ).fetchall()
        ]
        return _ok({
            "student_id": student_id, "student_name": student["name"],
            "credits_total": int(credits_total),   # sessions of credit
            "sessions_occurred": sessions_occurred,
            "balance": balance,                    # session units
            "balance_status": "credit" if balance > 0 else ("owed" if balance < 0 else "settled"),
            "lessons": {
                "confirmed_paid": confirmed_paid,
                "confirmed_unpaid": confirmed_unpaid,
                "unconfirmed": unconfirmed,
            },
            "unpaid_lesson_ids": unpaid_lesson_ids,
        })
    finally:
        conn.close()


def tool_add_student(args):
    name     = (args.get("name") or "").strip()
    schedule = args.get("schedule") or {}
    if not name:
        return _err("name is required")
    conn = _db()
    try:
        cur = conn.execute("INSERT INTO students (name) VALUES (?)", (name,))
        student_id = cur.lastrowid
        for day_str, time_str in schedule.items():
            dow = _DAY_MAP.get(day_str)
            if dow is None:
                conn.rollback()
                return _err(f"Unknown day key: {day_str!r}. Use Mon/Tue/Wed/Thu/Fri/Sat/Sun")
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
        return _ok(student)
    except sqlite3.IntegrityError:
        conn.rollback()
        return _err(f"A student named '{name}' already exists")
    except Exception as e:
        conn.rollback()
        return _err(str(e))
    finally:
        conn.close()


def tool_update_student(args):
    student_id = args.get("student_id")
    name       = (args.get("name") or "").strip()
    if student_id is None:
        return _err("student_id is required")
    if not name:
        return _err("name is required")
    conn = _db()
    try:
        conn.execute("UPDATE students SET name=? WHERE id=?", (name, student_id))
        conn.commit()
        row = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if row is None:
            return _err(f"Student {student_id} not found")
        return _ok(dict(row))
    except sqlite3.IntegrityError:
        conn.rollback()
        return _err(f"A student named '{name}' already exists")
    finally:
        conn.close()


def tool_deactivate_student(args):
    student_id = args.get("student_id")
    if student_id is None:
        return _err("student_id is required")
    conn = _db()
    try:
        conn.execute("UPDATE students SET active=0 WHERE id=?", (student_id,))
        conn.commit()
        return _ok({"student_id": student_id, "active": 0})
    finally:
        conn.close()


def tool_reactivate_student(args):
    student_id = args.get("student_id")
    if student_id is None:
        return _err("student_id is required")
    conn = _db()
    try:
        conn.execute("UPDATE students SET active=1 WHERE id=?", (student_id,))
        conn.commit()
        return _ok({"student_id": student_id, "active": 1})
    finally:
        conn.close()


def tool_get_week_lessons(args):
    week_date = args.get("week_date")
    if not week_date:
        return _err("week_date is required")
    try:
        d = datetime.fromisoformat(week_date)
    except ValueError:
        return _err(f"Invalid week_date: {week_date!r}")
    monday = d - timedelta(days=d.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6)
    week_start = monday.strftime("%Y-%m-%dT00:00:00")
    week_end   = sunday.strftime("%Y-%m-%dT23:59:59")
    conn = _db()
    try:
        rows = _rows(conn.execute(
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
        return _ok(rows)
    finally:
        conn.close()


def tool_add_lesson(args):
    student_id = args.get("student_id")
    scheduled_datetime = args.get("scheduled_datetime")
    if not student_id or not scheduled_datetime:
        return _err("student_id and scheduled_datetime are required")
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO lessons (student_id, scheduled_at) VALUES (?,?)",
            (student_id, scheduled_datetime),
        )
        conn.commit()
        return _ok(dict(conn.execute("SELECT * FROM lessons WHERE id=?", (cur.lastrowid,)).fetchone()))
    except sqlite3.IntegrityError:
        return _err(f"A lesson for student {student_id} at {scheduled_datetime} already exists")
    finally:
        conn.close()


def tool_cancel_lesson(args):
    lesson_id = args.get("lesson_id")
    if lesson_id is None:
        return _err("lesson_id is required")
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if row is None:
            return _err(f"Lesson {lesson_id} not found")
        scheduled_at = dict(row).get("scheduled_at", "")
        conn.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
        conn.commit()
        freed_slot_matches = _rows(conn.execute(
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
            (scheduled_at[:10], scheduled_at[11:16]),
        ).fetchall())
        return _ok({
            "cancelled": True,
            "lesson_id": lesson_id,
            "freed_slot_matches": freed_slot_matches,
        })
    finally:
        conn.close()


def tool_reschedule_lesson(args):
    lesson_id    = args.get("lesson_id")
    new_datetime = args.get("new_datetime")
    if lesson_id is None:
        return _err("lesson_id is required")
    if not new_datetime:
        return _err("new_datetime is required")
    conn = _db()
    try:
        conn.execute(
            "UPDATE lessons SET scheduled_at=?, happened=NULL, paid=0, paid_at=NULL WHERE id=?",
            (new_datetime, lesson_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if row is None:
            return _err(f"Lesson {lesson_id} not found")
        return _ok(dict(row))
    except sqlite3.IntegrityError:
        conn.rollback()
        return _err(f"A lesson already exists at {new_datetime}")
    finally:
        conn.close()


def tool_remove_schedule_day(args):
    student_id = args.get("student_id")
    day = args.get("day")
    if student_id is None or day is None:
        return _err("student_id and day are required")
    conn = _db()
    try:
        conn.execute(
            "UPDATE schedules SET active=0 WHERE student_id=? AND day_of_week=? AND active=1",
            (student_id, day),
        )
        conn.commit()
        return _ok({"student_id": student_id, "day": day, "active": 0})
    finally:
        conn.close()


def tool_delete_pending_request(args):
    request_id = args.get("request_id")
    if request_id is None:
        return _err("request_id is required")
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM pending_requests WHERE id=?", (request_id,)).fetchone():
            return _err(f"Request {request_id} not found")
        conn.execute("DELETE FROM pending_requests WHERE id=?", (request_id,))
        conn.commit()
        return _ok({"deleted": True, "request_id": request_id})
    finally:
        conn.close()


def tool_update_pending_request(args):
    request_id     = args.get("request_id")
    requested_date = args.get("requested_date")
    if request_id is None:
        return _err("request_id is required")
    if not requested_date:
        return _err("requested_date is required")
    requested_time = args.get("requested_time")
    flexible_time  = 1 if args.get("flexible_time") else 0
    notes          = args.get("notes", "")
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM pending_requests WHERE id=?", (request_id,)).fetchone():
            return _err(f"Request {request_id} not found")
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
        return _ok(dict(row))
    finally:
        conn.close()


def tool_generate_upcoming_lessons(args):
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
        return _ok({"generated": generated, "weeks_ahead": weeks_ahead})
    finally:
        conn.close()


TOOL_REGISTRY = {
    "get_students":            tool_get_students,
    "get_pending_lessons":     tool_get_pending_lessons,
    "get_pending_overrides":   tool_get_pending_overrides,
    "get_todays_lessons":      tool_get_todays_lessons,
    "mark_lesson":             tool_mark_lesson,
    "add_credit":              tool_add_credit,
    "apply_payment":           tool_apply_payment,
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
    "cancel_lesson":              tool_cancel_lesson,
    "reschedule_lesson":          tool_reschedule_lesson,
    "generate_upcoming_lessons":  tool_generate_upcoming_lessons,
    "remove_schedule_day":        tool_remove_schedule_day,
    "delete_pending_request":     tool_delete_pending_request,
    "update_pending_request":     tool_update_pending_request,
}


# ─── MCP tool manifest ────────────────────────────────────────────────────────


TOOLS_MANIFEST = [
    {
        "name": "get_students",
        "description": "List all active students with their default weekly schedules.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pending_lessons",
        "description": "Return lessons scheduled before now that have not yet been confirmed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_datetime": {"type": "string",
                                   "description": "ISO datetime lower bound, e.g. '2026-05-01T00:00:00'"},
            },
            "required": ["since_datetime"],
        },
    },
    {
        "name": "get_pending_overrides",
        "description": "Return one-off schedule override requests not yet applied.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_todays_lessons",
        "description": "Return all lessons scheduled for today.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mark_lesson",
        "description": "Mark whether a scheduled lesson happened or was a no-show.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lesson_id": {"type": "integer"},
                "happened": {"type": "boolean"},
            },
            "required": ["lesson_id", "happened"],
        },
    },
    {
        "name": "add_credit",
        "description": "Add prepaid or makeup credit to a student's account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "integer"},
                "amount": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["student_id", "amount"],
        },
    },
    {
        "name": "apply_payment",
        "description": "Mark a set of confirmed lessons as paid and record the payment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "integer"},
                "lesson_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["student_id", "lesson_ids"],
        },
    },
    {
        "name": "update_schedule",
        "description": "Change a student's schedule permanently or for a single week.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "integer"},
                "day":         {"type": "integer",
                                "description": "Day of week: 0=Mon … 6=Sun"},
                "time":        {"type": "string",
                                "description": "Lesson time HH:MM"},
                "override_week": {"type": "string",
                                  "description": "ISO date of the week's Monday for a one-off change. Omit for permanent."},
            },
            "required": ["student_id", "day", "time"],
        },
    },
    {
        "name": "generate_balance",
        "description": "Compute credit/payment balance summary for a student.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "integer"},
            },
            "required": ["student_id"],
        },
    },
    {
        "name": "add_lesson",
        "description": "Manually schedule a one-off lesson for a student.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id":          {"type": "integer"},
                "scheduled_datetime":  {"type": "string",
                                        "description": "ISO datetime, e.g. '2026-05-28T09:00:00'"},
            },
            "required": ["student_id", "scheduled_datetime"],
        },
    },
    {
        "name": "add_pending_request",
        "description": "Record that a student wants a lesson on a specific date (and optionally time).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id":     {"type": "integer"},
                "requested_date": {"type": "string",  "description": "ISO date YYYY-MM-DD"},
                "requested_time": {"type": "string",  "description": "HH:MM — omit if flexible_time is true"},
                "flexible_time":  {"type": "boolean", "description": "true = any time on that date works"},
                "notes":          {"type": "string"},
            },
            "required": ["student_id", "requested_date"],
        },
    },
    {
        "name": "check_pending_requests",
        "description": "Return unfulfilled requests that match a newly freed slot (date + time).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "freed_date": {"type": "string", "description": "ISO date YYYY-MM-DD of the freed slot"},
                "freed_time": {"type": "string", "description": "HH:MM of the freed slot"},
            },
            "required": ["freed_date"],
        },
    },
    {
        "name": "get_pending_requests",
        "description": "Return all unfulfilled lesson-slot requests across all students.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_week_lessons",
        "description": "Return all lessons (any status) for the week containing week_date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_date": {"type": "string",
                              "description": "Any ISO date within the target week (YYYY-MM-DD)"},
            },
            "required": ["week_date"],
        },
    },
    {
        "name": "add_student",
        "description": "Create a new student with an optional weekly schedule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "schedule": {
                    "type": "object",
                    "description": 'Weekly schedule map, e.g. {"Mon": "09:00", "Wed": "09:00"}',
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_student",
        "description": "Rename an existing student.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "integer"},
                "name": {"type": "string", "description": "New name"},
            },
            "required": ["student_id", "name"],
        },
    },
    {
        "name": "deactivate_student",
        "description": "Soft-delete a student (active=0). All lesson history is preserved.",
        "inputSchema": {
            "type": "object",
            "properties": {"student_id": {"type": "integer"}},
            "required": ["student_id"],
        },
    },
    {
        "name": "reactivate_student",
        "description": "Re-enable a previously deactivated student (active=1).",
        "inputSchema": {
            "type": "object",
            "properties": {"student_id": {"type": "integer"}},
            "required": ["student_id"],
        },
    },
    {
        "name": "cancel_lesson",
        "description": "Delete a scheduled lesson and return any pending requests that match the freed slot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lesson_id": {"type": "integer", "description": "Lesson ID to cancel"},
            },
            "required": ["lesson_id"],
        },
    },
    {
        "name": "reschedule_lesson",
        "description": "Move a lesson to a new datetime and reset its confirmation status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lesson_id":    {"type": "integer", "description": "Lesson ID to move"},
                "new_datetime": {"type": "string",  "description": "New ISO datetime, e.g. '2026-05-28T10:00:00'"},
            },
            "required": ["lesson_id", "new_datetime"],
        },
    },
    {
        "name": "generate_upcoming_lessons",
        "description": "Auto-populate the lessons table from recurring schedules for the next N weeks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "weeks_ahead": {"type": "integer",
                                "description": "How many weeks to populate (default 8)"},
            },
        },
    },
    {
        "name": "remove_schedule_day",
        "description": "Deactivate a student's recurring schedule slot for a given day of week.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "integer"},
                "day":        {"type": "integer", "description": "Day of week 0=Mon … 6=Sun"},
            },
            "required": ["student_id", "day"],
        },
    },
    {
        "name": "delete_pending_request",
        "description": "Permanently delete a pending lesson request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "integer"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "update_pending_request",
        "description": "Update the date, time, flexibility flag, or notes of a pending lesson request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id":     {"type": "integer"},
                "requested_date": {"type": "string",  "description": "ISO date YYYY-MM-DD"},
                "requested_time": {"type": "string",  "description": "HH:MM — omit or null if flexible_time"},
                "flexible_time":  {"type": "boolean"},
                "notes":          {"type": "string"},
            },
            "required": ["request_id", "requested_date"],
        },
    },
]


# ─── MCP JSON-RPC 2.0 stdio protocol ─────────────────────────────────────────


def send(obj):
    sys.stdout.write(json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def handle(req):
    method = req.get("method", "")
    req_id = req.get("id")          # None for notifications
    params = req.get("params") or {}

    # ── Notifications (no response) ──────────────────────────────────────────
    if req_id is None:
        return

    # ── initialize ───────────────────────────────────────────────────────────
    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "trainer-scheduler", "version": "1.0.0"},
            },
        })
        return

    # ── tools/list ───────────────────────────────────────────────────────────
    if method == "tools/list":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": TOOLS_MANIFEST},
        })
        return

    # ── tools/call ───────────────────────────────────────────────────────────
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            })
            return
        try:
            result_text = fn(arguments)
            send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": result_text}]},
            })
        except Exception as exc:
            send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                    "isError": True,
                },
            })
        return

    # ── unknown method ───────────────────────────────────────────────────────
    send({
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    })


# ─── DB init ──────────────────────────────────────────────────────────────────


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.executescript(SCHEMA_PATH.read_text())


# ─── Entry point ──────────────────────────────────────────────────────────────


def main():
    init_db()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(req)


if __name__ == "__main__":
    main()
