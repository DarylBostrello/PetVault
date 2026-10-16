"""The SQLite table definitions and the small migrations for older database files."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    species      TEXT NOT NULL,
    breed        TEXT,
    birth_date   TEXT,
    weight_kg    REAL,
    owner_name   TEXT NOT NULL,
    owner_phone  TEXT NOT NULL,
    owner_email  TEXT
);

CREATE TABLE IF NOT EXISTS veterinarians (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    specialty  TEXT
);

CREATE TABLE IF NOT EXISTS vet_schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vet_id      INTEGER NOT NULL REFERENCES veterinarians(id) ON DELETE CASCADE,
    weekday     INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    working     INTEGER NOT NULL DEFAULT 1,
    start_time  TEXT NOT NULL DEFAULT '08:00',
    end_time    TEXT NOT NULL DEFAULT '18:00',
    UNIQUE (vet_id, weekday)
);

CREATE TABLE IF NOT EXISTS vet_days_off (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vet_id      INTEGER NOT NULL REFERENCES veterinarians(id) ON DELETE CASCADE,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS appointments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    vet_id        INTEGER NOT NULL REFERENCES veterinarians(id),
    scheduled_at  TEXT NOT NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'scheduled'
                  CHECK (status IN ('scheduled', 'completed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS medical_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    vet_id          INTEGER NOT NULL REFERENCES veterinarians(id),
    visit_date      TEXT NOT NULL,
    diagnosis       TEXT NOT NULL,
    treatment       TEXT,
    notes           TEXT,
    appointment_id  INTEGER REFERENCES appointments(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    amount_cents    INTEGER NOT NULL CHECK (amount_cents >= 0),
    issued_on       TEXT NOT NULL,
    paid            INTEGER NOT NULL DEFAULT 0,
    payment_method  TEXT,
    paid_on         TEXT,
    appointment_id  INTEGER REFERENCES appointments(id) ON DELETE SET NULL,
    voided          INTEGER NOT NULL DEFAULT 0,
    void_reason     TEXT,
    voided_on       TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name      TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('admin', 'receptionist', 'vet')),
    password_hash  TEXT NOT NULL
);
"""

# Columns added after the first version: older database files get them on start-up.
MIGRATIONS = [
    ("medical_records", "appointment_id",
     "INTEGER REFERENCES appointments(id) ON DELETE SET NULL"),
    ("invoices", "appointment_id",
     "INTEGER REFERENCES appointments(id) ON DELETE SET NULL"),
    ("invoices", "payment_method", "TEXT"),
    ("invoices", "paid_on", "TEXT"),
    ("invoices", "voided", "INTEGER NOT NULL DEFAULT 0"),
    ("invoices", "void_reason", "TEXT"),
    ("invoices", "voided_on", "TEXT"),
]
