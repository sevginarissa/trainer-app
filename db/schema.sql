PRAGMA foreign_keys = ON;

-- ─── Tables ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS students (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,
    lesson_price     REAL    NOT NULL DEFAULT 50.0,   -- legacy; kept for compat
    price_per_lesson INTEGER NOT NULL DEFAULT 0,      -- lira per session (new)
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- day_of_week: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
CREATE TABLE IF NOT EXISTS schedules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id),
    day_of_week  INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    lesson_time  TEXT    NOT NULL,  -- HH:MM
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lessons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL REFERENCES students(id),
    scheduled_at TEXT    NOT NULL,  -- ISO datetime
    happened     INTEGER,           -- NULL=unconfirmed, 1=happened, 0=cancelled/late-cancel
    late_cancel  INTEGER NOT NULL DEFAULT 0,  -- 1=late cancellation (counts as session)
    is_free      INTEGER NOT NULL DEFAULT 0,  -- 1=free lesson (no billing impact)
    paid         INTEGER NOT NULL DEFAULT 0,
    paid_at      TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, scheduled_at)
);

-- amount = session count (integer units), not currency
CREATE TABLE IF NOT EXISTS credits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    amount     REAL    NOT NULL,
    reason     TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    amount     REAL    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lesson_payments (
    payment_id INTEGER NOT NULL REFERENCES payments(id),
    lesson_id  INTEGER NOT NULL REFERENCES lessons(id),
    PRIMARY KEY (payment_id, lesson_id)
);

-- override_week = ISO date of that week's Monday; NULL means permanent change request
CREATE TABLE IF NOT EXISTS schedule_overrides (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL REFERENCES students(id),
    day_of_week   INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    lesson_time   TEXT    NOT NULL,
    override_week TEXT,
    applied       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(id),
    requested_date TEXT    NOT NULL,             -- ISO date YYYY-MM-DD
    requested_time TEXT,                         -- HH:MM; NULL when flexible_time=1
    flexible_time  INTEGER NOT NULL DEFAULT 0,   -- 1 = any time on that date works
    notes          TEXT,
    fulfilled      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Trainer's recurring availability windows (when they can teach)
CREATE TABLE IF NOT EXISTS trainer_availability (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time  TEXT    NOT NULL,  -- HH:MM
    end_time    TEXT    NOT NULL,  -- HH:MM
    active      INTEGER NOT NULL DEFAULT 1
);

-- Recurring blocks within availability (e.g. group class, doctor's appointment)
CREATE TABLE IF NOT EXISTS trainer_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT    NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time  TEXT    NOT NULL,  -- HH:MM
    end_time    TEXT    NOT NULL,  -- HH:MM
    active      INTEGER NOT NULL DEFAULT 1
);

-- WhatsApp conversation sessions keyed by student phone number
CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number TEXT    NOT NULL UNIQUE,
    messages     TEXT    NOT NULL DEFAULT '[]',  -- JSON array of {role, content}
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─── Seed: Students ───────────────────────────────────────────────────────────

INSERT OR IGNORE INTO students (id, name, lesson_price, price_per_lesson)
VALUES (1, 'Maria', 50.0, 500);

INSERT OR IGNORE INTO students (id, name, lesson_price, price_per_lesson)
VALUES (2, 'David', 50.0, 500);

-- ─── Seed: Default Schedules ──────────────────────────────────────────────────

-- Maria: Mon (0) and Wed (2) at 09:00
INSERT INTO schedules (student_id, day_of_week, lesson_time)
SELECT 1, 0, '09:00'
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE student_id = 1 AND day_of_week = 0 AND active = 1);

INSERT INTO schedules (student_id, day_of_week, lesson_time)
SELECT 1, 2, '09:00'
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE student_id = 1 AND day_of_week = 2 AND active = 1);

-- David: Tue (1) and Thu (3) at 11:00
INSERT INTO schedules (student_id, day_of_week, lesson_time)
SELECT 2, 1, '11:00'
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE student_id = 2 AND day_of_week = 1 AND active = 1);

INSERT INTO schedules (student_id, day_of_week, lesson_time)
SELECT 2, 3, '11:00'
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE student_id = 2 AND day_of_week = 3 AND active = 1);

-- ─── Seed: Lessons ────────────────────────────────────────────────────────────
-- Three weeks ago (week of 2026-05-04): confirmed and paid

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid, paid_at)
VALUES (1, '2026-05-04 09:00:00', 1, 1, '2026-05-04 10:00:00');

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid, paid_at)
VALUES (1, '2026-05-06 09:00:00', 1, 1, '2026-05-06 10:00:00');

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid, paid_at)
VALUES (2, '2026-05-05 11:00:00', 1, 1, '2026-05-05 12:00:00');

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (2, '2026-05-07 11:00:00', 1, 0);

-- Two weeks ago (week of 2026-05-11): confirmed but unpaid, plus one no-show

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (1, '2026-05-11 09:00:00', 1, 0);

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (1, '2026-05-13 09:00:00', 1, 0);

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (2, '2026-05-12 11:00:00', 1, 0);

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (2, '2026-05-14 11:00:00', 0, 0);

-- Last week (week of 2026-05-18): all unconfirmed

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (1, '2026-05-18 09:00:00');

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (1, '2026-05-20 09:00:00');

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (2, '2026-05-19 11:00:00');

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (2, '2026-05-21 11:00:00');

-- ─── Seed: Credits ────────────────────────────────────────────────────────────

INSERT INTO credits (student_id, amount, reason)
SELECT 1, 200.0, 'Prepaid package – 4 lessons'
WHERE NOT EXISTS (SELECT 1 FROM credits WHERE student_id = 1);

INSERT INTO credits (student_id, amount, reason)
SELECT 2, 100.0, 'Prepaid package – 2 lessons'
WHERE NOT EXISTS (SELECT 1 FROM credits WHERE student_id = 2);

-- ─── Seed: Schedule Override ─────────────────────────────────────────────────
-- David requests to move Thu to Fri for the week of 2026-05-25

INSERT INTO schedule_overrides (student_id, day_of_week, lesson_time, override_week)
SELECT 2, 4, '11:00', '2026-05-25'
WHERE NOT EXISTS (SELECT 1 FROM schedule_overrides WHERE student_id = 2);

-- ─── Seed: Trainer Availability ───────────────────────────────────────────────
-- Mon–Fri 08:00–20:00, Sat 09:00–14:00

INSERT INTO trainer_availability (day_of_week, start_time, end_time)
SELECT 0, '08:00', '20:00' WHERE NOT EXISTS (SELECT 1 FROM trainer_availability WHERE day_of_week = 0);

INSERT INTO trainer_availability (day_of_week, start_time, end_time)
SELECT 1, '08:00', '20:00' WHERE NOT EXISTS (SELECT 1 FROM trainer_availability WHERE day_of_week = 1);

INSERT INTO trainer_availability (day_of_week, start_time, end_time)
SELECT 2, '08:00', '20:00' WHERE NOT EXISTS (SELECT 1 FROM trainer_availability WHERE day_of_week = 2);

INSERT INTO trainer_availability (day_of_week, start_time, end_time)
SELECT 3, '08:00', '20:00' WHERE NOT EXISTS (SELECT 1 FROM trainer_availability WHERE day_of_week = 3);

INSERT INTO trainer_availability (day_of_week, start_time, end_time)
SELECT 4, '08:00', '20:00' WHERE NOT EXISTS (SELECT 1 FROM trainer_availability WHERE day_of_week = 4);

INSERT INTO trainer_availability (day_of_week, start_time, end_time)
SELECT 5, '09:00', '14:00' WHERE NOT EXISTS (SELECT 1 FROM trainer_availability WHERE day_of_week = 5);

-- ─── Seed: Trainer Blocks ─────────────────────────────────────────────────────
-- Wed 18:00–19:00 group class, Thu 11:00–12:00 doctor appointment

INSERT INTO trainer_blocks (description, day_of_week, start_time, end_time)
SELECT 'Grup dersi', 2, '18:00', '19:00'
WHERE NOT EXISTS (SELECT 1 FROM trainer_blocks WHERE day_of_week = 2 AND description = 'Grup dersi');

INSERT INTO trainer_blocks (description, day_of_week, start_time, end_time)
SELECT 'Doktor', 3, '11:00', '12:00'
WHERE NOT EXISTS (SELECT 1 FROM trainer_blocks WHERE day_of_week = 3 AND description = 'Doktor');
