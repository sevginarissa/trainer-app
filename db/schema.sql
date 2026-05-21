PRAGMA foreign_keys = ON;

-- ─── Tables ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS students (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    lesson_price REAL    NOT NULL DEFAULT 50.0,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
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
    happened     INTEGER,           -- NULL=unconfirmed, 1=happened, 0=no-show/cancelled
    paid         INTEGER NOT NULL DEFAULT 0,
    paid_at      TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, scheduled_at)
);

-- amount in the same currency as lesson_price (e.g. prepaid, makeup credit)
CREATE TABLE IF NOT EXISTS credits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    amount     REAL    NOT NULL,
    reason     TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- one row per payment event; total amount = lesson_price * number of lessons covered
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

-- ─── Seed: Students ───────────────────────────────────────────────────────────

INSERT OR IGNORE INTO students (id, name, lesson_price)
VALUES (1, 'Maria', 50.0);

INSERT OR IGNORE INTO students (id, name, lesson_price)
VALUES (2, 'David', 50.0);

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
VALUES (1, '2026-05-04 09:00:00', 1, 1, '2026-05-04 10:00:00');  -- Maria Mon

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid, paid_at)
VALUES (1, '2026-05-06 09:00:00', 1, 1, '2026-05-06 10:00:00');  -- Maria Wed

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid, paid_at)
VALUES (2, '2026-05-05 11:00:00', 1, 1, '2026-05-05 12:00:00');  -- David Tue

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (2, '2026-05-07 11:00:00', 1, 0);                         -- David Thu (happened, unpaid)

-- Two weeks ago (week of 2026-05-11): confirmed but unpaid, plus one no-show

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (1, '2026-05-11 09:00:00', 1, 0);  -- Maria Mon

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (1, '2026-05-13 09:00:00', 1, 0);  -- Maria Wed

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (2, '2026-05-12 11:00:00', 1, 0);  -- David Tue

INSERT OR IGNORE INTO lessons (student_id, scheduled_at, happened, paid)
VALUES (2, '2026-05-14 11:00:00', 0, 0);  -- David Thu (no-show)

-- Last week (week of 2026-05-18): all unconfirmed

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (1, '2026-05-18 09:00:00');  -- Maria Mon

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (1, '2026-05-20 09:00:00');  -- Maria Wed

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (2, '2026-05-19 11:00:00');  -- David Tue

INSERT OR IGNORE INTO lessons (student_id, scheduled_at)
VALUES (2, '2026-05-21 11:00:00');  -- David Thu (today, unconfirmed)

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
