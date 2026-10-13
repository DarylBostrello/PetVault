#!/usr/bin/env python3
"""
PetVault: Veterinary Clinic Patient & Appointment Management System
--------------------------------------------------------------------
A single-file Tkinter desktop app backed by an SQLite database.
Standard library only.

Each patient record holds the pet's details AND its owner's details
(name, phone, email), so there is no separate owners list to maintain.

Highlights
  * Login with roles (administrator, receptionist, veterinarian)
  * Patients, veterinarians, appointments, medical records and billing
  * Free-slot booking that respects vet working hours and days off
  * "Complete visit" saves the medical record and the invoice together
  * Patient profile, edit / delete, reschedule, payment methods, receipts
  * Reports with CSV / PDF export, automatic and manual database backup

Run:
    python petvault.py            # open the app (creates petvault.db if needed)
    python petvault.py --demo     # load sample data (and demo logins) first
    python petvault.py --db my.db # use a different database file

On Linux you may need Tk installed (Arch: sudo pacman -S tk,
Debian/Ubuntu: sudo apt install python3-tk).
"""

import argparse
import calendar as pycal
import csv
import hashlib
import hmac
import os
import sqlite3
import subprocess
import sys
import textwrap
import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from tkinter import filedialog
from tkinter import font as tkfont
from tkinter import messagebox, ttk

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "petvault.db")
DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M"
SLOT_MINUTES = 30
DEFAULT_START, DEFAULT_END = "08:00", "18:00"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
            "Sunday"]
ROLES = ("admin", "receptionist", "vet")
ROLE_LABELS = {"admin": "Administrator", "receptionist": "Receptionist",
               "vet": "Veterinarian"}
PAYMENT_METHODS = ["Cash", "Card", "E-wallet", "Bank transfer", "Other"]
PBKDF2_ROUNDS = 200_000

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


class ClinicError(Exception):
    """Raised for any validation or business-rule problem."""


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def parse_date(text: str) -> date:
    try:
        return datetime.strptime(text.strip(), DATE_FMT).date()
    except ValueError:
        raise ClinicError(f"Invalid date '{text}'. Use YYYY-MM-DD.")


def parse_datetime(text: str) -> datetime:
    try:
        return datetime.strptime(text.strip(), DATETIME_FMT)
    except ValueError:
        raise ClinicError(f"Invalid date/time '{text}'. Use YYYY-MM-DD HH:MM.")


def parse_money_to_cents(text: str) -> int:
    try:
        amount = Decimal(text.strip().replace(",", ""))
    except InvalidOperation:
        raise ClinicError(f"Invalid amount '{text}'.")
    if amount < 0:
        raise ClinicError("Amount cannot be negative.")
    return int((amount * 100).quantize(Decimal("1")))


def require(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ClinicError(f"{label} is required.")
    return value


def to_minutes(text: str) -> int:
    try:
        hours, minutes = text.strip().split(":")
        hours, minutes = int(hours), int(minutes)
    except ValueError:
        raise ClinicError(f"Invalid time '{text}'. Use HH:MM.")
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ClinicError(f"Invalid time '{text}'. Use HH:MM.")
    return hours * 60 + minutes


def from_minutes(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def slot_times(start: str, end: str):
    """Every appointment start time between start and end (last slot must fit)."""
    return [from_minutes(m) for m in
            range(to_minutes(start), to_minutes(end) - SLOT_MINUTES + 1,
                  SLOT_MINUTES)]


def plural(count, word):
    return f"{count} {word if count == 1 else word + 's'}"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _scheme, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# --------------------------------------------------------------------------
# Core logic and database access
# --------------------------------------------------------------------------
class Clinic:
    def __init__(self, path: str = DB_FILE):
        self.path = path
        self.backup_dir = os.path.join(os.path.dirname(os.path.abspath(path)),
                                       "backups")
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self._backfill_schedules()

    def close(self):
        self.conn.close()

    # -- housekeeping ----------------------------------------------------------
    def _migrate(self):
        for table, column, ddl in MIGRATIONS:
            existing = {r["name"] for r in
                        self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        self.conn.commit()

    def _backfill_schedules(self):
        rows = self.conn.execute(
            "SELECT v.id FROM veterinarians v WHERE NOT EXISTS "
            "(SELECT 1 FROM vet_schedules s WHERE s.vet_id = v.id)").fetchall()
        for row in rows:
            self._create_default_schedule(row["id"])
        self.conn.commit()

    def _create_default_schedule(self, vet_id):
        for weekday in range(7):
            self.conn.execute(
                "INSERT OR IGNORE INTO vet_schedules "
                "(vet_id, weekday, working, start_time, end_time) "
                "VALUES (?, ?, ?, ?, ?)",
                (vet_id, weekday, 0 if weekday == 6 else 1,
                 DEFAULT_START, DEFAULT_END))

    def _must_exist(self, table: str, row_id: int, label: str):
        cur = self.conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,))
        if cur.fetchone() is None:
            raise ClinicError(f"No {label} found with ID {row_id}.")

    def _count(self, sql, *params):
        return self.conn.execute(sql, params).fetchone()[0]

    # -- users and login -----------------------------------------------------------
    def user_count(self) -> int:
        return self._count("SELECT COUNT(*) FROM users")

    def create_user(self, username, full_name, role, password) -> int:
        username = require(username, "Username")
        full_name = require(full_name, "Full name")
        if len(username) < 3:
            raise ClinicError("Username must be at least 3 characters.")
        if role not in ROLES:
            raise ClinicError("Please choose a role.")
        if len(password or "") < 6:
            raise ClinicError("Password must be at least 6 characters.")
        try:
            cur = self.conn.execute(
                "INSERT INTO users (username, full_name, role, password_hash) "
                "VALUES (?, ?, ?, ?)",
                (username, full_name, role, hash_password(password)))
        except sqlite3.IntegrityError:
            raise ClinicError("That username is already taken.")
        self.conn.commit()
        return cur.lastrowid

    def authenticate(self, username, password):
        """The user row when the login is right, otherwise None."""
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?",
            ((username or "").strip(),)).fetchone()
        if row is not None and check_password(password or "", row["password_hash"]):
            return row
        return None

    def list_users(self):
        return self.conn.execute(
            "SELECT id, username, full_name, role FROM users ORDER BY id"
        ).fetchall()

    def delete_user(self, user_id, acting_user_id):
        if user_id == acting_user_id:
            raise ClinicError("You cannot delete the account you are signed in with.")
        row = self.conn.execute("SELECT role FROM users WHERE id = ?",
                                (user_id,)).fetchone()
        if row is None:
            raise ClinicError("That user no longer exists.")
        if row["role"] == "admin" and self._count(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'") <= 1:
            raise ClinicError("There must always be at least one administrator.")
        self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()

    def set_password(self, user_id, new_password):
        if len(new_password or "") < 6:
            raise ClinicError("Password must be at least 6 characters.")
        self._must_exist("users", user_id, "user")
        self.conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                          (hash_password(new_password), user_id))
        self.conn.commit()

    def change_password(self, user_id, old_password, new_password):
        row = self.conn.execute("SELECT password_hash FROM users WHERE id = ?",
                                (user_id,)).fetchone()
        if row is None or not check_password(old_password or "",
                                             row["password_hash"]):
            raise ClinicError("Your current password is not correct.")
        self.set_password(user_id, new_password)

    # -- patients (pet + owner details in one record) --------------------------------
    @staticmethod
    def _clean_patient(name, species, owner_name, owner_phone, breed,
                       birth_date, weight_kg, owner_email):
        name = require(name, "Patient name")
        species = require(species, "Species")
        owner_name = require(owner_name, "Owner name")
        owner_phone = require(owner_phone, "Owner phone")
        birth_date = (birth_date or "").strip()
        if birth_date and parse_date(birth_date) > date.today():
            raise ClinicError("Birth date cannot be in the future.")
        if weight_kg is not None and weight_kg <= 0:
            raise ClinicError("Weight must be greater than zero.")
        return (name, species, (breed or "").strip() or None, birth_date or None,
                weight_kg, owner_name, owner_phone,
                (owner_email or "").strip() or None)

    def add_patient(self, name, species, owner_name, owner_phone, breed=None,
                    birth_date=None, weight_kg=None, owner_email=None) -> int:
        values = self._clean_patient(name, species, owner_name, owner_phone,
                                     breed, birth_date, weight_kg, owner_email)
        cur = self.conn.execute(
            "INSERT INTO patients (name, species, breed, birth_date, weight_kg, "
            "owner_name, owner_phone, owner_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            values)
        self.conn.commit()
        return cur.lastrowid

    def update_patient(self, patient_id, name, species, owner_name, owner_phone,
                       breed=None, birth_date=None, weight_kg=None,
                       owner_email=None):
        self._must_exist("patients", patient_id, "patient")
        values = self._clean_patient(name, species, owner_name, owner_phone,
                                     breed, birth_date, weight_kg, owner_email)
        self.conn.execute(
            "UPDATE patients SET name = ?, species = ?, breed = ?, birth_date = ?, "
            "weight_kg = ?, owner_name = ?, owner_phone = ?, owner_email = ? "
            "WHERE id = ?", values + (patient_id,))
        self.conn.commit()

    def get_patient(self, patient_id):
        row = self.conn.execute("SELECT * FROM patients WHERE id = ?",
                                (patient_id,)).fetchone()
        if row is None:
            raise ClinicError(f"No patient found with ID {patient_id}.")
        return row

    def patient_usage(self, patient_id):
        return {
            "appointments": self._count(
                "SELECT COUNT(*) FROM appointments WHERE patient_id = ?", patient_id),
            "medical records": self._count(
                "SELECT COUNT(*) FROM medical_records WHERE patient_id = ?", patient_id),
            "invoices": self._count(
                "SELECT COUNT(*) FROM invoices WHERE patient_id = ?", patient_id),
        }

    def delete_patient(self, patient_id):
        patient = self.get_patient(patient_id)
        used = {k: v for k, v in self.patient_usage(patient_id).items() if v}
        if used:
            names = {"appointments": "appointment",
                     "medical records": "medical record", "invoices": "invoice"}
            parts = ", ".join(plural(v, names[k]) for k, v in used.items())
            raise ClinicError(
                f"{patient['name']} already has {parts}, so the patient cannot "
                "be deleted. Cancel appointments or keep the history instead.")
        self.conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        self.conn.commit()

    def search_patients(self, term=""):
        like = f"%{term.strip()}%"
        return self.conn.execute(
            "SELECT * FROM patients WHERE name LIKE ? OR owner_name LIKE ? "
            "OR species LIKE ? OR owner_phone LIKE ? ORDER BY id",
            (like, like, like, like),
        ).fetchall()

    def owner_names(self):
        rows = self.conn.execute(
            "SELECT DISTINCT owner_name FROM patients ORDER BY owner_name"
        ).fetchall()
        return [r["owner_name"] for r in rows]

    def owner_contact(self, owner_name):
        """Most recent phone/email saved for this owner name (or None)."""
        return self.conn.execute(
            "SELECT owner_phone, owner_email FROM patients "
            "WHERE owner_name = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1",
            (owner_name.strip(),),
        ).fetchone()

    # -- veterinarians ---------------------------------------------------------------
    def add_vet(self, name, specialty=None) -> int:
        name = require(name, "Name")
        cur = self.conn.execute(
            "INSERT INTO veterinarians (name, specialty) VALUES (?, ?)",
            (name, (specialty or "").strip() or None),
        )
        self._create_default_schedule(cur.lastrowid)
        self.conn.commit()
        return cur.lastrowid

    def update_vet(self, vet_id, name, specialty=None):
        self._must_exist("veterinarians", vet_id, "veterinarian")
        self.conn.execute(
            "UPDATE veterinarians SET name = ?, specialty = ? WHERE id = ?",
            (require(name, "Name"), (specialty or "").strip() or None, vet_id))
        self.conn.commit()

    def get_vet(self, vet_id):
        row = self.conn.execute("SELECT * FROM veterinarians WHERE id = ?",
                                (vet_id,)).fetchone()
        if row is None:
            raise ClinicError(f"No veterinarian found with ID {vet_id}.")
        return row

    def delete_vet(self, vet_id):
        vet = self.get_vet(vet_id)
        appts = self._count("SELECT COUNT(*) FROM appointments WHERE vet_id = ?", vet_id)
        records = self._count("SELECT COUNT(*) FROM medical_records WHERE vet_id = ?", vet_id)
        if appts or records:
            raise ClinicError(
                f"{vet['name']} already has {plural(appts, 'appointment')} and "
                f"{plural(records, 'medical record')}, so the veterinarian "
                "cannot be deleted.")
        self.conn.execute("DELETE FROM veterinarians WHERE id = ?", (vet_id,))
        self.conn.commit()

    def list_vets(self):
        return self.conn.execute(
            "SELECT * FROM veterinarians ORDER BY id"
        ).fetchall()

    # -- vet working hours and days off ------------------------------------------------
    def get_schedule(self, vet_id):
        return self.conn.execute(
            "SELECT weekday, working, start_time, end_time FROM vet_schedules "
            "WHERE vet_id = ? ORDER BY weekday", (vet_id,)).fetchall()

    def set_schedule(self, vet_id, rows):
        """rows: (weekday, working, start 'HH:MM', end 'HH:MM') for each day."""
        self._must_exist("veterinarians", vet_id, "veterinarian")
        for weekday, working, start, end in rows:
            if working and to_minutes(start) + SLOT_MINUTES > to_minutes(end):
                raise ClinicError(
                    f"{WEEKDAYS[weekday]}: the end time must be at least "
                    f"{SLOT_MINUTES} minutes after the start time.")
        for weekday, working, start, end in rows:
            self.conn.execute(
                "INSERT INTO vet_schedules (vet_id, weekday, working, start_time, "
                "end_time) VALUES (?, ?, ?, ?, ?) ON CONFLICT (vet_id, weekday) "
                "DO UPDATE SET working = excluded.working, "
                "start_time = excluded.start_time, end_time = excluded.end_time",
                (vet_id, weekday, 1 if working else 0, start, end))
        self.conn.commit()

    def list_days_off(self, vet_id):
        return self.conn.execute(
            "SELECT id, start_date, end_date, COALESCE(note, '') AS note "
            "FROM vet_days_off WHERE vet_id = ? ORDER BY start_date", (vet_id,)
        ).fetchall()

    def add_day_off(self, vet_id, start_date, end_date=None, note=None):
        self._must_exist("veterinarians", vet_id, "veterinarian")
        start = parse_date(start_date)
        end = parse_date(end_date) if (end_date or "").strip() else start
        if end < start:
            raise ClinicError("The last day off cannot be before the first.")
        cur = self.conn.execute(
            "INSERT INTO vet_days_off (vet_id, start_date, end_date, note) "
            "VALUES (?, ?, ?, ?)",
            (vet_id, start.isoformat(), end.isoformat(),
             (note or "").strip() or None))
        self.conn.commit()
        return cur.lastrowid

    def delete_day_off(self, off_id):
        self.conn.execute("DELETE FROM vet_days_off WHERE id = ?", (off_id,))
        self.conn.commit()

    def _availability_problem(self, vet_id, when: datetime):
        """Why the vet cannot take an appointment at this time (None if free)."""
        vet = self.get_vet(vet_id)
        day = when.strftime(DATE_FMT)
        off = self.conn.execute(
            "SELECT 1 FROM vet_days_off WHERE vet_id = ? AND start_date <= ? "
            "AND end_date >= ?", (vet_id, day, day)).fetchone()
        if off:
            return f"{vet['name']} is on leave on {day}."
        sched = self.conn.execute(
            "SELECT * FROM vet_schedules WHERE vet_id = ? AND weekday = ?",
            (vet_id, when.weekday())).fetchone()
        if sched is None:
            return None
        if not sched["working"]:
            return f"{vet['name']} does not work on {when:%A}s."
        minute = when.hour * 60 + when.minute
        if (minute < to_minutes(sched["start_time"])
                or minute + SLOT_MINUTES > to_minutes(sched["end_time"])):
            return (f"{vet['name']} works {sched['start_time']} to "
                    f"{sched['end_time']} on {when:%A}s.")
        return None

    def _overlap_problem(self, vet_id, when: datetime, exclude_id=None):
        existing = self.conn.execute(
            "SELECT id, scheduled_at FROM appointments "
            "WHERE vet_id = ? AND status = 'scheduled'", (vet_id,)).fetchall()
        slot = timedelta(minutes=SLOT_MINUTES)
        for row in existing:
            if row["id"] == exclude_id:
                continue
            other = datetime.strptime(row["scheduled_at"], DATETIME_FMT)
            if abs(other - when) < slot:
                return (f"That vet is already booked around {other:%Y-%m-%d %H:%M} "
                        f"(slots are {SLOT_MINUTES} minutes).")
        return None

    def free_slots(self, vet_id, day: date, exclude_id=None):
        """Start times ('HH:MM') still free for this vet on this day."""
        sched = self.conn.execute(
            "SELECT * FROM vet_schedules WHERE vet_id = ? AND weekday = ?",
            (vet_id, day.weekday())).fetchone()
        if sched is not None and not sched["working"]:
            return []
        start = sched["start_time"] if sched else DEFAULT_START
        end = sched["end_time"] if sched else DEFAULT_END
        free = []
        for text in slot_times(start, end):
            when = datetime.combine(day, datetime.strptime(text, "%H:%M").time())
            if when < datetime.now():
                continue
            if (self._availability_problem(vet_id, when)
                    or self._overlap_problem(vet_id, when, exclude_id)):
                continue
            free.append(text)
        return free

    # -- appointments --------------------------------------------------------------------
    def book_appointment(self, patient_id, vet_id, when: datetime, reason) -> int:
        self._must_exist("patients", patient_id, "patient")
        self._must_exist("veterinarians", vet_id, "veterinarian")
        reason = require(reason, "Reason")
        if when < datetime.now():
            raise ClinicError("Appointments cannot be booked in the past.")
        problem = (self._availability_problem(vet_id, when)
                   or self._overlap_problem(vet_id, when))
        if problem:
            raise ClinicError(problem)
        cur = self.conn.execute(
            "INSERT INTO appointments (patient_id, vet_id, scheduled_at, reason) "
            "VALUES (?, ?, ?, ?)",
            (patient_id, vet_id, when.strftime(DATETIME_FMT), reason),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_appointment(self, appt_id):
        row = self.conn.execute(
            """
            SELECT a.*, p.name AS patient, p.owner_name AS owner, v.name AS vet
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN veterinarians v ON v.id = a.vet_id
            WHERE a.id = ?
            """, (appt_id,)).fetchone()
        if row is None:
            raise ClinicError(f"No appointment found with ID {appt_id}.")
        return row

    def reschedule_appointment(self, appt_id, vet_id, when: datetime, reason):
        appt = self.get_appointment(appt_id)
        if appt["status"] != "scheduled":
            raise ClinicError("Only scheduled appointments can be rescheduled.")
        self._must_exist("veterinarians", vet_id, "veterinarian")
        reason = require(reason, "Reason")
        if when < datetime.now():
            raise ClinicError("Appointments cannot be moved into the past.")
        problem = (self._availability_problem(vet_id, when)
                   or self._overlap_problem(vet_id, when, exclude_id=appt_id))
        if problem:
            raise ClinicError(problem)
        self.conn.execute(
            "UPDATE appointments SET vet_id = ?, scheduled_at = ?, reason = ? "
            "WHERE id = ?",
            (vet_id, when.strftime(DATETIME_FMT), reason, appt_id))
        self.conn.commit()

    def list_appointments(self, on_date: date = None, status: str = None):
        query = """
            SELECT a.id, a.scheduled_at, p.name AS patient,
                   p.owner_name AS owner, v.name AS vet, a.reason, a.status
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN veterinarians v ON v.id = a.vet_id
            WHERE 1 = 1
        """
        params = []
        if on_date:
            query += " AND a.scheduled_at LIKE ?"
            params.append(f"{on_date:{DATE_FMT}}%")
        if status:
            query += " AND a.status = ?"
            params.append(status)
        query += " ORDER BY a.scheduled_at"
        return self.conn.execute(query, params).fetchall()

    def todays_appointments(self):
        today = date.today().strftime(DATE_FMT)
        return self.conn.execute(
            """
            SELECT a.id, substr(a.scheduled_at, 12, 5) AS time, p.name AS patient,
                   p.owner_name AS owner, v.name AS vet, a.reason, a.status
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN veterinarians v ON v.id = a.vet_id
            WHERE a.scheduled_at LIKE ? ORDER BY a.scheduled_at
            """, (f"{today}%",)).fetchall()

    def upcoming_appointments(self, limit=10):
        now = datetime.now().strftime(DATETIME_FMT)
        return self.conn.execute(
            """
            SELECT a.id, a.scheduled_at, p.name AS patient,
                   p.owner_name AS owner, v.name AS vet, a.reason
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN veterinarians v ON v.id = a.vet_id
            WHERE a.status = 'scheduled' AND a.scheduled_at >= ?
            ORDER BY a.scheduled_at LIMIT ?
            """,
            (now, limit),
        ).fetchall()

    def patient_appointments(self, patient_id):
        return self.conn.execute(
            """
            SELECT a.id, a.scheduled_at, v.name AS vet, a.reason, a.status
            FROM appointments a JOIN veterinarians v ON v.id = a.vet_id
            WHERE a.patient_id = ? ORDER BY a.scheduled_at DESC
            """, (patient_id,)).fetchall()

    def set_appointment_status(self, appt_id: int, status: str):
        if status not in ("completed", "cancelled"):
            raise ClinicError("Status must be 'completed' or 'cancelled'.")
        row = self.conn.execute(
            "SELECT status FROM appointments WHERE id = ?", (appt_id,)
        ).fetchone()
        if row is None:
            raise ClinicError(f"No appointment found with ID {appt_id}.")
        if row["status"] != "scheduled":
            raise ClinicError(f"Appointment is already {row['status']}.")
        self.conn.execute(
            "UPDATE appointments SET status = ? WHERE id = ?", (status, appt_id)
        )
        self.conn.commit()

    def delete_appointment(self, appt_id):
        self.get_appointment(appt_id)
        self.conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        self.conn.commit()

    def complete_appointment(self, appt_id, record=None, invoice=None):
        """Mark a visit completed and save its medical record and invoice
        together, so nothing is half-saved.

        record  = {"diagnosis", "treatment", "notes"} or None
        invoice = {"description", "amount_cents", "method"} or None
                  (method None means not paid yet)
        """
        appt = self.get_appointment(appt_id)
        if appt["status"] != "scheduled":
            raise ClinicError(f"Appointment is already {appt['status']}.")
        if record is not None:
            require(record.get("diagnosis"), "Diagnosis")
        if invoice is not None:
            require(invoice.get("description"), "Invoice description")
            if invoice.get("method") and invoice["method"] not in PAYMENT_METHODS:
                raise ClinicError("Please choose a payment method.")
        today = date.today()
        visit = min(datetime.strptime(appt["scheduled_at"][:10], DATE_FMT).date(),
                    today)
        result = {"record_id": None, "invoice_id": None}
        with self.conn:  # one transaction: all or nothing
            self.conn.execute(
                "UPDATE appointments SET status = 'completed' WHERE id = ?",
                (appt_id,))
            if record is not None:
                cur = self.conn.execute(
                    "INSERT INTO medical_records (patient_id, vet_id, visit_date, "
                    "diagnosis, treatment, notes, appointment_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (appt["patient_id"], appt["vet_id"], visit.strftime(DATE_FMT),
                     record["diagnosis"].strip(),
                     (record.get("treatment") or "").strip() or None,
                     (record.get("notes") or "").strip() or None, appt_id))
                result["record_id"] = cur.lastrowid
            if invoice is not None:
                method = invoice.get("method")
                cur = self.conn.execute(
                    "INSERT INTO invoices (patient_id, description, amount_cents, "
                    "issued_on, paid, payment_method, paid_on, appointment_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (appt["patient_id"], invoice["description"].strip(),
                     invoice["amount_cents"], today.strftime(DATE_FMT),
                     1 if method else 0, method or None,
                     today.strftime(DATE_FMT) if method else None, appt_id))
                result["invoice_id"] = cur.lastrowid
        return result

    # -- medical records --------------------------------------------------------------------
    def add_record(self, patient_id, vet_id, diagnosis, treatment=None,
                   notes=None, visit_date: date = None) -> int:
        self._must_exist("patients", patient_id, "patient")
        self._must_exist("veterinarians", vet_id, "veterinarian")
        diagnosis = require(diagnosis, "Diagnosis")
        visit_date = visit_date or date.today()
        cur = self.conn.execute(
            "INSERT INTO medical_records "
            "(patient_id, vet_id, visit_date, diagnosis, treatment, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (patient_id, vet_id, visit_date.strftime(DATE_FMT), diagnosis,
             (treatment or "").strip() or None, (notes or "").strip() or None),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_record(self, record_id):
        row = self.conn.execute("SELECT * FROM medical_records WHERE id = ?",
                                (record_id,)).fetchone()
        if row is None:
            raise ClinicError(f"No medical record found with ID {record_id}.")
        return row

    def update_record(self, record_id, vet_id, visit_date: date, diagnosis,
                      treatment=None, notes=None):
        self.get_record(record_id)
        self._must_exist("veterinarians", vet_id, "veterinarian")
        self.conn.execute(
            "UPDATE medical_records SET vet_id = ?, visit_date = ?, diagnosis = ?, "
            "treatment = ?, notes = ? WHERE id = ?",
            (vet_id, visit_date.strftime(DATE_FMT),
             require(diagnosis, "Diagnosis"),
             (treatment or "").strip() or None, (notes or "").strip() or None,
             record_id))
        self.conn.commit()

    def delete_record(self, record_id):
        self.get_record(record_id)
        self.conn.execute("DELETE FROM medical_records WHERE id = ?", (record_id,))
        self.conn.commit()

    def patient_history(self, patient_id: int):
        patient = self.get_patient(patient_id)
        records = self.conn.execute(
            """
            SELECT r.id, r.visit_date, v.name AS vet, r.diagnosis, r.treatment,
                   r.notes
            FROM medical_records r JOIN veterinarians v ON v.id = r.vet_id
            WHERE r.patient_id = ? ORDER BY r.visit_date DESC, r.id DESC
            """,
            (patient_id,),
        ).fetchall()
        return patient, records

    # -- billing -------------------------------------------------------------------------------
    def create_invoice(self, patient_id, description, amount_cents: int) -> int:
        self._must_exist("patients", patient_id, "patient")
        description = require(description, "Description")
        cur = self.conn.execute(
            "INSERT INTO invoices (patient_id, description, amount_cents, issued_on) "
            "VALUES (?, ?, ?, ?)",
            (patient_id, description, amount_cents,
             date.today().strftime(DATE_FMT)),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_invoice(self, invoice_id):
        row = self.conn.execute(
            """
            SELECT i.*, p.name AS patient, p.owner_name AS owner,
                   p.owner_phone AS owner_phone
            FROM invoices i JOIN patients p ON p.id = i.patient_id WHERE i.id = ?
            """, (invoice_id,)).fetchone()
        if row is None:
            raise ClinicError(f"No invoice found with ID {invoice_id}.")
        return row

    def update_invoice(self, invoice_id, description, amount_cents):
        invoice = self.get_invoice(invoice_id)
        if invoice["voided"]:
            raise ClinicError("Void invoices cannot be changed.")
        if invoice["paid"]:
            raise ClinicError("Paid invoices cannot be changed.")
        self.conn.execute(
            "UPDATE invoices SET description = ?, amount_cents = ? WHERE id = ?",
            (require(description, "Description"), amount_cents, invoice_id))
        self.conn.commit()

    def void_invoice(self, invoice_id, reason):
        """Cancel an unpaid invoice but keep it on record, marked as void.
        (Paid invoices record a payment, so they can never be voided.)"""
        invoice = self.get_invoice(invoice_id)
        if invoice["voided"]:
            raise ClinicError("This invoice is already void.")
        if invoice["paid"]:
            raise ClinicError("Paid invoices cannot be voided because they "
                              "record a payment.")
        reason = require(reason, "Reason")
        self.conn.execute(
            "UPDATE invoices SET voided = 1, void_reason = ?, voided_on = ? "
            "WHERE id = ?", (reason, date.today().strftime(DATE_FMT), invoice_id))
        self.conn.commit()

    def pay_invoice(self, invoice_id: int, method="Cash"):
        invoice = self.get_invoice(invoice_id)
        if invoice["voided"]:
            raise ClinicError("A void invoice cannot be paid.")
        if invoice["paid"]:
            raise ClinicError("Invoice is already paid.")
        if method not in PAYMENT_METHODS:
            raise ClinicError("Please choose a payment method.")
        self.conn.execute(
            "UPDATE invoices SET paid = 1, payment_method = ?, paid_on = ? "
            "WHERE id = ?", (method, date.today().strftime(DATE_FMT), invoice_id))
        self.conn.commit()

    _INVOICE_SQL = """
        SELECT i.id, i.issued_on, p.name AS patient, p.owner_name AS owner,
               i.description, printf('%.2f', i.amount_cents / 100.0) AS amount,
               i.amount_cents,
               CASE WHEN i.voided THEN 'Void' WHEN i.paid THEN 'Paid'
                    ELSE 'Unpaid' END AS status,
               CASE WHEN i.voided THEN 'void' WHEN i.paid THEN 'paid'
                    ELSE 'unpaid' END AS tag,
               COALESCE(i.payment_method, '') AS method,
               COALESCE(i.paid_on, '') AS paid_on,
               COALESCE(i.void_reason, '') AS void_reason
        FROM invoices i JOIN patients p ON p.id = i.patient_id
    """

    def list_invoices(self, status="outstanding"):
        where = {"outstanding": "WHERE i.paid = 0 AND i.voided = 0",
                 "paid": "WHERE i.paid = 1",
                 "void": "WHERE i.voided = 1"}.get(status, "")
        return self.conn.execute(
            f"{self._INVOICE_SQL} {where} ORDER BY i.issued_on, i.id").fetchall()

    def outstanding_invoices(self):
        return self.list_invoices("outstanding")

    def patient_invoices(self, patient_id):
        return self.conn.execute(
            f"{self._INVOICE_SQL} WHERE i.patient_id = ? "
            "ORDER BY i.issued_on DESC, i.id DESC", (patient_id,)).fetchall()

    def outstanding_total_cents(self, patient_id=None) -> int:
        sql = ("SELECT COALESCE(SUM(amount_cents), 0) FROM invoices "
               "WHERE paid = 0 AND voided = 0")
        params = ()
        if patient_id is not None:
            sql += " AND patient_id = ?"
            params = (patient_id,)
        return self._count(sql, *params)

    # -- dashboard and reports ---------------------------------------------------------------------
    def stats(self):
        today = date.today().strftime(DATE_FMT)
        return {
            "patients": self._count("SELECT COUNT(*) FROM patients"),
            "vets": self._count("SELECT COUNT(*) FROM veterinarians"),
            "today": self._count(
                "SELECT COUNT(*) FROM appointments WHERE status = 'scheduled' "
                "AND scheduled_at LIKE ?", f"{today}%"),
            "outstanding_cents": self.outstanding_total_cents(),
        }

    def weekly_counts(self, before=5, after=2):
        """Appointments (not cancelled) per week: [(monday, count), ...]."""
        monday = date.today() - timedelta(days=date.today().weekday())
        first = monday - timedelta(weeks=before)
        last = monday + timedelta(weeks=after + 1)
        rows = self.conn.execute(
            "SELECT substr(scheduled_at, 1, 10) AS day FROM appointments "
            "WHERE status != 'cancelled' AND day >= ? AND day < ?",
            (first.isoformat(), last.isoformat())).fetchall()
        counts = {first + timedelta(weeks=i): 0 for i in range(before + after + 1)}
        for row in rows:
            day = datetime.strptime(row["day"], DATE_FMT).date()
            counts[day - timedelta(days=day.weekday())] += 1
        return sorted(counts.items())

    @staticmethod
    def period_bounds(kind, day: date):
        if kind == "Monthly":
            last = pycal.monthrange(day.year, day.month)[1]
            return day.replace(day=1), day.replace(day=last)
        return day, day

    def report_summary(self, start: date, end: date):
        s, e = start.isoformat(), end.isoformat()
        by_status = {r["status"]: r["n"] for r in self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM appointments "
            "WHERE substr(scheduled_at, 1, 10) BETWEEN ? AND ? GROUP BY status",
            (s, e))}
        issued = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS cents "
            "FROM invoices WHERE voided = 0 AND issued_on BETWEEN ? AND ?",
            (s, e)).fetchone()
        collected = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS cents "
            "FROM invoices WHERE paid = 1 AND COALESCE(paid_on, issued_on) "
            "BETWEEN ? AND ?", (s, e)).fetchone()
        outstanding = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS cents "
            "FROM invoices WHERE paid = 0 AND voided = 0 "
            "AND issued_on BETWEEN ? AND ?", (s, e)).fetchone()
        by_vet = self.conn.execute(
            """
            SELECT v.name AS vet, COUNT(*) AS total,
                   SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) AS completed
            FROM appointments a JOIN veterinarians v ON v.id = a.vet_id
            WHERE substr(a.scheduled_at, 1, 10) BETWEEN ? AND ?
            GROUP BY v.id ORDER BY total DESC, v.name
            """, (s, e)).fetchall()
        return {
            "start": start, "end": end,
            "appointments": sum(by_status.values()),
            "scheduled": by_status.get("scheduled", 0),
            "completed": by_status.get("completed", 0),
            "cancelled": by_status.get("cancelled", 0),
            "visits": self._count(
                "SELECT COUNT(*) FROM medical_records WHERE visit_date BETWEEN ? AND ?",
                s, e),
            "issued_count": issued["n"], "issued_cents": issued["cents"],
            "collected_count": collected["n"], "collected_cents": collected["cents"],
            "void_count": self._count(
                "SELECT COUNT(*) FROM invoices WHERE voided = 1 "
                "AND issued_on BETWEEN ? AND ?", s, e),
            "outstanding_count": outstanding["n"],
            "outstanding_cents": outstanding["cents"],
            "by_vet": by_vet,
        }

    def report_appointments(self, start: date, end: date):
        return self.conn.execute(
            """
            SELECT a.id, a.scheduled_at, p.name AS patient,
                   p.owner_name AS owner, v.name AS vet, a.reason, a.status
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN veterinarians v ON v.id = a.vet_id
            WHERE substr(a.scheduled_at, 1, 10) BETWEEN ? AND ?
            ORDER BY a.scheduled_at
            """, (start.isoformat(), end.isoformat())).fetchall()

    def report_invoices(self, start: date, end: date):
        return self.conn.execute(
            f"{self._INVOICE_SQL} WHERE i.issued_on BETWEEN ? AND ? "
            "ORDER BY i.issued_on, i.id",
            (start.isoformat(), end.isoformat())).fetchall()

    # -- backup --------------------------------------------------------------------------------------
    def backup(self, keep=10):
        """Copy the live database into the backups folder (newest `keep` kept)."""
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(self.backup_dir, f"petvault-{stamp}.db")
        dest = sqlite3.connect(target)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        files = sorted(f for f in os.listdir(self.backup_dir)
                       if f.startswith("petvault-") and f.endswith(".db"))
        for old in files[:-keep]:
            os.remove(os.path.join(self.backup_dir, old))
        return target

    def last_backup(self):
        """(file name, time) of the newest backup, or None."""
        if not os.path.isdir(self.backup_dir):
            return None
        files = sorted(f for f in os.listdir(self.backup_dir)
                       if f.startswith("petvault-") and f.endswith(".db"))
        if not files:
            return None
        newest = os.path.join(self.backup_dir, files[-1])
        return files[-1], datetime.fromtimestamp(os.path.getmtime(newest))


# --------------------------------------------------------------------------
# Files: CSV, a tiny PDF writer, and opening files in the system viewer
# --------------------------------------------------------------------------
CURRENCY = "₱"
CURRENCY_CODE = "PHP"  # used in PDFs (the PDF's built-in fonts have no ₱ sign)


def money(cents):
    return f"{CURRENCY}{cents / 100:,.2f}"


def pdf_money(cents):
    return f"{CURRENCY_CODE} {cents / 100:,.2f}"


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def build_pdf(lines, mono=False):
    """A very small text-only PDF writer (A4, standard fonts).

    lines: strings, (text, size, bold) tuples, or ("row", size, columns) where
    columns is a list of (x position, text, bold). Returns the PDF as bytes."""
    page_w, page_h, margin = 595, 842, 56
    items = []
    for line in lines:
        if isinstance(line, str):
            items.append((11, [(margin, line, False)]))
        elif line[0] == "row":
            items.append((line[1], line[2]))
        else:
            items.append((line[1], [(margin, line[0], line[2])]))
    pages, current, y = [], [], page_h - margin
    for size, cols in items:
        leading = size * 1.5
        if y - leading < margin:
            pages.append(current)
            current, y = [], page_h - margin
        y -= leading
        current.append((size, cols, y))
    pages.append(current)

    def esc(text):
        text = text.encode("latin-1", "replace").decode("latin-1")
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    fonts = ("Courier", "Courier-Bold") if mono else ("Helvetica", "Helvetica-Bold")
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: f"<< /Type /Font /Subtype /Type1 /BaseFont /{fonts[0]} "
           f"/Encoding /WinAnsiEncoding >>".encode(),
        4: f"<< /Type /Font /Subtype /Type1 /BaseFont /{fonts[1]} "
           f"/Encoding /WinAnsiEncoding >>".encode(),
    }
    kids, number = [], 5
    for page in pages:
        content = "\n".join(
            f"BT /{'F2' if bold else 'F1'} {size} Tf {x} {y:.1f} Td "
            f"({esc(text)}) Tj ET"
            for size, cols, y in page for x, text, bold in cols)
        data = content.encode("latin-1", "replace")
        page_id, content_id = number, number + 1
        objects[content_id] = (b"<< /Length %d >>\nstream\n" % len(data)
                               + data + b"\nendstream")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>").encode()
        kids.append(f"{page_id} 0 R")
        number += 2
    objects[2] = (f"<< /Type /Pages /Kids [{' '.join(kids)}] "
                  f"/Count {len(kids)} >>").encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in sorted(objects):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def write_pdf(path, lines, mono=False):
    with open(path, "wb") as handle:
        handle.write(build_pdf(lines, mono))


def receipt_lines(invoice):
    """Lines for a one-page receipt of a paid invoice (a database row)."""
    def row(label, value):
        return ("row", 11, [(56, label, True), (190, value, False)])
    lines = [("PetVault Veterinary Clinic", 20, True),
             ("Official receipt", 13, False), "", "",
             row("Receipt no.", f"{invoice['id']:06d}"),
             row("Date paid", invoice["paid_on"] or invoice["issued_on"]),
             row("Issued on", invoice["issued_on"]), "",
             row("Patient", invoice["patient"]),
             row("Owner", invoice["owner"]), ""]
    for i, part in enumerate(textwrap.wrap(invoice["description"], 58) or [""]):
        lines.append(row("Description" if i == 0 else "", part))
    lines += ["", row("Amount paid", pdf_money(invoice["amount_cents"])),
              row("Payment method", invoice["payment_method"] or "-"), "", "",
              ("Thank you for trusting us with your pet.", 11, False)]
    return lines


def summary_lines(report):
    """Lines (monospaced) for a printable summary of a report period."""
    start, end = report["start"], report["end"]
    period = (start.strftime("%d %B %Y") if start == end
              else f"{start:%d %B %Y} to {end:%d %B %Y}")
    lines = [("PetVault: Clinic summary", 16, True), (period, 11, False), ""]

    def add(label, value):
        lines.append(f"{label:<30}{value:>16}")
    add("Appointments", report["appointments"])
    add("  Scheduled", report["scheduled"])
    add("  Completed", report["completed"])
    add("  Cancelled", report["cancelled"])
    add("Medical records (visits)", report["visits"])
    lines.append("")
    add("Invoices issued", report["issued_count"])
    add("  Value issued", pdf_money(report["issued_cents"]))
    add("Payments collected", report["collected_count"])
    add("  Amount collected", pdf_money(report["collected_cents"]))
    add("Still unpaid (issued here)", pdf_money(report["outstanding_cents"]))
    add("Voided invoices", report["void_count"])
    lines += ["", ("Veterinarian workload", 12, True),
              f"{'Veterinarian':<30}{'Appts':>8}{'Done':>8}"]
    for row in report["by_vet"]:
        lines.append(f"{row['vet'][:29]:<30}{row['total']:>8}{row['completed']:>8}")
    if not report["by_vet"]:
        lines.append("(no appointments in this period)")
    return lines


def open_file(path):
    """Open a file or folder with the system's default program."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except (OSError, AttributeError):
        return False


# --------------------------------------------------------------------------
# Demo data
# --------------------------------------------------------------------------
DEMO_USERS = [
    ("admin", "Clinic Administrator", "admin", "admin123"),
    ("reception", "Front Desk", "receptionist", "reception123"),
    ("dr.cruz", "Dr. Ana Cruz", "vet", "vet12345"),
]


def load_demo_data(clinic: Clinic):
    if clinic.user_count() == 0:
        for username, full_name, role, password in DEMO_USERS:
            clinic.create_user(username, full_name, role, password)
        print("Demo logins:")
        for username, _name, role, password in DEMO_USERS:
            print(f"  {username} / {password}   ({ROLE_LABELS[role]})")
    if clinic.search_patients(""):
        print("Database already has patients; skipping sample patients.")
        return
    buddy = clinic.add_patient(
        "Buddy", "Dog", "Maria Santos", "0917-555-0101", breed="Golden Retriever",
        birth_date="2020-03-14", weight_kg=29.5, owner_email="maria@example.com")
    mimi = clinic.add_patient(
        "Mimi", "Cat", "Maria Santos", "0917-555-0101", breed="Persian",
        birth_date="2021-07-02", weight_kg=4.2, owner_email="maria@example.com")
    rocky = clinic.add_patient(
        "Rocky", "Dog", "John Reyes", "0918-555-0202", breed="Shih Tzu",
        birth_date="2019-11-20", weight_kg=7.8)
    dr_cruz = clinic.add_vet("Dr. Ana Cruz", "General practice")
    dr_lim = clinic.add_vet("Dr. Paolo Lim", "Surgery")

    # a few appointments in the past, today and the coming days (for the dashboard)
    def insert(patient, vet, day_offset, hour, minute, reason, status):
        when = (datetime.now() + timedelta(days=day_offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        clinic.conn.execute(
            "INSERT INTO appointments (patient_id, vet_id, scheduled_at, reason, "
            "status) VALUES (?, ?, ?, ?, ?)",
            (patient, vet, when.strftime(DATETIME_FMT), reason, status))
    history = [(-33, buddy, dr_cruz, "Checkup"), (-27, mimi, dr_cruz, "Vaccination"),
               (-26, rocky, dr_lim, "Dental check"), (-20, buddy, dr_lim, "Limping"),
               (-19, mimi, dr_cruz, "Ear infection"), (-13, rocky, dr_cruz, "Checkup"),
               (-12, buddy, dr_cruz, "Skin check"), (-11, mimi, dr_lim, "Checkup"),
               (-6, rocky, dr_cruz, "Vaccination"), (-5, buddy, dr_lim, "Checkup")]
    for offset, patient, vet, reason in history:
        insert(patient, vet, offset, 10, 0, reason, "completed")
    insert(mimi, dr_cruz, -2, 14, 30, "Follow-up", "cancelled")
    insert(buddy, dr_cruz, 0, 10, 30, "Annual vaccination", "scheduled")
    insert(rocky, dr_lim, 0, 14, 0, "Dental check", "scheduled")
    insert(mimi, dr_cruz, 1, 9, 0, "Ear infection follow-up", "scheduled")
    insert(buddy, dr_lim, 3, 11, 0, "Weight check", "scheduled")
    insert(rocky, dr_cruz, 8, 15, 30, "Vaccination booster", "scheduled")
    clinic.conn.commit()

    clinic.add_record(buddy, dr_cruz, "Healthy", "Rabies booster",
                      "Weight stable", date.today() - timedelta(days=33))
    clinic.add_record(mimi, dr_cruz, "Mild ear infection", "Ear drops for 7 days",
                      None, date.today() - timedelta(days=19))
    old = clinic.create_invoice(buddy, "Checkup and rabies booster",
                                parse_money_to_cents("850.00"))
    clinic.pay_invoice(old, "Cash")
    clinic.create_invoice(mimi, "Consultation and ear drops",
                          parse_money_to_cents("1250.00"))
    mistake = clinic.create_invoice(rocky, "Nail trim (entered twice)",
                                    parse_money_to_cents("150.00"))
    clinic.void_invoice(mistake, "Duplicate entry")
    print("Sample patients, vets and appointments loaded.")

# ==========================================================================
# Interface
# ==========================================================================
APP_NAME = "PetVault"
APP_SUBTITLE = "Veterinary Clinic Patient & Appointment Management System"

# Soft, pet-friendly palette: cream, peach, mint, sky and rose.
BG = "#FFF8F1"          # page background (cream)
SIDEBAR = "#FFEBDD"     # sidebar (light peach)
NAV_HOVER = "#FFDCC6"
NAV_ACTIVE = "#FFC9A6"
CARD = "#FFFFFF"
FIELD = "#FFF4EA"       # input background
BORDER = "#F0D9C8"
HEADING = "#FFE6D5"     # table header
TEXT = "#4A342D"        # warm dark brown
MUTED = "#8C7068"
MUTED_DARK = "#6F5A52"
PRIMARY, PRIMARY_H = "#F4A070", "#EE8D56"   # soft orange
MINT, MINT_H = "#BFE8D4", "#A7DCC3"
ROSE, ROSE_H = "#F7B8B8", "#F2A0A0"
SAND, SAND_H = "#F3E3D6", "#EBD3C1"
PEACH, SKY, LAVENDER, MINT_BG, PINK = (
    "#FFE0CC", "#DCEBFA", "#E8E0F8", "#D9F2E6", "#FFDDE5")

BUTTON_KINDS = {
    "primary": (PRIMARY, PRIMARY_H),
    "mint": (MINT, MINT_H),
    "danger": (ROSE, ROSE_H),
    "ghost": (SAND, SAND_H),
}

DANGER_TEXT = "#B3392F"
OK_TEXT = "#2F8F5B"
FONT = "TkDefaultFont"  # replaced by the real font family in apply_theme()
SPECIES = ["Dog", "Cat", "Rabbit", "Bird", "Hamster", "Reptile", "Other"]
TIME_SLOTS = slot_times(DEFAULT_START, DEFAULT_END)
SCHEDULE_TIMES = [from_minutes(m) for m in range(5 * 60, 22 * 60 + 1, 30)]


# --------------------------------------------------------------------------
# Theme (ttk parts: tables and scrollbars)
# --------------------------------------------------------------------------
def apply_theme(root):
    global FONT
    default = tkfont.nametofont("TkDefaultFont")
    default.configure(size=10)
    FONT = default.actual("family")

    root.configure(bg=BG)
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("Treeview", rowheight=32, background=CARD,
                    fieldbackground=CARD, foreground=TEXT, borderwidth=0,
                    font=(FONT, 10))
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Treeview.Heading", background=HEADING, foreground=TEXT,
                    font=(FONT, 10, "bold"), padding=(10, 8), relief="flat",
                    borderwidth=0)
    style.map("Treeview.Heading", background=[("active", NAV_HOVER)])
    style.map("Treeview", background=[("selected", NAV_ACTIVE)],
              foreground=[("selected", TEXT)])

    for bar in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(bar, background=BORDER, troughcolor=CARD,
                        bordercolor=CARD, lightcolor=BORDER, darkcolor=BORDER,
                        arrowcolor=MUTED, relief="flat")
        style.map(bar, background=[("active", NAV_ACTIVE)])


# --------------------------------------------------------------------------
# Drawing helpers and rounded widgets
# --------------------------------------------------------------------------
def round_rect(canvas, x1, y1, x2, y2, radius, **kw):
    """Draw a rounded rectangle on a canvas (smoothed polygon)."""
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
              x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
              x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


def draw_paw(canvas, x, y, size, color):
    """Paw print (one pad, four toes) inside a size x size box at (x, y)."""
    s = size / 46.0
    for x1, y1, x2, y2 in ((11, 24, 35, 44), (2, 17, 12, 29), (11, 5, 22, 20),
                           (24, 5, 35, 20), (34, 17, 44, 29)):
        canvas.create_oval(x + x1 * s, y + y1 * s, x + x2 * s, y + y2 * s,
                           fill=color, outline=color)


class Card(tk.Frame):
    """A rounded panel. Put content in card.body."""

    def __init__(self, parent, fill=CARD, border=BORDER, radius=20, pad=18,
                 parent_bg=BG):
        super().__init__(parent, bg=parent_bg)
        self._fill, self._border, self._radius = fill, border, radius
        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._canvas.bind("<Configure>", self._redraw)

    def _redraw(self, event):
        self._canvas.delete("all")
        round_rect(self._canvas, 1, 1, event.width - 2, event.height - 2,
                   self._radius, fill=self._fill, outline=self._border)


class PillButton(tk.Canvas):
    """A rounded button with hover and press feedback."""

    def __init__(self, parent, text, command, kind="primary", parent_bg=CARD,
                 small=False):
        label_font = tkfont.Font(family=FONT, size=10, weight="bold")
        pad_x, pad_y = (28, 12) if small else (40, 18)
        width = label_font.measure(text) + pad_x
        height = label_font.metrics("linespace") + pad_y
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._btn_fill, self._btn_hover = BUTTON_KINDS[kind]
        self._btn_command = command
        self._btn_size = (width, height)
        self._btn_shape = round_rect(self, 1, 1, width - 1, height - 1, 16,
                                     fill=self._btn_fill, outline=self._btn_fill)
        self.create_text(width / 2, height / 2, text=text, fill=TEXT,
                         font=(FONT, 10, "bold"))
        self.bind("<Enter>", lambda _e: self._paint(self._btn_hover))
        self.bind("<Leave>", lambda _e: self._paint(self._btn_fill))
        self.bind("<ButtonPress-1>", lambda _e: self._paint(self._btn_hover))
        self.bind("<ButtonRelease-1>", self._release)

    def set_kind(self, kind):
        """Change the colour (used by tab-like button rows)."""
        self._btn_fill, self._btn_hover = BUTTON_KINDS[kind]
        self._paint(self._btn_fill)

    def _paint(self, color):
        self.itemconfigure(self._btn_shape, fill=color, outline=color)

    def _release(self, event):
        width, height = self._btn_size
        inside = 0 <= event.x < width and 0 <= event.y < height
        self._paint(self._btn_hover if inside else self._btn_fill)
        if inside:
            self._btn_command()


class ToggleButton(tk.Canvas):
    """A small on/off pill, for example 'Working' / 'Day off'."""

    def __init__(self, parent, on_text="Working", off_text="Day off", value=True,
                 parent_bg=CARD, command=None):
        super().__init__(parent, width=100, height=32, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._tg_texts = (on_text, off_text)
        self._tg_on = bool(value)
        self._tg_command = command
        self.bind("<Button-1>", self._flip)
        self._draw()

    def get(self):
        return self._tg_on

    def set(self, value):
        self._tg_on = bool(value)
        self._draw()

    def _flip(self, _event):
        self.set(not self._tg_on)
        if self._tg_command:
            self._tg_command(self._tg_on)

    def _draw(self):
        self.delete("all")
        fill = MINT if self._tg_on else ROSE
        round_rect(self, 1, 1, 99, 31, 16, fill=fill, outline=fill)
        self.create_text(50, 16, text=self._tg_texts[0 if self._tg_on else 1],
                         fill=TEXT, font=(FONT, 9, "bold"))


class NavButton(tk.Canvas):
    """A sidebar menu item shaped like a pill."""

    def __init__(self, parent, text, command):
        super().__init__(parent, width=10, height=42, bg=SIDEBAR,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._nav_text, self._nav_command = text, command
        self._nav_active = self._nav_hover = False
        self._nav_width = 0
        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self._nav_command())

    def _on_resize(self, event):
        self._nav_width = event.width
        self._draw()

    def _set_hover(self, value):
        self._nav_hover = value
        self._draw()

    def set_active(self, value):
        self._nav_active = value
        self._draw()

    def _draw(self):
        if not self._nav_width:
            return
        self.delete("all")
        if self._nav_active:
            fill = NAV_ACTIVE
        elif self._nav_hover:
            fill = NAV_HOVER
        else:
            fill = SIDEBAR
        round_rect(self, 2, 2, self._nav_width - 2, 40, 16, fill=fill,
                   outline=fill)
        self.create_text(20, 21, text=self._nav_text, anchor="w", fill=TEXT,
                         font=(FONT, 11, "bold" if self._nav_active else "normal"))


class CalendarPopup(tk.Toplevel):
    """A small month calendar that opens under a date field."""

    def __init__(self, owner, on_pick):
        super().__init__(owner)
        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._on_pick = on_pick
        self._year, self._month = date.today().year, date.today().month
        self._selected = self._lo = self._hi = None
        self._days = []
        outer = tk.Frame(self, bg=BORDER)
        outer.pack()
        body = tk.Frame(outer, bg=CARD)
        body.pack(padx=1, pady=1)

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", padx=8, pady=(8, 4))
        for text, step in (("<<", -12), ("<", -1)):
            self._nav(head, text, step).pack(side="left")
        for text, step in ((">>", 12), (">", 1)):
            self._nav(head, text, step).pack(side="right")
        self._title = tk.Label(head, bg=CARD, fg=TEXT, font=(FONT, 10, "bold"))
        self._title.pack(expand=True)

        grid = tk.Frame(body, bg=CARD)
        grid.pack(padx=8)
        for col, name in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            tk.Label(grid, text=name, width=4, bg=CARD, fg=MUTED,
                     font=(FONT, 9)).grid(row=0, column=col)
        self._cells = []
        for row in range(6):
            for col in range(7):
                cell = tk.Label(grid, width=4, bg=CARD, fg=TEXT, font=(FONT, 10),
                                cursor="hand2")
                cell.grid(row=row + 1, column=col, pady=1)
                cell.bind("<Button-1>", lambda _e, r=row, c=col: self._click(r, c))
                cell.bind("<Enter>", lambda _e, r=row, c=col: self._hover(r, c, True))
                cell.bind("<Leave>", lambda _e, r=row, c=col: self._hover(r, c, False))
                self._cells.append(cell)
        today = tk.Label(body, text="Today", bg=CARD, fg=PRIMARY_H, cursor="hand2",
                         font=(FONT, 9, "bold"))
        today.pack(pady=(4, 8))
        today.bind("<Button-1>", lambda _e: self._pick_today())

    def _nav(self, parent, text, step):
        label = tk.Label(parent, text=text, bg=CARD, fg=MUTED_DARK, padx=6,
                         cursor="hand2", font=(FONT, 10, "bold"))
        label.bind("<Button-1>", lambda _e: self._shift(step))
        return label

    def show(self, current, lo, hi, x, y):
        day = current or date.today()
        self._year, self._month = day.year, day.month
        self._selected, self._lo, self._hi = current, lo, hi
        self._render()
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()

    def _shift(self, months):
        index = self._year * 12 + (self._month - 1) + months
        self._year, self._month = index // 12, index % 12 + 1
        self._render()
        return "break"

    def _blocked(self, day):
        return bool((self._lo and day < self._lo) or (self._hi and day > self._hi))

    def _base_bg(self, day):
        if day == self._selected:
            return PRIMARY
        return PEACH if day == date.today() else CARD

    def _render(self):
        self._title.configure(text=f"{pycal.month_name[self._month]} {self._year}")
        weeks = pycal.Calendar(6).monthdatescalendar(self._year, self._month)
        while len(weeks) < 6:
            weeks.append([weeks[-1][-1] + timedelta(days=i + 1) for i in range(7)])
        self._weeks = weeks
        self._days = []
        for r, week in enumerate(weeks):
            row = []
            for c, day in enumerate(week):
                blocked = self._blocked(day)
                fg = BORDER if blocked else (
                    TEXT if day.month == self._month else MUTED)
                self._cells[r * 7 + c].configure(text=str(day.day), fg=fg,
                                                 bg=self._base_bg(day))
                row.append(None if blocked else day)
            self._days.append(row)

    def _hover(self, r, c, inside):
        day = self._weeks[r][c]
        if self._days[r][c] is None:
            return
        self._cells[r * 7 + c].configure(
            bg=NAV_HOVER if inside and day != self._selected else self._base_bg(day))

    def _click(self, r, c):
        day = self._days[r][c]
        if day is not None:
            self._on_pick(day)
        return "break"

    def _pick_today(self):
        today = date.today()
        if not self._blocked(today):
            self._on_pick(today)
        return "break"


class RoundedField(tk.Frame):
    """A rounded text box.

    * choices: it becomes a searchable dropdown. Type to narrow the list down,
      use Up/Down and Enter, or click an item. With strict=True the text must
      end up matching one of the choices (see resolve()); otherwise the choices
      are only suggestions and any text is allowed.
    * calendar=(earliest, latest): it gets a date picker (either may be None).
    * secret=True: the text is hidden (passwords).
    """

    HEIGHT = 38

    def __init__(self, parent, variable, choices=None, strict=False, width=240,
                 parent_bg=CARD, on_pick=None, calendar=None, secret=False):
        super().__init__(parent, bg=parent_bg, width=width, height=self.HEIGHT)
        self._variable = variable
        self._choices = None if choices is None else list(choices)
        self._calendar = calendar
        self._strict = strict
        self._on_pick = on_pick
        self._focused = False
        self._shown = False
        self._typing = False
        self._popup = self._listbox = self._scrollbar = self._cal = None
        self._size = (0, 0)

        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._canvas.bind("<Configure>", self._redraw)

        has_arrow = self._choices is not None or self._calendar is not None
        right = 38 if has_arrow else 14
        self.widget = tk.Entry(self, textvariable=variable, relief="flat",
                               bd=0, highlightthickness=0, bg=FIELD, fg=TEXT,
                               insertbackground=TEXT, font=(FONT, 10),
                               show="\u2022" if secret else "")
        self.widget.place(x=14, y=7, relwidth=1, width=-(14 + right), height=24)
        self.widget.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.widget.bind("<FocusOut>", self._on_focus_out, add="+")

        if has_arrow:
            self._canvas.bind("<Button-1>", self._toggle)
            self.widget.bind("<Escape>", self._escape)
            # clicking anywhere else in the window closes the open list/calendar
            self.winfo_toplevel().bind("<Button-1>", self._outside_click, add="+")
        if self._choices is not None:
            self.widget.bind("<Button-1>",
                             lambda _e: self.after_idle(self._open, True),
                             add="+")
            self.widget.bind("<KeyPress>", self._key_pressed, add="+")
            variable.trace_add("write", self._text_changed)
            self.widget.bind("<Down>", self._down)
            self.widget.bind("<Up>", self._up)
            self.widget.bind("<Return>", self._enter)

    # -- public ----------------------------------------------------------------
    def set_choices(self, choices):
        self._choices = list(choices)

    def resolve(self):
        """The choice the text stands for: an exact match, or the only choice
        that contains the typed text. None when there is no clear match."""
        text = self._variable.get().strip().lower()
        if not text or not self._choices:
            return None
        for choice in self._choices:
            if choice.lower() == text:
                return choice
        hits = [c for c in self._choices if text in c.lower()]
        return hits[0] if len(hits) == 1 else None

    # -- drawing -----------------------------------------------------------------
    def _set_focus(self, value):
        self._focused = value
        self._draw()

    def _redraw(self, event):
        self._size = (event.width, event.height)
        self._draw()

    def _draw(self):
        width, height = self._size
        if not width:
            return
        self._canvas.delete("all")
        round_rect(self._canvas, 1, 1, width - 2, height - 2, 14, fill=FIELD,
                   outline=PRIMARY if self._focused else BORDER,
                   width=2 if self._focused else 1)
        if self._calendar is not None:  # small calendar icon
            x, y = width - 32, height / 2 - 8
            c = self._canvas
            c.create_rectangle(x, y + 3, x + 16, y + 16, outline=MUTED_DARK, width=2)
            c.create_rectangle(x, y + 3, x + 16, y + 7, fill=MUTED_DARK,
                               outline=MUTED_DARK)
            c.create_line(x + 4, y, x + 4, y + 5, fill=MUTED_DARK, width=2)
            c.create_line(x + 12, y, x + 12, y + 5, fill=MUTED_DARK, width=2)
        elif self._choices is not None:  # small arrow showing it is a dropdown
            x, y = width - 22, height / 2
            self._canvas.create_polygon(x - 5, y - 2, x + 5, y - 2, x, y + 4,
                                        fill=MUTED_DARK, outline=MUTED_DARK)

    # -- the dropdown list --------------------------------------------------------
    def _matches(self, show_all=False):
        text = self._variable.get().strip().lower()
        if show_all or not text or any(c.lower() == text for c in self._choices):
            return list(self._choices)
        return [c for c in self._choices if text in c.lower()]

    def _build_popup(self):
        popup = tk.Toplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)
        try:
            popup.attributes("-topmost", True)
        except tk.TclError:
            pass
        border = tk.Frame(popup, bg=BORDER)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._scrollbar = ttk.Scrollbar(inner, orient="vertical")
        box = tk.Listbox(inner, activestyle="none", exportselection=False,
                         relief="flat", bd=0, highlightthickness=0, bg=CARD,
                         fg=TEXT, selectbackground=NAV_ACTIVE,
                         selectforeground=TEXT, font=(FONT, 10),
                         yscrollcommand=self._scrollbar.set)
        self._scrollbar.configure(command=box.yview)
        box.pack(side="left", fill="both", expand=True)
        box.bind("<ButtonPress-1>", self._click_item)
        box.bind("<Motion>", self._hover)
        self._popup, self._listbox = popup, box

    def _open(self, show_all=False):
        if not self._choices:
            return
        items = self._matches(show_all)
        if not items:
            self._close()
            return
        if self._popup is None:
            self._build_popup()
        if self._cal is not None:
            self._cal.withdraw()
        box = self._listbox
        box.delete(0, "end")
        for item in items:
            box.insert("end", item)

        rows = min(len(items), 8)
        measure = tkfont.Font(family=FONT, size=10)
        digit = max(measure.measure("0"), 1)
        need = max(measure.measure(item) for item in items) + 28
        box.configure(height=rows,
                      width=max(int(need / digit) + 1,
                                int(self.winfo_width() / digit)))
        if len(items) > rows:
            self._scrollbar.pack(side="right", fill="y", before=box)
        else:
            self._scrollbar.pack_forget()

        text = self._variable.get().strip().lower()
        index = next((i for i, item in enumerate(items) if item.lower() == text),
                     0 if text and not show_all else None)
        if index is not None:
            self._highlight(index)

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        self._popup.geometry(f"+{x}+{y}")
        self._popup.deiconify()
        self._popup.lift()
        self._shown = True

    def _open_calendar(self):
        if self._popup is not None:
            self._popup.withdraw()
        if self._cal is None:
            self._cal = CalendarPopup(self, self._pick_date)
        try:
            current = parse_date(self._variable.get())
        except ClinicError:
            current = None
        low, high = self._calendar
        self._cal.show(current, low, high, self.winfo_rootx(),
                       self.winfo_rooty() + self.winfo_height() + 2)
        self._shown = True

    def _pick_date(self, day):
        self._variable.set(day.isoformat())
        self._close()
        self.widget.focus_set()
        self.widget.icursor("end")
        if self._on_pick:
            self._on_pick(day.isoformat())

    def _close(self):
        if self._popup is not None:
            self._popup.withdraw()
        if self._cal is not None:
            self._cal.withdraw()
        self._shown = False

    def _highlight(self, index):
        box = self._listbox
        box.selection_clear(0, "end")
        box.selection_set(index)
        box.activate(index)
        box.see(index)

    def _move(self, step):
        size = self._listbox.size()
        current = self._listbox.curselection()
        if current:
            index = (current[0] + step) % size
        else:
            index = 0 if step > 0 else size - 1
        self._highlight(index)

    def _pick(self, text):
        self._variable.set(text)
        self._close()
        self.widget.icursor("end")
        self.widget.focus_set()
        if self._on_pick:
            self._on_pick(text)

    def _commit(self):
        """On leaving a strict field, turn partly typed text into the one
        choice it matches (for example 'bud' becomes '1 - Buddy (Maria)')."""
        if not self._strict or not self._choices:
            return
        choice = self.resolve()
        if choice is not None:
            if choice != self._variable.get():
                self._variable.set(choice)
            if self._on_pick:
                self._on_pick(choice)

    # -- events --------------------------------------------------------------------
    def _toggle(self, _event):
        if self._shown:
            self._close()
            return
        self.widget.focus_set()
        if self._calendar is not None:
            self._open_calendar()
        elif self._choices is not None:
            self._open(show_all=True)

    def _key_pressed(self, _event):
        # Remember that the text is being edited by hand, not set by the program.
        self._typing = True
        self.after(80, self._clear_typing)

    def _clear_typing(self):
        self._typing = False

    def _text_changed(self, *_args):
        """Search as you type: refresh the list whenever the text changes."""
        if self._typing and self._choices:
            self._open()

    def _down(self, _event):
        if self._shown:
            self._move(1)
        else:
            self._open(show_all=True)
        return "break"

    def _up(self, _event):
        if self._shown:
            self._move(-1)
        return "break"

    def _enter(self, _event):
        if self._shown:
            selected = self._listbox.curselection()
            if selected:
                self._pick(self._listbox.get(selected[0]))
                return "break"
            self._close()
        self._commit()
        return "break"

    def _escape(self, _event):
        if self._shown:
            self._close()
            return "break"

    def _click_item(self, event):
        index = self._listbox.nearest(event.y)
        self._pick(self._listbox.get(index))
        return "break"  # stops Tk from moving the keyboard focus to the list

    def _hover(self, event):
        self._highlight(self._listbox.nearest(event.y))

    def _outside_click(self, event):
        if not self._shown:
            return
        clicked = str(event.widget)
        inside = [str(self.widget), str(self._canvas)]
        inside += [str(w) for w in (self._popup, self._cal) if w is not None]
        if clicked in inside[:2] or any(clicked.startswith(p) for p in inside[2:]):
            return
        self._close()

    def _on_focus_out(self, _event):
        self._set_focus(False)
        if self._choices is not None or self._calendar is not None:
            self.after(120, self._finish_edit)

    def _finish_edit(self):
        try:
            try:
                focused = self.focus_get()
            except KeyError:
                focused = None
            if focused is self.widget:
                return
            self._close()
            self._commit()
        except tk.TclError:
            pass  # the field was closed or destroyed in the meantime


class BarChart(tk.Canvas):
    """A simple bar chart. set_data([(label, value, highlighted), ...])."""

    def __init__(self, parent, bg=CARD):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=180)
        self._chart_data = []
        self.bind("<Configure>", lambda _e: self._draw())

    def set_data(self, data):
        self._chart_data = list(data)
        self._draw()

    def _draw(self):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 60 or height < 80 or not self._chart_data:
            return
        self.delete("all")
        left, right, top, bottom = 8, 8, 24, 28
        slot = (width - left - right) / len(self._chart_data)
        bar = min(slot * 0.62, 38)
        peak = max(1, max(value for _label, value, _flag in self._chart_data))
        base = height - bottom
        self.create_line(left, base, width - right, base, fill=BORDER)
        for i, (label, value, current) in enumerate(self._chart_data):
            cx = left + slot * (i + 0.5)
            bar_h = (base - top) * value / peak
            color = PRIMARY if current else NAV_ACTIVE
            if value > 0:
                round_rect(self, cx - bar / 2, base - bar_h, cx + bar / 2, base,
                           8, fill=color, outline=color)
            self.create_text(cx, base - bar_h - 9, text=str(value), fill=TEXT,
                             font=(FONT, 9, "bold"))
            self.create_text(cx, base + 14, text=label,
                             fill=MUTED_DARK if current else MUTED,
                             font=(FONT, 8))


# --------------------------------------------------------------------------
# Layout helpers
# --------------------------------------------------------------------------
def card_title(parent, text, hint=None, bg=CARD):
    tk.Label(parent, text=text, bg=bg, fg=TEXT,
             font=(FONT, 13, "bold")).pack(anchor="w")
    if hint:
        tk.Label(parent, text=hint, bg=bg, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w")
    tk.Frame(parent, bg=bg, height=10).pack()


def add_field(parent, label, choices=None, strict=False, width=220, pack=True,
              on_pick=None, calendar=None, secret=False):
    """Label above a rounded field. Returns (variable, field, container).
    Pass choices for a searchable dropdown, calendar=(min, max) for a date
    picker, secret=True for a password box."""
    box = tk.Frame(parent, bg=CARD)
    tk.Label(box, text=label, bg=CARD, fg=MUTED,
             font=(FONT, 9)).pack(anchor="w", pady=(0, 3))
    var = tk.StringVar()
    field = RoundedField(box, var, choices=choices, strict=strict, width=width,
                         on_pick=on_pick, calendar=calendar, secret=secret)
    field.pack(fill="x")
    if pack:
        box.pack(fill="x", pady=(0, 10))
    return var, field, box


def autohide(bar):
    """Scrollbar callback that hides the bar when everything already fits."""
    def update(first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            bar.grid_remove()
        else:
            bar.grid()
        bar.set(first, last)
    return update


def fit_columns(tree):
    """Make every column as wide as its heading and data need, and share any
    spare room between the columns. If it cannot all fit, a scrollbar appears."""
    spec = getattr(tree, "_spec", None)
    if not spec:
        return
    body = tkfont.Font(family=FONT, size=10)
    head = tkfont.Font(family=FONT, size=10, weight="bold")
    items = tree.get_children()
    wanted = []
    for key, heading, _base in spec:
        width = head.measure(heading) + 24
        for item in items:
            width = max(width, body.measure(str(tree.set(item, key))) + 16)
        wanted.append(max(width, 36))
    total = sum(wanted)
    extra = max(0, (tree.winfo_width() or 0) - total)
    for (key, _heading, _base), width in zip(spec, wanted):
        tree.column(key, width=int(width + extra * width / total),
                    stretch=False)


def make_table(parent, columns, height=6):
    """columns: list of (key, heading, width). Returns (frame, tree)."""
    frame = tk.Frame(parent, bg=CARD)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns],
                        show="headings", height=height, selectmode="browse")
    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, minwidth=30, anchor="w", stretch=False)
    vbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=autohide(vbar), xscrollcommand=autohide(hbar))
    tree.grid(row=0, column=0, sticky="nsew")
    vbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
    hbar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
    tree._spec = columns
    tree.bind("<Configure>", lambda _event: fit_columns(tree))
    tree.tag_configure("odd", background=BG)
    tree.tag_configure("even", background=CARD)
    tree.tag_configure("completed", foreground="#2F8F5B")
    tree.tag_configure("cancelled", foreground="#B0A09A")
    tree.tag_configure("paid", foreground="#2F8F5B")
    tree.tag_configure("void", foreground="#B0A09A")
    return frame, tree


def fill_tree(tree, rows, keys, tag_key=None):
    """keys may be column names or functions that take the row."""
    tree.delete(*tree.get_children())
    for index, row in enumerate(rows):
        values = []
        for key in keys:
            value = key(row) if callable(key) else row[key]
            values.append("" if value is None else value)
        iid = str(row["id"]) if "id" in row.keys() else None
        tags = ["odd" if index % 2 else "even"]
        if tag_key:
            tags.append(row[tag_key])
        tree.insert("", "end", iid=iid, values=values, tags=tuple(tags))
    fit_columns(tree)


def age_text(birth_date):
    """'2020-03-14' -> '6y 7m'. Returns '' when the date is missing/invalid."""
    if not birth_date:
        return ""
    try:
        born = datetime.strptime(birth_date, DATE_FMT).date()
    except ValueError:
        return ""
    today = date.today()
    months = ((today.year - born.year) * 12 + today.month - born.month
              - (1 if today.day < born.day else 0))
    years, months = divmod(max(months, 0), 12)
    return f"{years}y {months}m" if years else f"{months}m"


def choice_id(field, label):
    """The id at the start of the choice a dropdown field points to,
    e.g. '12 - Buddy (Maria Santos)' gives 12."""
    choice = field.resolve()
    if choice is None:
        raise ClinicError(f"Please choose a {label} from the list.")
    return int(choice.split(" - ", 1)[0])


def parse_weight(text):
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ClinicError(f"Invalid weight '{text}'. Enter a number in kg.")

# --------------------------------------------------------------------------
# Pop-up dialogs
# --------------------------------------------------------------------------
def center_over(window, parent):
    """Place a dialog in the middle of the main window."""
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
    y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
    window.geometry(f"+{x}+{y}")


def make_modal(window, parent):
    """Show a dialog on top of the main window and block the window behind it."""
    window.transient(parent)
    center_over(window, parent)
    window.deiconify()
    try:
        window.wait_visibility()
        window.grab_set()
    except tk.TclError:
        pass  # some window managers refuse the grab; the dialog still works
    window.focus_set()


class FormDialog(tk.Toplevel):
    """A small rounded pop-up form.

    fields: a list of dicts {"key", "label", "choices", "strict", "calendar",
    "secret", "value"}, or {"heading": "Section title"}.
    on_submit(dialog) saves the data; it may raise ClinicError (the dialog then
    stays open and shows the message) or return a message for the status bar.
    """

    def __init__(self, app, title, fields, on_submit, submit_text="Save",
                 message="Saved.", hint=None, width=300):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self._on_submit = on_submit
        self._message = message
        self.vars, self.fields = {}, {}

        card = Card(self, parent_bg=BG, pad=20)
        card.pack(padx=18, pady=18)
        tk.Label(card.body, text=title, bg=CARD, fg=TEXT,
                 font=(FONT, 14, "bold")).pack(anchor="w")
        if hint:
            tk.Label(card.body, text=hint, bg=CARD, fg=MUTED, font=(FONT, 9),
                     justify="left", wraplength=width).pack(anchor="w", pady=(2, 0))
        tk.Frame(card.body, bg=CARD, height=10).pack()
        for spec in fields:
            if "heading" in spec:
                tk.Label(card.body, text=spec["heading"], bg=CARD, fg=PRIMARY_H,
                         font=(FONT, 10, "bold")).pack(anchor="w", pady=(4, 6))
                continue
            var, field, _box = add_field(
                card.body, spec["label"], choices=spec.get("choices"),
                strict=spec.get("strict", False), width=width,
                calendar=spec.get("calendar"), secret=spec.get("secret", False))
            var.set(spec.get("value", ""))
            self.vars[spec["key"]] = var
            self.fields[spec["key"]] = field
        buttons = tk.Frame(card.body, bg=CARD)
        buttons.pack(fill="x", pady=(8, 0))
        PillButton(buttons, submit_text, self._save).pack(side="right")
        PillButton(buttons, "Cancel", self.destroy, kind="ghost").pack(
            side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        make_modal(self, app)

    # helpers for on_submit callbacks
    def get(self, key):
        return self.vars[key].get().strip()

    def choice_text(self, key, label):
        """The list item a dropdown field points to (error if unclear)."""
        choice = self.fields[key].resolve()
        if choice is None:
            raise ClinicError(f"Please choose {label} from the list.")
        return choice

    def choice_id(self, key, label):
        return choice_id(self.fields[key], label)

    def _save(self):
        try:
            message = self._on_submit(self)
        except ClinicError as err:
            messagebox.showerror("Cannot save", str(err), parent=self)
            return
        self.app.status.set(message or self._message)
        self.destroy()
        self.app.refresh_all()


class ScheduleDialog(tk.Toplevel):
    """Edit a veterinarian's weekly working hours and days off."""

    def __init__(self, app, vet_id):
        super().__init__(app)
        self.withdraw()
        self.app, self.clinic, self.vet_id = app, app.clinic, vet_id
        vet = self.clinic.get_vet(vet_id)
        self.title(f"Working hours: {vet['name']}")
        self.configure(bg=BG)
        self.resizable(False, False)

        card = Card(self, parent_bg=BG, pad=20)
        card.pack(padx=18, pady=18)
        tk.Label(card.body, text=f"Working hours: {vet['name']}", bg=CARD,
                 fg=TEXT, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(card.body, text="Appointments can only be booked inside these "
                 "hours and never on days off.", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w", pady=(2, 10))
        body = tk.Frame(card.body, bg=CARD)
        body.pack()

        left = tk.Frame(body, bg=CARD)
        left.pack(side="left", fill="y", padx=(0, 28))
        tk.Label(left, text="Weekly hours", bg=CARD, fg=PRIMARY_H,
                 font=(FONT, 10, "bold")).pack(anchor="w", pady=(0, 6))
        schedule = {r["weekday"]: r for r in self.clinic.get_schedule(vet_id)}
        self.rows = []
        for weekday, name in enumerate(WEEKDAYS):
            row = tk.Frame(left, bg=CARD)
            row.pack(fill="x", pady=3)
            sched = schedule.get(weekday)
            tk.Label(row, text=name, width=10, anchor="w", bg=CARD, fg=TEXT,
                     font=(FONT, 10)).pack(side="left")
            toggle = ToggleButton(row, value=bool(sched["working"]) if sched else True)
            toggle.pack(side="left", padx=(0, 10))
            start, end = tk.StringVar(), tk.StringVar()
            start.set(sched["start_time"] if sched else DEFAULT_START)
            end.set(sched["end_time"] if sched else DEFAULT_END)
            start_field = RoundedField(row, start, choices=SCHEDULE_TIMES,
                                       strict=True, width=100)
            start_field.pack(side="left")
            tk.Label(row, text="to", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(
                side="left", padx=6)
            end_field = RoundedField(row, end, choices=SCHEDULE_TIMES,
                                     strict=True, width=100)
            end_field.pack(side="left")
            self.rows.append((weekday, toggle, start_field, end_field))
        foot = tk.Frame(left, bg=CARD)
        foot.pack(fill="x", pady=(12, 0))
        self.note = tk.StringVar()
        tk.Label(foot, textvariable=self.note, bg=CARD, fg=OK_TEXT,
                 font=(FONT, 9)).pack(side="left")
        PillButton(foot, "Save weekly hours", self._save_hours).pack(side="right")

        right = tk.Frame(body, bg=CARD)
        right.pack(side="left", fill="both")
        tk.Label(right, text="Days off and leave", bg=CARD, fg=PRIMARY_H,
                 font=(FONT, 10, "bold")).pack(anchor="w", pady=(0, 6))
        frame, self.tree = make_table(right, [
            ("start_date", "From", 95), ("end_date", "To", 95),
            ("note", "Note", 140)], height=5)
        frame.pack(fill="x")
        PillButton(right, "Remove selected", self._remove_off, kind="danger",
                   small=True).pack(anchor="e", pady=(8, 12))
        self.off_from, _f, _b = add_field(right, "From (first day off)",
                                          width=310, calendar=(None, None))
        self.off_to, _f, _b = add_field(right, "To (blank = one day)", width=310,
                                        calendar=(None, None))
        self.off_note, _f, _b = add_field(right, "Note (optional)", width=310)
        PillButton(right, "Add day off", self._add_off, kind="mint").pack(anchor="e")

        PillButton(card.body, "Close", self.destroy, kind="ghost").pack(
            anchor="e", pady=(14, 0))
        self.bind("<Escape>", lambda _e: self.destroy())
        self._refresh_days_off()
        make_modal(self, app)

    def _refresh_days_off(self):
        fill_tree(self.tree, self.clinic.list_days_off(self.vet_id),
                  ["start_date", "end_date", "note"])

    def _save_hours(self):
        rows = []
        try:
            for weekday, toggle, start_field, end_field in self.rows:
                start, end = start_field.resolve(), end_field.resolve()
                if toggle.get() and (start is None or end is None):
                    raise ClinicError(
                        f"{WEEKDAYS[weekday]}: choose a start and an end time.")
                rows.append((weekday, toggle.get(), start or DEFAULT_START,
                             end or DEFAULT_END))
            self.clinic.set_schedule(self.vet_id, rows)
        except ClinicError as err:
            messagebox.showerror("Cannot save", str(err), parent=self)
            return
        self.note.set("Weekly hours saved.")
        self.app.refresh_all()

    def _add_off(self):
        try:
            self.clinic.add_day_off(self.vet_id, self.off_from.get(),
                                    self.off_to.get(), self.off_note.get())
        except ClinicError as err:
            messagebox.showerror("Cannot add", str(err), parent=self)
            return
        for var in (self.off_from, self.off_to, self.off_note):
            var.set("")
        self._refresh_days_off()
        self.app.refresh_all()

    def _remove_off(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select a day off", "Select a row in the table "
                                "first.", parent=self)
            return
        self.clinic.delete_day_off(int(selected[0]))
        self._refresh_days_off()
        self.app.refresh_all()

# --------------------------------------------------------------------------
# Permissions: what each role may do
# --------------------------------------------------------------------------
PERMISSIONS = {
    "patients.edit": ("admin", "receptionist"),
    "patients.delete": ("admin",),
    "vets.manage": ("admin",),
    "appointments.book": ("admin", "receptionist"),
    "appointments.complete": ("admin", "receptionist", "vet"),
    "appointments.delete": ("admin",),
    "records.edit": ("admin", "vet"),
    "records.delete": ("admin",),
    "billing.manage": ("admin", "receptionist"),
    "reports.view": ("admin", "receptionist"),
    "admin.manage": ("admin",),
}
ROLE_BY_LABEL = {label: role for role, label in ROLE_LABELS.items()}


def selected_id(page, tree, what):
    """The id of the highlighted table row, or None (with a friendly message)."""
    selected = tree.selection()
    if not selected:
        messagebox.showinfo(f"Select {what}",
                            f"Select {what} in the table first.", parent=page)
        return None
    return int(selected[0])


def ask_yes(page, title, text):
    return messagebox.askyesno(title, text, parent=page)


def offer_open(page, path):
    if messagebox.askyesno("Saved", f"Saved to:\n{path}\n\nOpen it now?",
                           parent=page):
        if not open_file(path):
            messagebox.showinfo("Open file", "Could not open the file "
                                "automatically. You can find it at:\n" + path,
                                parent=page)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
class BasePage(tk.Frame):
    title = ""
    subtitle = ""
    roles = ROLES

    def __init__(self, app, parent):
        super().__init__(parent, bg=BG)
        self.app = app
        self.clinic = app.clinic
        self.build()

    def side_layout(self, form_title, hint=None, with_form=True):
        """Form card on the left (optional), content card on the right."""
        form = None
        if with_form:
            form = Card(self)
            form.pack(side="left", fill="y", padx=(0, 16))
            card_title(form.body, form_title, hint)
        right = Card(self)
        right.pack(side="left", fill="both", expand=True)
        return form, right

    def preselect_patient(self, patient_id):
        """Called when another screen sends the user here for one patient."""

    def build(self):
        raise NotImplementedError

    def refresh(self):
        raise NotImplementedError


class StatCard(Card):
    """A pastel summary tile."""

    def __init__(self, parent, title, fill, parent_bg=BG, compact=False):
        super().__init__(parent, fill=fill, border=fill, radius=22,
                         pad=14 if compact else 18, parent_bg=parent_bg)
        self.value = tk.StringVar(value="0")
        tk.Label(self.body, textvariable=self.value, bg=fill, fg=TEXT,
                 font=(FONT, 20 if compact else 26, "bold")).pack(anchor="w")
        tk.Label(self.body, text=title, bg=fill, fg=MUTED_DARK,
                 font=(FONT, 10)).pack(anchor="w")


class DashboardPage(BasePage):
    title = "Dashboard"
    subtitle = "Today at a glance"
    KEYS = ["time", "patient", "owner", "vet", "reason", "status"]

    def build(self):
        banner = Card(self, fill=PEACH, border=PEACH, radius=26, pad=20)
        banner.pack(fill="x")
        paw = tk.Canvas(banner.body, width=64, height=64, bg=PEACH,
                        highlightthickness=0, bd=0)
        paw.pack(side="right", padx=(10, 4))
        draw_paw(paw, 0, 0, 64, "#F8BE98")
        tk.Label(banner.body, text=f"Welcome to {APP_NAME}", bg=PEACH, fg=TEXT,
                 font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(banner.body, text=APP_SUBTITLE, bg=PEACH, fg=MUTED_DARK,
                 font=(FONT, 10)).pack(anchor="w", pady=(2, 0))

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=14)
        self.cards = {}
        spec = [("patients", "Registered patients", SKY),
                ("today", "Appointments today", LAVENDER),
                ("vets", "Veterinarians", MINT_BG),
                ("balance", "Outstanding balance", PINK)]
        for col, (key, title, color) in enumerate(spec):
            card = StatCard(row, title, color)
            card.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 14, 0))
            row.columnconfigure(col, weight=1, uniform="stat")
            self.cards[key] = card

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="both", expand=True)
        today_card = Card(bottom)
        today_card.pack(side="left", fill="both", expand=True)
        card_title(today_card.body, "Today's appointments")
        frame, self.tree = make_table(today_card.body, [
            ("time", "Time", 60), ("patient", "Patient", 100),
            ("owner", "Owner", 130), ("vet", "Veterinarian", 130),
            ("reason", "Reason", 150), ("status", "Status", 80)])
        frame.pack(fill="both", expand=True)
        self.empty_note = tk.Label(today_card.body, text="", bg=CARD, fg=MUTED,
                                   font=(FONT, 10))
        self.empty_note.pack(anchor="w", pady=(6, 0))

        chart_card = Card(bottom)
        chart_card.pack(side="left", fill="y", padx=(16, 0))
        card_title(chart_card.body, "Appointments per week",
                   "Week starting on Monday, cancelled not counted")
        self.chart = BarChart(chart_card.body)
        self.chart.configure(width=330)
        self.chart.pack(fill="both", expand=True)

    def refresh(self):
        stats = self.clinic.stats()
        self.cards["patients"].value.set(str(stats["patients"]))
        self.cards["today"].value.set(str(stats["today"]))
        self.cards["vets"].value.set(str(stats["vets"]))
        self.cards["balance"].value.set(money(stats["outstanding_cents"]))
        rows = self.clinic.todays_appointments()
        fill_tree(self.tree, rows, self.KEYS, tag_key="status")
        self.empty_note.configure(
            text="" if rows else "No appointments today.")
        this_monday = date.today() - timedelta(days=date.today().weekday())
        self.chart.set_data([(f"{d:%b} {d.day}", n, d == this_monday)
                             for d, n in self.clinic.weekly_counts()])


class PatientsPage(BasePage):
    title = "Patients"
    subtitle = "Register a pet together with its owner's details"
    SORTS = ["ID", "A - Z", "Z - A"]
    KEYS = ["id", "name", "species", "breed",
            lambda row: age_text(row["birth_date"]), "weight_kg",
            "owner_name", "owner_phone", "owner_email"]

    def build(self):
        if self.app.can("patients.edit"):
            self._build_form()
        table_card = Card(self)
        table_card.pack(fill="both", expand=True)
        bar = tk.Frame(table_card.body, bg=CARD)
        bar.pack(fill="x", pady=(0, 10))
        tk.Label(bar, text="All patients", bg=CARD, fg=TEXT,
                 font=(FONT, 13, "bold")).pack(side="left")
        self.search = tk.StringVar()
        self.sort = tk.StringVar(value=self.SORTS[0])
        RoundedField(bar, self.search, width=230).pack(side="right")
        tk.Label(bar, text="Search", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="right", padx=8)
        RoundedField(bar, self.sort, choices=self.SORTS, strict=True,
                     width=130, on_pick=lambda _t: self.refresh_list()).pack(
                         side="right", padx=(0, 16))
        tk.Label(bar, text="Sort by", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="right", padx=8)
        self.search.trace_add("write", lambda *_: self.refresh_list())
        frame, self.tree = make_table(table_card.body, [
            ("id", "ID", 40), ("name", "Patient", 100),
            ("species", "Species", 75), ("breed", "Breed", 120),
            ("age", "Age", 60), ("weight_kg", "kg", 50),
            ("owner_name", "Owner", 140), ("owner_phone", "Phone", 120),
            ("owner_email", "Email", 170)])
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_profile())

        buttons = tk.Frame(table_card.body, bg=CARD)
        buttons.pack(fill="x", pady=(10, 0))
        PillButton(buttons, "Open profile", self.open_profile).pack(side="left")
        if self.app.can("patients.edit"):
            PillButton(buttons, "Edit patient", self.edit, kind="ghost").pack(
                side="left", padx=8)
        if self.app.can("patients.delete"):
            PillButton(buttons, "Delete", self.delete, kind="danger").pack(
                side="left")
        tk.Label(buttons, text="Tip: double-click a patient to open the profile.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="right")

    def _build_form(self):
        form = Card(self)
        form.pack(fill="x", pady=(0, 14))
        card_title(form.body, "Register patient",
                   "The owner's name, phone and email are saved with the patient.")
        grid = tk.Frame(form.body, bg=CARD)
        grid.pack(fill="x")
        for col in range(5):
            grid.columnconfigure(col, weight=1, uniform="pf")

        def put(row, col, label, **kw):
            var, field, box = add_field(grid, label, pack=False, width=120, **kw)
            box.grid(row=row, column=col, sticky="we", pady=(0, 8),
                     padx=(0 if col == 0 else 10, 0))
            return var, field

        self.name, _ = put(0, 0, "Patient name")
        self.species, _ = put(0, 1, "Species", choices=SPECIES)
        self.breed, _ = put(0, 2, "Breed (optional)")
        self.born, _ = put(0, 3, "Born (type or pick)",
                           calendar=(None, date.today()))
        self.weight, _ = put(0, 4, "Weight in kg (optional)")
        self.owner, self.owner_box = put(1, 0, "Owner name", choices=[],
                                         on_pick=self._owner_chosen)
        self.phone, _ = put(1, 1, "Owner phone")
        self.email, _ = put(1, 2, "Owner email (optional)")
        self.owner_box.widget.bind("<FocusOut>", self._owner_left, add="+")
        PillButton(grid, "Register patient", self.add).grid(
            row=1, column=4, sticky="se", pady=(0, 8))

    def _owner_chosen(self, _text=None):
        """Fill phone and email when an existing owner is picked."""
        contact = self.clinic.owner_contact(self.owner.get())
        if contact:
            self.phone.set(contact["owner_phone"] or "")
            self.email.set(contact["owner_email"] or "")

    def _owner_left(self, _event=None):
        if not self.phone.get().strip():
            self._owner_chosen()

    def add(self):
        def action():
            self.clinic.add_patient(
                self.name.get(), self.species.get(), self.owner.get(),
                self.phone.get(), breed=self.breed.get(),
                birth_date=self.born.get(),
                weight_kg=parse_weight(self.weight.get()),
                owner_email=self.email.get())
            for var in (self.name, self.breed, self.born, self.weight,
                        self.owner, self.phone, self.email):
                var.set("")
        self.app.commit(action, "Patient registered.")

    def open_profile(self):
        patient_id = selected_id(self, self.tree, "a patient")
        if patient_id is not None:
            ProfileDialog(self.app, patient_id)

    def edit(self):
        patient_id = selected_id(self, self.tree, "a patient")
        if patient_id is not None:
            self.edit_patient(patient_id)

    def edit_patient(self, patient_id):
        patient = self.clinic.get_patient(patient_id)
        fields = [
            {"key": "name", "label": "Patient name", "value": patient["name"]},
            {"key": "species", "label": "Species", "choices": SPECIES,
             "value": patient["species"]},
            {"key": "breed", "label": "Breed", "value": patient["breed"] or ""},
            {"key": "born", "label": "Born (type or pick)",
             "calendar": (None, date.today()),
             "value": patient["birth_date"] or ""},
            {"key": "weight", "label": "Weight in kg",
             "value": "" if patient["weight_kg"] is None
             else str(patient["weight_kg"])},
            {"heading": "Owner"},
            {"key": "owner", "label": "Owner name", "choices":
             self.clinic.owner_names(), "value": patient["owner_name"]},
            {"key": "phone", "label": "Owner phone",
             "value": patient["owner_phone"]},
            {"key": "email", "label": "Owner email",
             "value": patient["owner_email"] or ""},
        ]

        def submit(dlg):
            self.clinic.update_patient(
                patient_id, dlg.get("name"), dlg.get("species"), dlg.get("owner"),
                dlg.get("phone"), breed=dlg.get("breed"),
                birth_date=dlg.get("born"),
                weight_kg=parse_weight(dlg.get("weight")),
                owner_email=dlg.get("email"))
        FormDialog(self.app, f"Edit {patient['name']}", fields, submit,
                   message="Patient updated.")

    def delete(self):
        patient_id = selected_id(self, self.tree, "a patient")
        if patient_id is None:
            return
        name = self.clinic.get_patient(patient_id)["name"]
        if ask_yes(self, "Delete patient",
                   f"Delete {name}? This cannot be undone."):
            self.app.commit(lambda: self.clinic.delete_patient(patient_id),
                            f"{name} was deleted.")

    def refresh_list(self):
        rows = self.clinic.search_patients(self.search.get())
        mode = self.sort.get()
        if mode == "A - Z":
            rows = sorted(rows, key=lambda r: r["name"].lower())
        elif mode == "Z - A":
            rows = sorted(rows, key=lambda r: r["name"].lower(), reverse=True)
        fill_tree(self.tree, rows, self.KEYS)

    def refresh(self):
        if self.app.can("patients.edit"):
            self.owner_box.set_choices(self.clinic.owner_names())
        self.refresh_list()


class VetsPage(BasePage):
    title = "Veterinarians"
    subtitle = "The doctors who attend to your patients"
    KEYS = ["id", "name", "specialty"]

    def build(self):
        manage = self.app.can("vets.manage")
        form, right = self.side_layout("Add veterinarian", with_form=manage)
        if manage:
            self.name, _, _ = add_field(form.body, "Name")
            self.specialty, _, _ = add_field(form.body, "Specialty (optional)")
            PillButton(form.body, "Add veterinarian", self.add).pack(anchor="e")
        card_title(right.body, "Veterinarians")
        frame, self.tree = make_table(right.body, [
            ("id", "ID", 50), ("name", "Name", 240),
            ("specialty", "Specialty", 240)])
        frame.pack(fill="both", expand=True)
        if manage:
            buttons = tk.Frame(right.body, bg=CARD)
            buttons.pack(fill="x", pady=(10, 0))
            PillButton(buttons, "Working hours", self.schedule).pack(side="left")
            PillButton(buttons, "Edit", self.edit, kind="ghost").pack(
                side="left", padx=8)
            PillButton(buttons, "Delete", self.delete, kind="danger").pack(
                side="left")

    def add(self):
        def action():
            self.clinic.add_vet(self.name.get(), self.specialty.get())
            self.name.set("")
            self.specialty.set("")
        self.app.commit(action, "Veterinarian added (Monday to Saturday, "
                        "08:00 to 18:00 by default).")

    def schedule(self):
        vet_id = selected_id(self, self.tree, "a veterinarian")
        if vet_id is not None:
            ScheduleDialog(self.app, vet_id)

    def edit(self):
        vet_id = selected_id(self, self.tree, "a veterinarian")
        if vet_id is None:
            return
        vet = self.clinic.get_vet(vet_id)
        fields = [{"key": "name", "label": "Name", "value": vet["name"]},
                  {"key": "specialty", "label": "Specialty",
                   "value": vet["specialty"] or ""}]

        def submit(dlg):
            self.clinic.update_vet(vet_id, dlg.get("name"), dlg.get("specialty"))
        FormDialog(self.app, f"Edit {vet['name']}", fields, submit,
                   message="Veterinarian updated.")

    def delete(self):
        vet_id = selected_id(self, self.tree, "a veterinarian")
        if vet_id is None:
            return
        name = self.clinic.get_vet(vet_id)["name"]
        if ask_yes(self, "Delete veterinarian",
                   f"Delete {name}? This cannot be undone."):
            self.app.commit(lambda: self.clinic.delete_vet(vet_id),
                            f"{name} was deleted.")

    def refresh(self):
        fill_tree(self.tree, self.clinic.list_vets(), self.KEYS)


class AppointmentsPage(BasePage):
    title = "Appointments"
    subtitle = "Book, reschedule, complete or cancel visits"
    FILTERS = ["All", "ID", "Date", "Status", "Patient", "Veterinarian"]
    STATUSES = ["Scheduled", "Completed", "Cancelled"]
    SORTS = ["ID", "Date (Soonest)", "Date (Latest)", "A - Z", "Z - A", "Status"]
    KEYS = ["id", "scheduled_at", "patient", "owner", "vet", "reason", "status"]

    def build(self):
        self.can_book = self.app.can("appointments.book")
        form, right = self.side_layout("Book appointment",
                                       with_form=self.can_book)
        if self.can_book:
            self.patient, self.patient_box, _ = add_field(
                form.body, "Patient", choices=[], strict=True)
            self.vet, self.vet_box, _ = add_field(
                form.body, "Veterinarian", choices=[], strict=True)
            self.day, _, _ = add_field(form.body, "Date (type or pick)",
                                       calendar=(date.today(), None))
            self.time, self.time_box, _ = add_field(
                form.body, "Time", choices=TIME_SLOTS, strict=True)
            self.slot_note = tk.StringVar()
            tk.Label(form.body, textvariable=self.slot_note, bg=CARD, fg=MUTED,
                     font=(FONT, 9), wraplength=220, justify="left").pack(
                         anchor="w", pady=(0, 10))
            self.reason, _, _ = add_field(form.body, "Reason for visit")
            self.day.set(date.today().isoformat())
            PillButton(form.body, "Book appointment", self.book).pack(anchor="e")
            self.vet.trace_add("write", lambda *_: self.refresh_slots())
            self.day.trace_add("write", lambda *_: self.refresh_slots())

        bar = tk.Frame(right.body, bg=CARD)
        bar.pack(fill="x", pady=(0, 10))
        # sort control on the right
        self.sort = tk.StringVar(value=self.SORTS[1])
        RoundedField(bar, self.sort, choices=self.SORTS, strict=True, width=150,
                     on_pick=lambda _t: self.refresh_list()).pack(side="right")
        tk.Label(bar, text="Sort by", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="right", padx=8)
        # filter control on the left: pick what to filter by, then type or pick
        tk.Label(bar, text="Filter by", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="left")
        self.filter_by = tk.StringVar(value=self.FILTERS[0])
        RoundedField(bar, self.filter_by, choices=self.FILTERS, strict=True,
                     width=120, on_pick=self._filter_mode_changed).pack(
                         side="left", padx=8)
        holder = tk.Frame(bar, bg=CARD)
        holder.pack(side="left")
        self.filter_text = tk.StringVar()
        self.filter_status = tk.StringVar()
        self.text_field = RoundedField(holder, self.filter_text, width=140)
        self.status_field = RoundedField(
            holder, self.filter_status, choices=self.STATUSES, strict=True,
            width=140)
        for field in (self.text_field, self.status_field):
            field.grid(row=0, column=0)
            field.grid_remove()
        PillButton(bar, "Clear", self.clear_filter, kind="ghost",
                   small=True).pack(side="left", padx=8)

        frame, self.tree = make_table(right.body, [
            ("id", "ID", 40), ("scheduled_at", "When", 125),
            ("patient", "Patient", 90), ("owner", "Owner", 110),
            ("vet", "Vet", 110), ("reason", "Reason", 150),
            ("status", "Status", 85)])
        frame.pack(fill="both", expand=True)

        buttons = tk.Frame(right.body, bg=CARD)
        buttons.pack(fill="x", pady=(12, 0))
        if self.app.can("appointments.complete"):
            PillButton(buttons, "Complete visit", self.complete,
                       kind="mint").pack(side="left")
        if self.can_book:
            PillButton(buttons, "Reschedule", self.reschedule,
                       kind="ghost").pack(side="left", padx=8)
            PillButton(buttons, "Cancel appointment",
                       lambda: self.change("cancelled"), kind="danger").pack(
                           side="left")
        if self.app.can("appointments.delete"):
            PillButton(buttons, "Delete", self.delete, kind="ghost").pack(
                side="left", padx=8)

        # live filtering: the table updates as you type
        self.filter_text.trace_add("write", lambda *_: self.refresh_list())
        self.filter_status.trace_add("write", lambda *_: self.refresh_list())

    # -- booking -------------------------------------------------------------------
    def refresh_slots(self):
        """Show only the times this vet is free on the chosen day."""
        try:
            day = parse_date(self.day.get())
        except ClinicError:
            self.time_box.set_choices(TIME_SLOTS)
            self.slot_note.set("Pick a valid date.")
            return
        vet = self.vet_box.resolve()
        if vet is None:
            self.time_box.set_choices(TIME_SLOTS)
            self.slot_note.set("Choose a veterinarian to see the free times.")
            return
        slots = self.clinic.free_slots(int(vet.split(" - ", 1)[0]), day)
        self.time_box.set_choices(slots)
        if slots:
            if self.time.get() not in slots:
                self.time.set(slots[0])
            self.slot_note.set(f"{len(slots)} free time(s) on {day:%A, %d %b}.")
        else:
            self.time.set("")
            self.slot_note.set("No free times that day (day off, not working "
                               "or fully booked). Try another date.")

    def preselect_patient(self, patient_id):
        if self.can_book:
            self.patient.set(self.app.patient_text(patient_id))

    def book(self):
        def action():
            patient_id = choice_id(self.patient_box, "patient")
            vet_id = choice_id(self.vet_box, "veterinarian")
            time_text = self.time_box.resolve()
            if time_text is None:
                raise ClinicError("Please choose a time from the list.")
            when = parse_datetime(f"{self.day.get().strip()} {time_text}")
            self.clinic.book_appointment(patient_id, vet_id, when,
                                         self.reason.get())
            self.reason.set("")
        self.app.commit(action, "Appointment booked.")

    # -- actions on the selected appointment -----------------------------------------
    def change(self, status):
        appt_id = selected_id(self, self.tree, "an appointment")
        if appt_id is None:
            return
        if status == "cancelled" and not ask_yes(
                self, "Cancel appointment", "Cancel the selected appointment?"):
            return
        self.app.commit(
            lambda: self.clinic.set_appointment_status(appt_id, status),
            f"Appointment {appt_id} marked {status}.")

    def delete(self):
        appt_id = selected_id(self, self.tree, "an appointment")
        if appt_id is None:
            return
        if ask_yes(self, "Delete appointment",
                   "Delete this appointment? Its medical record and invoice "
                   "(if any) are kept."):
            self.app.commit(lambda: self.clinic.delete_appointment(appt_id),
                            f"Appointment {appt_id} deleted.")

    def reschedule(self):
        appt_id = selected_id(self, self.tree, "an appointment")
        if appt_id is None:
            return
        appt = self.clinic.get_appointment(appt_id)
        if appt["status"] != "scheduled":
            messagebox.showinfo("Reschedule", f"This appointment is already "
                                f"{appt['status']}.", parent=self)
            return
        vet_text = next((v for v in self.app.vet_choices()
                         if v.startswith(f"{appt['vet_id']} - ")), "")
        fields = [
            {"key": "vet", "label": "Veterinarian", "choices":
             self.app.vet_choices(), "strict": True, "value": vet_text},
            {"key": "date", "label": "Date (type or pick)",
             "calendar": (date.today(), None),
             "value": appt["scheduled_at"][:10]},
            {"key": "time", "label": "Time", "choices": [], "strict": True,
             "value": appt["scheduled_at"][11:16]},
            {"key": "reason", "label": "Reason for visit",
             "value": appt["reason"]},
        ]

        def submit(dlg):
            vet_id = dlg.choice_id("vet", "veterinarian")
            time_text = dlg.choice_text("time", "a time")
            when = parse_datetime(f"{dlg.get('date')} {time_text}")
            self.clinic.reschedule_appointment(appt_id, vet_id, when,
                                               dlg.get("reason"))
            return "Appointment rescheduled."
        dlg = FormDialog(self.app, f"Reschedule: {appt['patient']}", fields,
                         submit, hint=f"Currently {appt['scheduled_at']} with "
                         f"{appt['vet']}.")

        def update_slots(*_):
            vet = dlg.fields["vet"].resolve()
            try:
                day = parse_date(dlg.get("date"))
            except ClinicError:
                return
            if vet is None:
                return
            slots = self.clinic.free_slots(int(vet.split(" - ", 1)[0]), day,
                                           exclude_id=appt_id)
            dlg.fields["time"].set_choices(slots)
            if slots and dlg.get("time") not in slots:
                dlg.vars["time"].set(slots[0])
        dlg.vars["vet"].trace_add("write", update_slots)
        dlg.vars["date"].trace_add("write", update_slots)
        update_slots()

    def complete(self):
        """Finish a visit: mark it completed and save the record and invoice."""
        appt_id = selected_id(self, self.tree, "an appointment")
        if appt_id is None:
            return
        appt = self.clinic.get_appointment(appt_id)
        if appt["status"] != "scheduled":
            messagebox.showinfo("Complete visit", f"This appointment is already "
                                f"{appt['status']}.", parent=self)
            return
        can_record = self.app.can("records.edit")
        can_invoice = self.app.can("billing.manage")
        fields = []
        if can_record:
            fields += [{"heading": "Medical record"},
                       {"key": "diagnosis", "label": "Diagnosis"},
                       {"key": "treatment", "label": "Treatment"},
                       {"key": "notes", "label": "Notes"}]
        if can_invoice:
            fields += [{"heading": "Invoice"},
                       {"key": "description", "label": "Description",
                        "value": f"Consultation: {appt['reason']}"},
                       {"key": "amount", "label": f"Amount ({CURRENCY})"},
                       {"key": "method", "label": "Payment", "choices":
                        ["Not paid yet"] + PAYMENT_METHODS, "strict": True,
                        "value": "Not paid yet"}]

        def submit(dlg):
            record = invoice = None
            if can_record and (dlg.get("diagnosis") or dlg.get("treatment")
                               or dlg.get("notes")):
                record = {"diagnosis": dlg.get("diagnosis"),
                          "treatment": dlg.get("treatment"),
                          "notes": dlg.get("notes")}
            if can_invoice and dlg.get("amount"):
                method = dlg.choice_text("method", "a payment option")
                invoice = {"description": dlg.get("description"),
                           "amount_cents": parse_money_to_cents(dlg.get("amount")),
                           "method": None if method == "Not paid yet" else method}
            result = self.clinic.complete_appointment(appt_id, record, invoice)
            parts = ["Visit completed."]
            if result["record_id"]:
                parts.append("Medical record saved.")
            if result["invoice_id"]:
                parts.append("Invoice created.")
            return " ".join(parts)
        FormDialog(self.app, "Complete visit", fields, submit,
                   submit_text="Complete visit", width=320,
                   hint=f"{appt['patient']} ({appt['owner']}) with {appt['vet']}, "
                   f"{appt['scheduled_at']}. Leave a part empty to skip it.")

    # -- filtering, sorting and showing ---------------------------------------------------
    def _filter_mode_changed(self, _text=None):
        mode = self.filter_by.get()
        self.filter_text.set("")
        self.filter_status.set("")
        self.text_field.grid_remove()
        self.status_field.grid_remove()
        if mode == "Status":
            self.status_field.grid()
        elif mode in ("ID", "Date", "Patient", "Veterinarian"):
            self.text_field.grid()
        self.refresh_list()

    def clear_filter(self):
        self.filter_by.set(self.FILTERS[0])
        self._filter_mode_changed()

    def _filtered(self, rows):
        mode = self.filter_by.get()
        box = self.filter_status if mode == "Status" else self.filter_text
        want = box.get().strip().lower()
        if mode == "All" or not want:
            return list(rows)
        if mode == "ID":
            return [r for r in rows if str(r["id"]) == want]
        if mode == "Date":
            return [r for r in rows if want in r["scheduled_at"]]
        if mode == "Status":
            return [r for r in rows if r["status"].startswith(want)]
        if mode == "Patient":
            return [r for r in rows if want in r["patient"].lower()]
        if mode == "Veterinarian":
            return [r for r in rows if want in r["vet"].lower()]
        return list(rows)

    def _sorted(self, rows):
        mode = self.sort.get()
        if mode == "ID":
            return sorted(rows, key=lambda r: r["id"])
        if mode == "A - Z":
            return sorted(rows, key=lambda r: (r["patient"].lower(),
                                               r["scheduled_at"]))
        if mode == "Z - A":
            return sorted(rows, key=lambda r: r["patient"].lower(),
                          reverse=True)
        if mode == "Status":
            order = {"scheduled": 0, "completed": 1, "cancelled": 2}
            return sorted(rows, key=lambda r: (order[r["status"]],
                                               r["scheduled_at"]))
        if mode == "Date (Latest)":
            return sorted(rows, key=lambda r: r["scheduled_at"], reverse=True)
        return list(rows)  # soonest first, the order the database gives

    def refresh_list(self):
        rows = self._sorted(self._filtered(self.clinic.list_appointments()))
        fill_tree(self.tree, rows, self.KEYS, tag_key="status")

    def refresh(self):
        if self.can_book:
            self.patient_box.set_choices(self.app.patient_choices())
            self.vet_box.set_choices(self.app.vet_choices())
            self.refresh_slots()
        self.refresh_list()


class RecordsPage(BasePage):
    title = "Medical Records"
    subtitle = "Diagnoses and treatments for every patient"
    roles = ("admin", "vet")
    KEYS = ["visit_date", "vet", "diagnosis", "treatment", "notes"]

    def build(self):
        form, right = self.side_layout("Add medical record")
        self.patient, self.patient_box, _ = add_field(
            form.body, "Patient", choices=[], strict=True,
            on_pick=lambda _t: self.refresh_history())
        self.vet, self.vet_box, _ = add_field(
            form.body, "Veterinarian", choices=[], strict=True)
        self.visit, _, _ = add_field(form.body, "Visit date (blank = today)",
                                     calendar=(None, date.today()))
        self.diagnosis, _, _ = add_field(form.body, "Diagnosis")
        self.treatment, _, _ = add_field(form.body, "Treatment")
        self.notes, _, _ = add_field(form.body, "Notes")
        PillButton(form.body, "Save record", self.save).pack(anchor="e")

        self.summary = tk.StringVar(
            value="Select a patient to see their history.")
        tk.Label(right.body, textvariable=self.summary, bg=CARD, fg=TEXT,
                 font=(FONT, 13, "bold"), anchor="w").pack(fill="x",
                                                           pady=(0, 10))
        frame, self.tree = make_table(right.body, [
            ("visit_date", "Date", 95), ("vet", "Veterinarian", 125),
            ("diagnosis", "Diagnosis", 170), ("treatment", "Treatment", 170),
            ("notes", "Notes", 190)])
        frame.pack(fill="both", expand=True)
        buttons = tk.Frame(right.body, bg=CARD)
        buttons.pack(fill="x", pady=(10, 0))
        PillButton(buttons, "Edit record", self.edit, kind="ghost").pack(
            side="left")
        if self.app.can("records.delete"):
            PillButton(buttons, "Delete record", self.delete,
                       kind="danger").pack(side="left", padx=8)

    def preselect_patient(self, patient_id):
        self.patient.set(self.app.patient_text(patient_id))
        self.refresh_history()

    def save(self):
        def action():
            patient_id = choice_id(self.patient_box, "patient")
            vet_id = choice_id(self.vet_box, "veterinarian")
            visit = self.visit.get().strip()
            self.clinic.add_record(
                patient_id, vet_id, self.diagnosis.get(), self.treatment.get(),
                self.notes.get(), parse_date(visit) if visit else None)
            for var in (self.visit, self.diagnosis, self.treatment,
                        self.notes):
                var.set("")
        self.app.commit(action, "Medical record saved.")

    def edit(self):
        record_id = selected_id(self, self.tree, "a medical record")
        if record_id is None:
            return
        record = self.clinic.get_record(record_id)
        vet_text = next((v for v in self.app.vet_choices()
                         if v.startswith(f"{record['vet_id']} - ")), "")
        fields = [
            {"key": "vet", "label": "Veterinarian", "choices":
             self.app.vet_choices(), "strict": True, "value": vet_text},
            {"key": "date", "label": "Visit date (type or pick)",
             "calendar": (None, date.today()), "value": record["visit_date"]},
            {"key": "diagnosis", "label": "Diagnosis",
             "value": record["diagnosis"]},
            {"key": "treatment", "label": "Treatment",
             "value": record["treatment"] or ""},
            {"key": "notes", "label": "Notes", "value": record["notes"] or ""},
        ]

        def submit(dlg):
            self.clinic.update_record(
                record_id, dlg.choice_id("vet", "veterinarian"),
                parse_date(dlg.get("date")), dlg.get("diagnosis"),
                dlg.get("treatment"), dlg.get("notes"))
        FormDialog(self.app, "Edit medical record", fields, submit,
                   message="Medical record updated.")

    def delete(self):
        record_id = selected_id(self, self.tree, "a medical record")
        if record_id is None:
            return
        if ask_yes(self, "Delete medical record",
                   "Delete this medical record? This cannot be undone."):
            self.app.commit(lambda: self.clinic.delete_record(record_id),
                            "Medical record deleted.")

    def refresh_history(self):
        choice = self.patient_box.resolve()
        if choice is None:
            self.summary.set("Select a patient to see their history.")
            fill_tree(self.tree, [], self.KEYS)
            return
        patient, records = self.clinic.patient_history(
            int(choice.split(" - ", 1)[0]))
        self.summary.set(
            f"{patient['name']} - {patient['species']}, "
            f"{patient['breed'] or 'unknown breed'} "
            f"(owner: {patient['owner_name']})")
        fill_tree(self.tree, records, self.KEYS)

    def refresh(self):
        self.patient_box.set_choices(self.app.patient_choices())
        self.vet_box.set_choices(self.app.vet_choices())
        self.refresh_history()


class BillingPage(BasePage):
    title = "Billing"
    subtitle = "Invoices, payments and receipts"
    roles = ("admin", "receptionist")
    SHOW = ["Outstanding", "Paid", "Void", "All"]
    SORTS = ["ID", "Date (Oldest)", "Date (Newest)", "A - Z", "Z - A"]
    KEYS = ["id", "issued_on", "patient", "owner", "description", "amount",
            "status", "method"]

    def build(self):
        form, right = self.side_layout("Create invoice")
        self.patient, self.patient_box, _ = add_field(
            form.body, "Patient", choices=[], strict=True)
        self.description, _, _ = add_field(form.body, "Description")
        self.amount, _, _ = add_field(form.body, f"Amount ({CURRENCY})")
        PillButton(form.body, "Create invoice", self.create).pack(anchor="e")

        head = tk.Frame(right.body, bg=CARD)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Invoices", bg=CARD, fg=TEXT,
                 font=(FONT, 13, "bold")).pack(side="left")
        self.sort = tk.StringVar(value=self.SORTS[1])
        self.show = tk.StringVar(value=self.SHOW[0])
        RoundedField(head, self.sort, choices=self.SORTS, strict=True,
                     width=140, on_pick=lambda _t: self.refresh_list()).pack(
                         side="right")
        tk.Label(head, text="Sort by", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="right", padx=8)
        RoundedField(head, self.show, choices=self.SHOW, strict=True,
                     width=130, on_pick=lambda _t: self.refresh_list()).pack(
                         side="right", padx=(0, 16))
        tk.Label(head, text="Show", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="right", padx=8)
        frame, self.tree = make_table(right.body, [
            ("id", "ID", 40), ("issued_on", "Issued", 90),
            ("patient", "Patient", 90), ("owner", "Owner", 120),
            ("description", "Description", 200),
            ("amount", f"Amount ({CURRENCY})", 100), ("status", "Status", 70),
            ("method", "Method", 90)])
        frame.pack(fill="both", expand=True)

        footer = tk.Frame(right.body, bg=CARD)
        footer.pack(fill="x", pady=(12, 0))
        PillButton(footer, "Record payment", self.pay, kind="mint").pack(
            side="left")
        PillButton(footer, "Receipt (PDF)", self.receipt, kind="ghost").pack(
            side="left", padx=8)
        PillButton(footer, "Edit", self.edit, kind="ghost").pack(side="left")
        PillButton(footer, "Void", self.void, kind="danger").pack(
            side="left", padx=8)
        self.total = tk.StringVar()
        tk.Label(footer, textvariable=self.total, bg=CARD, fg=TEXT,
                 font=(FONT, 12, "bold")).pack(side="right")

    def preselect_patient(self, patient_id):
        self.patient.set(self.app.patient_text(patient_id))

    def create(self):
        def action():
            patient_id = choice_id(self.patient_box, "patient")
            cents = parse_money_to_cents(self.amount.get())
            self.clinic.create_invoice(patient_id, self.description.get(),
                                       cents)
            self.description.set("")
            self.amount.set("")
        self.app.commit(action, "Invoice created.")

    def pay(self):
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if invoice["voided"]:
            messagebox.showinfo("Record payment", "A void invoice cannot be paid.",
                                parent=self)
            return
        if invoice["paid"]:
            messagebox.showinfo("Record payment", "This invoice is already paid.",
                                parent=self)
            return
        fields = [{"key": "method", "label": "Payment method",
                   "choices": PAYMENT_METHODS, "strict": True, "value": "Cash"}]

        def submit(dlg):
            self.clinic.pay_invoice(invoice_id,
                                    dlg.choice_text("method", "a payment method"))
            return f"Invoice {invoice_id} marked as paid."
        FormDialog(self.app, "Record payment", fields, submit,
                   submit_text="Mark as paid",
                   hint=f"Invoice {invoice_id} for {invoice['patient']}: "
                   f"{money(invoice['amount_cents'])}")

    def receipt(self):
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if not invoice["paid"]:
            messagebox.showinfo("Receipt", "Receipts can only be made for paid "
                                "invoices. Record the payment first.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"receipt-{invoice_id:06d}.pdf")
        if not path:
            return
        try:
            write_pdf(path, receipt_lines(invoice))
        except OSError as err:
            messagebox.showerror("Receipt", f"Could not save the file:\n{err}",
                                 parent=self)
            return
        offer_open(self, path)

    def edit(self):
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if invoice["voided"] or invoice["paid"]:
            messagebox.showinfo(
                "Edit invoice", "Only unpaid invoices can be changed. "
                "Paid and void invoices are kept as they are.", parent=self)
            return
        fields = [{"key": "description", "label": "Description",
                   "value": invoice["description"]},
                  {"key": "amount", "label": f"Amount ({CURRENCY})",
                   "value": f"{invoice['amount_cents'] / 100:.2f}"}]

        def submit(dlg):
            self.clinic.update_invoice(
                invoice_id, dlg.get("description"),
                parse_money_to_cents(dlg.get("amount")))
        FormDialog(self.app, f"Edit invoice {invoice_id}", fields, submit,
                   message="Invoice updated.")

    def void(self):
        """Cancel an unpaid invoice. It stays in the list marked Void."""
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if invoice["voided"]:
            messagebox.showinfo("Void invoice", "This invoice is already void.",
                                parent=self)
            return
        if invoice["paid"]:
            messagebox.showinfo(
                "Void invoice", "Paid invoices cannot be voided because they "
                "record a payment.", parent=self)
            return
        fields = [{"key": "reason", "label": "Reason for voiding"}]

        def submit(dlg):
            self.clinic.void_invoice(invoice_id, dlg.get("reason"))
            return f"Invoice {invoice_id} voided."
        FormDialog(self.app, "Void invoice", fields, submit,
                   submit_text="Void invoice",
                   hint=f"Invoice {invoice_id} for {invoice['patient']}: "
                   f"{money(invoice['amount_cents'])}. It stays in the list "
                   "marked Void and no longer counts as money owed.")

    def _sorted(self, rows):
        mode = self.sort.get()
        if mode == "ID":
            return sorted(rows, key=lambda r: r["id"])
        if mode == "Date (Newest)":
            return sorted(rows, key=lambda r: (r["issued_on"], r["id"]),
                          reverse=True)
        if mode == "A - Z":
            return sorted(rows, key=lambda r: r["patient"].lower())
        if mode == "Z - A":
            return sorted(rows, key=lambda r: r["patient"].lower(),
                          reverse=True)
        return list(rows)  # oldest date first, the order the database gives

    def refresh_list(self):
        shown = {"Paid": "paid", "Void": "void", "All": "all"}.get(
            self.show.get(), "outstanding")
        rows = self._sorted(self.clinic.list_invoices(shown))
        fill_tree(self.tree, rows, self.KEYS, tag_key="tag")

    def refresh(self):
        self.patient_box.set_choices(self.app.patient_choices())
        self.refresh_list()
        self.total.set(
            f"Outstanding: {money(self.clinic.outstanding_total_cents())}")


class ReportsPage(BasePage):
    title = "Reports"
    subtitle = "Daily and monthly summaries you can export"
    roles = ("admin", "receptionist")

    def build(self):
        form, right = self.side_layout("Report period")
        self.kind, self.kind_box, _ = add_field(
            form.body, "Period", choices=["Daily", "Monthly"], strict=True)
        self.day, _, _ = add_field(form.body, "Date (type or pick)",
                                   calendar=(None, None))
        tk.Label(form.body, text="Monthly reports cover the whole month of "
                 "this date.", bg=CARD, fg=MUTED, font=(FONT, 9),
                 wraplength=220, justify="left").pack(anchor="w", pady=(0, 14))
        self.kind.set("Daily")
        self.day.set(date.today().isoformat())
        tk.Label(form.body, text="Export", bg=CARD, fg=PRIMARY_H,
                 font=(FONT, 10, "bold")).pack(anchor="w", pady=(0, 6))
        for text, command, kind in (
                ("Summary (PDF)", self.export_pdf, "primary"),
                ("Appointments (CSV)", self.export_appointments, "ghost"),
                ("Invoices (CSV)", self.export_invoices, "ghost"),
                ("All patients (CSV)", self.export_patients, "ghost")):
            PillButton(form.body, text, command, kind=kind).pack(
                anchor="w", pady=3)

        self.heading = tk.StringVar()
        tk.Label(right.body, textvariable=self.heading, bg=CARD, fg=TEXT,
                 font=(FONT, 13, "bold"), anchor="w").pack(fill="x",
                                                           pady=(0, 10))
        tiles = tk.Frame(right.body, bg=CARD)
        tiles.pack(fill="x")
        self.tiles = {}
        for col, (key, title, color) in enumerate([
                ("appointments", "Appointments", SKY),
                ("completed", "Completed visits", LAVENDER),
                ("collected", "Collected", MINT_BG),
                ("unpaid", "Unpaid (issued)", PINK)]):
            tile = StatCard(tiles, title, color, parent_bg=CARD, compact=True)
            tile.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 10, 0))
            tiles.columnconfigure(col, weight=1, uniform="rt")
            self.tiles[key] = tile
        tk.Label(right.body, text="By veterinarian", bg=CARD, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(anchor="w", pady=(14, 6))
        frame, self.vet_tree = make_table(right.body, [
            ("vet", "Veterinarian", 200), ("total", "Appointments", 110),
            ("completed", "Completed", 100)], height=3)
        frame.pack(fill="x")
        tk.Label(right.body, text="Appointments in this period", bg=CARD,
                 fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w",
                                                        pady=(14, 6))
        frame, self.appt_tree = make_table(right.body, [
            ("id", "ID", 40), ("scheduled_at", "When", 125),
            ("patient", "Patient", 90), ("owner", "Owner", 110),
            ("vet", "Vet", 110), ("reason", "Reason", 150),
            ("status", "Status", 85)])
        frame.pack(fill="both", expand=True)
        self.kind.trace_add("write", lambda *_: self.refresh())
        self.day.trace_add("write", lambda *_: self.refresh())

    def _period(self):
        """(start, end) for the chosen period, or None if the date is invalid."""
        try:
            day = parse_date(self.day.get())
        except ClinicError:
            return None
        kind = "Monthly" if self.kind.get().strip().lower().startswith("m") else "Daily"
        return Clinic.period_bounds(kind, day)

    def refresh(self):
        period = self._period()
        if period is None:
            self.heading.set("Pick a valid date (YYYY-MM-DD).")
            return
        start, end = period
        report = self.clinic.report_summary(start, end)
        self.heading.set(f"{start:%d %B %Y}" if start == end
                         else f"{start:%B %Y}")
        self.tiles["appointments"].value.set(str(report["appointments"]))
        self.tiles["completed"].value.set(str(report["visits"]))
        self.tiles["collected"].value.set(money(report["collected_cents"]))
        self.tiles["unpaid"].value.set(money(report["outstanding_cents"]))
        fill_tree(self.vet_tree, report["by_vet"],
                  ["vet", "total", "completed"])
        fill_tree(self.appt_tree, self.clinic.report_appointments(start, end),
                  ["id", "scheduled_at", "patient", "owner", "vet", "reason",
                   "status"], tag_key="status")

    # -- exports ---------------------------------------------------------------------------
    def _need_period(self):
        period = self._period()
        if period is None:
            messagebox.showinfo("Report", "Pick a valid date first.", parent=self)
        return period

    def _tag(self, start, end):
        return start.isoformat() if start == end else start.strftime("%Y-%m")

    def _ask(self, name, ext, kind):
        return filedialog.asksaveasfilename(
            parent=self, defaultextension=ext, initialfile=name,
            filetypes=[(kind, f"*{ext}")])

    def export_pdf(self):
        period = self._need_period()
        if period is None:
            return
        path = self._ask(f"petvault-summary-{self._tag(*period)}.pdf", ".pdf",
                         "PDF")
        if path:
            write_pdf(path, summary_lines(self.clinic.report_summary(*period)),
                      mono=True)
            offer_open(self, path)

    def export_appointments(self):
        period = self._need_period()
        if period is None:
            return
        path = self._ask(f"petvault-appointments-{self._tag(*period)}.csv",
                         ".csv", "CSV")
        if path:
            rows = self.clinic.report_appointments(*period)
            write_csv(path, ["ID", "When", "Patient", "Owner", "Veterinarian",
                             "Reason", "Status"],
                      [[r["id"], r["scheduled_at"], r["patient"], r["owner"],
                        r["vet"], r["reason"], r["status"]] for r in rows])
            offer_open(self, path)

    def export_invoices(self):
        period = self._need_period()
        if period is None:
            return
        path = self._ask(f"petvault-invoices-{self._tag(*period)}.csv", ".csv",
                         "CSV")
        if path:
            rows = self.clinic.report_invoices(*period)
            write_csv(path, ["ID", "Issued", "Patient", "Owner", "Description",
                             "Amount", "Status", "Payment method", "Paid on",
                             "Void reason"],
                      [[r["id"], r["issued_on"], r["patient"], r["owner"],
                        r["description"], r["amount"], r["status"], r["method"],
                        r["paid_on"], r["void_reason"]] for r in rows])
            offer_open(self, path)

    def export_patients(self):
        path = self._ask("petvault-patients.csv", ".csv", "CSV")
        if path:
            rows = self.clinic.search_patients("")
            write_csv(path, ["ID", "Name", "Species", "Breed", "Born",
                             "Weight (kg)", "Owner", "Owner phone",
                             "Owner email"],
                      [[r["id"], r["name"], r["species"], r["breed"] or "",
                        r["birth_date"] or "", r["weight_kg"] or "",
                        r["owner_name"], r["owner_phone"],
                        r["owner_email"] or ""] for r in rows])
            offer_open(self, path)


class AdminPage(BasePage):
    title = "Admin"
    subtitle = "Staff accounts and database backups"
    roles = ("admin",)
    KEYS = ["id", "username", "full_name", lambda r: ROLE_LABELS[r["role"]]]

    def build(self):
        form = Card(self)
        form.pack(side="left", fill="y", padx=(0, 16))
        card_title(form.body, "Add user", "Staff sign in with these details.")
        self.full_name, _, _ = add_field(form.body, "Full name")
        self.username, _, _ = add_field(form.body, "Username")
        self.role, _, _ = add_field(form.body, "Role",
                                    choices=list(ROLE_BY_LABEL), strict=True)
        self.password, _, _ = add_field(form.body, "Password (6+ characters)",
                                        secret=True)
        self.confirm, _, _ = add_field(form.body, "Confirm password", secret=True)
        PillButton(form.body, "Add user", self.add).pack(anchor="e")

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        users = Card(right)
        users.pack(fill="both", expand=True)
        card_title(users.body, "Users")
        frame, self.tree = make_table(users.body, [
            ("id", "ID", 40), ("username", "Username", 140),
            ("full_name", "Name", 200), ("role", "Role", 130)])
        frame.pack(fill="both", expand=True)
        buttons = tk.Frame(users.body, bg=CARD)
        buttons.pack(fill="x", pady=(10, 0))
        PillButton(buttons, "Reset password", self.reset_password,
                   kind="ghost").pack(side="left")
        PillButton(buttons, "Delete user", self.delete, kind="danger").pack(
            side="left", padx=8)

        backup = Card(right)
        backup.pack(fill="x", pady=(16, 0))
        card_title(backup.body, "Database backup",
                   "A copy is also saved automatically every time the app is "
                   "closed (the last 10 are kept).")
        self.backup_note = tk.StringVar()
        tk.Label(backup.body, textvariable=self.backup_note, bg=CARD, fg=MUTED_DARK,
                 font=(FONT, 10), justify="left", wraplength=560).pack(
                     anchor="w", pady=(0, 10))
        row = tk.Frame(backup.body, bg=CARD)
        row.pack(fill="x")
        PillButton(row, "Back up now", self.backup_now).pack(side="left")
        PillButton(row, "Open backup folder", self.open_folder,
                   kind="ghost").pack(side="left", padx=8)

    def add(self):
        def action():
            if self.password.get() != self.confirm.get():
                raise ClinicError("The two passwords do not match.")
            role_label = self.role.get().strip()
            if role_label not in ROLE_BY_LABEL:
                raise ClinicError("Please choose a role from the list.")
            self.clinic.create_user(self.username.get(), self.full_name.get(),
                                    ROLE_BY_LABEL[role_label], self.password.get())
            for var in (self.full_name, self.username, self.role, self.password,
                        self.confirm):
                var.set("")
        self.app.commit(action, "User added.")

    def reset_password(self):
        user_id = selected_id(self, self.tree, "a user")
        if user_id is None:
            return
        fields = [{"key": "new", "label": "New password (6+ characters)",
                   "secret": True},
                  {"key": "confirm", "label": "Confirm new password",
                   "secret": True}]

        def submit(dlg):
            if dlg.get("new") != dlg.get("confirm"):
                raise ClinicError("The two passwords do not match.")
            self.clinic.set_password(user_id, dlg.get("new"))
        FormDialog(self.app, "Reset password", fields, submit,
                   message="Password changed.")

    def delete(self):
        user_id = selected_id(self, self.tree, "a user")
        if user_id is None:
            return
        if ask_yes(self, "Delete user", "Delete this account?"):
            self.app.commit(
                lambda: self.clinic.delete_user(user_id, self.app.user["id"]),
                "User deleted.")

    def backup_now(self):
        try:
            path = self.clinic.backup()
        except (OSError, sqlite3.Error) as err:
            messagebox.showerror("Backup", f"The backup failed:\n{err}",
                                 parent=self)
            return
        self.app.status.set("Backup saved.")
        self.refresh()
        messagebox.showinfo("Backup", f"Backup saved to:\n{path}", parent=self)

    def open_folder(self):
        os.makedirs(self.clinic.backup_dir, exist_ok=True)
        if not open_file(self.clinic.backup_dir):
            messagebox.showinfo("Backups", "Backups are saved in:\n"
                                + self.clinic.backup_dir, parent=self)

    def refresh(self):
        fill_tree(self.tree, self.clinic.list_users(), self.KEYS)
        last = self.clinic.last_backup()
        where = f"Backups folder: {self.clinic.backup_dir}"
        if last:
            self.backup_note.set(f"Last backup: {last[1]:%d %b %Y, %H:%M}.\n{where}")
        else:
            self.backup_note.set(f"No backup yet.\n{where}")


PAGE_CLASSES = (DashboardPage, PatientsPage, VetsPage, AppointmentsPage,
                RecordsPage, BillingPage, ReportsPage, AdminPage)


class ProfileDialog(tk.Toplevel):
    """Everything about one patient on a single screen."""

    TABS = ["Appointments", "Medical history", "Invoices"]

    def __init__(self, app, patient_id):
        super().__init__(app)
        self.withdraw()
        self.app, self.clinic, self.patient_id = app, app.clinic, patient_id
        patient = self.clinic.get_patient(patient_id)
        self.title(f"Patient profile: {patient['name']}")
        self.configure(bg=BG)
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=18)

        head = Card(wrap, fill=PEACH, border=PEACH, radius=24, pad=18,
                    parent_bg=BG)
        head.pack(fill="x")
        paw = tk.Canvas(head.body, width=54, height=54, bg=PEACH,
                        highlightthickness=0, bd=0)
        paw.pack(side="left", padx=(0, 14))
        draw_paw(paw, 0, 0, 54, "#F8BE98")
        info = tk.Frame(head.body, bg=PEACH)
        info.pack(side="left")
        tk.Label(info, text=patient["name"], bg=PEACH, fg=TEXT,
                 font=(FONT, 18, "bold")).pack(anchor="w")
        facts = [patient["species"]]
        if patient["breed"]:
            facts.append(patient["breed"])
        if patient["birth_date"]:
            facts.append(age_text(patient["birth_date"]) + " old")
        if patient["weight_kg"]:
            facts.append(f"{patient['weight_kg']} kg")
        tk.Label(info, text="  |  ".join(facts), bg=PEACH, fg=MUTED_DARK,
                 font=(FONT, 10)).pack(anchor="w")
        owner = tk.Frame(head.body, bg=PEACH)
        owner.pack(side="right")
        tk.Label(owner, text="Owner", bg=PEACH, fg=MUTED_DARK,
                 font=(FONT, 9)).pack(anchor="e")
        for text, size, weight in ((patient["owner_name"], 12, "bold"),
                                   (patient["owner_phone"], 10, "normal"),
                                   (patient["owner_email"] or "", 10, "normal")):
            tk.Label(owner, text=text, bg=PEACH, fg=TEXT,
                     font=(FONT, size, weight)).pack(anchor="e")

        bar = tk.Frame(wrap, bg=BG)
        bar.pack(fill="x", pady=(14, 8))
        self.tab_buttons = []
        for index, name in enumerate(self.TABS):
            button = PillButton(bar, name, lambda i=index: self._show(i),
                                kind="ghost", parent_bg=BG, small=True)
            button.pack(side="left", padx=(0, 8))
            self.tab_buttons.append(button)
        owed = self.clinic.outstanding_total_cents(patient_id)
        tk.Label(bar, text=f"Outstanding: {money(owed)}", bg=BG,
                 fg=DANGER_TEXT if owed else OK_TEXT,
                 font=(FONT, 11, "bold")).pack(side="right")

        card = Card(wrap)
        card.pack(fill="both", expand=True)
        specs = [
            ([("scheduled_at", "When", 130), ("vet", "Veterinarian", 150),
              ("reason", "Reason", 220), ("status", "Status", 90)],
             self.clinic.patient_appointments(patient_id),
             ["scheduled_at", "vet", "reason", "status"], "status"),
            ([("visit_date", "Date", 95), ("vet", "Veterinarian", 130),
              ("diagnosis", "Diagnosis", 170), ("treatment", "Treatment", 170),
              ("notes", "Notes", 160)],
             self.clinic.patient_history(patient_id)[1],
             ["visit_date", "vet", "diagnosis", "treatment", "notes"], None),
            ([("issued_on", "Issued", 95), ("description", "Description", 230),
              ("amount", f"Amount ({CURRENCY})", 100), ("status", "Status", 70),
              ("method", "Method", 100)],
             self.clinic.patient_invoices(patient_id),
             ["issued_on", "description", "amount", "status", "method"], "tag"),
        ]
        self.frames = []
        for columns, rows, keys, tag in specs:
            frame, tree = make_table(card.body, columns, height=7)
            fill_tree(tree, rows, keys, tag_key=tag)
            self.frames.append(frame)

        actions = tk.Frame(wrap, bg=BG)
        actions.pack(fill="x", pady=(14, 0))
        PillButton(actions, "Close", self.destroy, kind="ghost",
                   parent_bg=BG).pack(side="right")
        extras = []
        if app.can("patients.edit"):
            extras.append(("Edit patient", self._edit))
        if app.can("appointments.book"):
            extras.append(("Book appointment",
                           lambda: self._go("Appointments")))
        if app.can("records.edit"):
            extras.append(("Add medical record",
                           lambda: self._go("Medical Records")))
        if app.can("billing.manage"):
            extras.append(("Create invoice", lambda: self._go("Billing")))
        for text, command in extras:
            PillButton(actions, text, command, parent_bg=BG).pack(
                side="left", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self._show(0)
        self.transient(app)
        center_over(self, app)
        self.deiconify()

    def _show(self, index):
        for i, (frame, button) in enumerate(zip(self.frames, self.tab_buttons)):
            if i == index:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
            button.set_kind("primary" if i == index else "ghost")

    def _go(self, page):
        self.destroy()
        self.app.go_to(page, self.patient_id)

    def _edit(self):
        self.destroy()
        self.app.go_to("Patients")
        self.app.pages["Patients"].edit_patient(self.patient_id)


# --------------------------------------------------------------------------
# Sign in
# --------------------------------------------------------------------------
class LoginView(tk.Frame):
    """The first screen: sign in, or create the first administrator account."""

    def __init__(self, app):
        super().__init__(app, bg=BG)
        self.app = app
        self.first_run = app.clinic.user_count() == 0
        card = Card(self, parent_bg=BG, radius=28, pad=30)
        card.place(relx=0.5, rely=0.5, anchor="center")
        logo = tk.Canvas(card.body, width=56, height=56, bg=CARD,
                         highlightthickness=0, bd=0)
        logo.pack()
        draw_paw(logo, 0, 0, 56, PRIMARY)
        tk.Label(card.body, text=APP_NAME, bg=CARD, fg=TEXT,
                 font=(FONT, 24, "bold")).pack(pady=(6, 0))
        tk.Label(card.body, text=APP_SUBTITLE, bg=CARD, fg=MUTED, font=(FONT, 10),
                 wraplength=300, justify="center").pack(pady=(0, 16))
        if self.first_run:
            tk.Label(card.body, text="Welcome! Create the first administrator "
                     "account.", bg=CARD, fg=TEXT, font=(FONT, 10, "bold"),
                     wraplength=300).pack(pady=(0, 10))
            self.full_name, _, _ = add_field(card.body, "Full name", width=300)
        self.username, self.username_box, _ = add_field(card.body, "Username",
                                                        width=300)
        self.password, self.password_box, _ = add_field(
            card.body, "Password", width=300, secret=True)
        self.confirm = None
        if self.first_run:
            self.confirm, self.confirm_box, _ = add_field(
                card.body, "Confirm password", width=300, secret=True)
        last = self.confirm_box if self.first_run else self.password_box
        last.widget.bind("<Return>", lambda _e: self.submit())
        self.message = tk.StringVar()
        tk.Label(card.body, textvariable=self.message, bg=CARD, fg=DANGER_TEXT,
                 font=(FONT, 9), wraplength=300).pack(pady=(0, 6))
        PillButton(card.body, "Create account" if self.first_run else "Sign in",
                   self.submit).pack(fill="x")
        if app.demo and not self.first_run:
            working = [f"{u} / {p}" for u, _n, _r, p in DEMO_USERS
                       if app.clinic.authenticate(u, p)]
            if working:
                tk.Label(card.body, text="Demo logins:\n" + "\n".join(working),
                         bg=CARD, fg=MUTED, font=(FONT, 9),
                         justify="left").pack(pady=(14, 0))
        self.after(150, lambda: self.username_box.widget.focus_set())

    def submit(self):
        clinic = self.app.clinic
        try:
            if self.first_run:
                if self.password.get() != self.confirm.get():
                    raise ClinicError("The two passwords do not match.")
                clinic.create_user(self.username.get(), self.full_name.get(),
                                   "admin", self.password.get())
            user = clinic.authenticate(self.username.get(), self.password.get())
            if user is None:
                raise ClinicError("Wrong username or password.")
        except ClinicError as err:
            self.message.set(str(err))
            return
        self.app.start_session(user)


# --------------------------------------------------------------------------
# Window icon (a paw print, embedded as PNG data so no extra file is needed)
# --------------------------------------------------------------------------

def make_app_icon(size=64):
    """Draw the paw-print icon (coral paw on a peach tile) with plain code."""
    peach, paw = (255, 224, 204), (240, 138, 85)
    img = tk.PhotoImage(width=size, height=size)
    radius = size * 0.24                      # rounded corners of the tile
    scale, offset = size * 0.62 / 46, size * 0.19
    # one pad and four toes: (centre x, centre y, radius x, radius y) on a 46 x 46 grid
    parts = [(23, 34, 12, 10), (7, 23, 5, 6), (16.5, 12.5, 5.5, 7.5),
             (29.5, 12.5, 5.5, 7.5), (39, 23, 5, 6)]

    def on_paw(px, py):
        gx, gy = (px - offset) / scale, (py - offset) / scale
        return any(((gx - cx) / rx) ** 2 + ((gy - cy) / ry) ** 2 <= 1
                   for cx, cy, rx, ry in parts)

    for y in range(size):
        for x in range(size):
            dx = max(radius - x - 0.5, x + 0.5 - (size - radius), 0)
            dy = max(radius - y - 0.5, y + 0.5 - (size - radius), 0)
            if dx * dx + dy * dy > radius * radius:
                continue                      # outside the tile: stay transparent
            hits = sum(on_paw(x + (i + 0.5) / 3, y + (j + 0.5) / 3)
                       for i in range(3) for j in range(3))
            mix = hits / 9                    # smooth the paw's edges
            r, g, b = (round(peach[n] + (paw[n] - peach[n]) * mix)
                       for n in range(3))
            img.put(f"#{r:02x}{g:02x}{b:02x}", (x, y))
    return img


def set_window_icon(root):
    """Replace the default Tk 'X' icon in the title bar and taskbar."""
    try:
        root._app_icon = make_app_icon(64)    # keep a reference or Tk drops it
        root.iconphoto(True, root._app_icon)
    except tk.TclError:
        pass                                  # keep the default icon if this fails

# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class VetApp(tk.Tk):
    def __init__(self, clinic, demo=False):
        super().__init__()
        self.clinic = clinic
        self.demo = demo
        self.user = None
        self.title(f"{APP_NAME}: {APP_SUBTITLE}")
        set_window_icon(self)
        self.minsize(1100, 660)
        self.center(1240, 740)
        apply_theme(self)

        self.status = tk.StringVar(value=f"Welcome to {APP_NAME}.")
        self.page_title = tk.StringVar()
        self.page_sub = tk.StringVar()
        self.nav, self.pages = {}, {}
        self.shell = self.login = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_login()

    def center(self, width, height):
        x = (self.winfo_screenwidth() - width) // 2
        y = max((self.winfo_screenheight() - height) // 2 - 20, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # -- sign in / out ---------------------------------------------------------------
    def show_login(self):
        if self.shell is not None:
            self.shell.destroy()
            self.shell = None
        self.user = None
        self.nav, self.pages = {}, {}
        self.login = LoginView(self)
        self.login.pack(fill="both", expand=True)

    def start_session(self, user):
        self.user = dict(user)
        if self.login is not None:
            self.login.destroy()
            self.login = None
        self.status.set(f"Signed in as {self.user['full_name']}.")
        self.shell = tk.Frame(self, bg=BG)
        self.shell.pack(fill="both", expand=True)
        self.build_sidebar(self.shell)
        self.build_content(self.shell)
        self.refresh_all()
        self.show_page("Dashboard")

    def logout(self):
        if ask_yes(self, "Log out", "Log out of PetVault?"):
            self.show_login()

    def change_password(self):
        fields = [{"key": "old", "label": "Current password", "secret": True},
                  {"key": "new", "label": "New password (6+ characters)",
                   "secret": True},
                  {"key": "confirm", "label": "Confirm new password",
                   "secret": True}]

        def submit(dlg):
            if dlg.get("new") != dlg.get("confirm"):
                raise ClinicError("The two new passwords do not match.")
            self.clinic.change_password(self.user["id"], dlg.get("old"),
                                        dlg.get("new"))
        FormDialog(self, "Change password", fields, submit,
                   message="Your password was changed.")

    def can(self, action):
        return (self.user is not None
                and self.user["role"] in PERMISSIONS.get(action, ()))

    def allowed_pages(self):
        return [c for c in PAGE_CLASSES if self.user["role"] in c.roles]

    # -- layout ----------------------------------------------------------------------------
    def build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=SIDEBAR, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", padx=20, pady=(26, 22))
        logo = tk.Canvas(brand, width=46, height=46, bg=SIDEBAR,
                         highlightthickness=0, bd=0)
        logo.pack(side="left")
        draw_paw(logo, 0, 0, 46, PRIMARY)
        names = tk.Frame(brand, bg=SIDEBAR)
        names.pack(side="left", padx=12)
        tk.Label(names, text=APP_NAME, bg=SIDEBAR, fg=TEXT,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(names, text="Veterinary Clinic", bg=SIDEBAR, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w")

        # the signed-in user sits at the bottom (packed first to keep its space)
        user_box = tk.Frame(sidebar, bg=SIDEBAR)
        user_box.pack(side="bottom", fill="x", padx=18, pady=16)
        tk.Label(user_box, text=self.user["full_name"], bg=SIDEBAR, fg=TEXT,
                 font=(FONT, 10, "bold"), wraplength=170,
                 justify="left").pack(anchor="w")
        tk.Label(user_box, text=ROLE_LABELS[self.user["role"]], bg=SIDEBAR,
                 fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(0, 8))
        PillButton(user_box, "Change password", self.change_password,
                   kind="ghost", parent_bg=SIDEBAR, small=True).pack(
                       anchor="w", pady=(0, 6))
        PillButton(user_box, "Log out", self.logout, kind="ghost",
                   parent_bg=SIDEBAR, small=True).pack(anchor="w")

        for page_class in self.allowed_pages():
            button = NavButton(
                sidebar, page_class.title,
                lambda name=page_class.title: self.show_page(name))
            button.pack(fill="x", padx=14, pady=3)
            self.nav[page_class.title] = button

    def build_content(self, parent):
        content = tk.Frame(parent, bg=BG)
        content.pack(side="left", fill="both", expand=True)

        top = tk.Frame(content, bg=BG)
        top.pack(fill="x", padx=28, pady=(22, 12))
        heading = tk.Frame(top, bg=BG)
        heading.pack(side="left")
        tk.Label(heading, textvariable=self.page_title, bg=BG, fg=TEXT,
                 font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(heading, textvariable=self.page_sub, bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack(anchor="w")
        tk.Label(top, text=date.today().strftime("%A, %d %B %Y"), bg=BG,
                 fg=MUTED, font=(FONT, 10)).pack(side="right")

        tk.Label(content, textvariable=self.status, bg=BG, fg=MUTED,
                 anchor="w", font=(FONT, 9)).pack(side="bottom", fill="x",
                                                  padx=28, pady=(0, 12))

        holder = tk.Frame(content, bg=BG)
        holder.pack(fill="both", expand=True, padx=28, pady=(0, 8))
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        for page_class in self.allowed_pages():
            page = page_class(self, holder)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[page_class.title] = page

    def show_page(self, name):
        page = self.pages[name]
        page.refresh()
        page.tkraise()
        self.page_title.set(page.title)
        self.page_sub.set(page.subtitle)
        for title, button in self.nav.items():
            button.set_active(title == name)

    def go_to(self, name, patient_id=None):
        """Open a screen, optionally with one patient already chosen."""
        if name not in self.pages:
            return
        self.show_page(name)
        if patient_id is not None:
            self.pages[name].preselect_patient(patient_id)

    # -- shared data for dropdowns ------------------------------------------------------------
    def patient_choices(self):
        return [f"{r['id']} - {r['name']} ({r['owner_name']})"
                for r in self.clinic.search_patients("")]

    def patient_text(self, patient_id):
        return next((c for c in self.patient_choices()
                     if c.startswith(f"{patient_id} - ")), "")

    def vet_choices(self):
        return [f"{r['id']} - {r['name']}" for r in self.clinic.list_vets()]

    # -- actions -----------------------------------------------------------------------------------
    def commit(self, action, message):
        """Run a database action, report errors in a dialog, refresh on success."""
        try:
            action()
        except ClinicError as err:
            messagebox.showerror("Cannot complete action", str(err),
                                 parent=self)
            return False
        self.status.set(message)
        self.refresh_all()
        return True

    def refresh_all(self):
        for page in self.pages.values():
            page.refresh()

    def on_close(self):
        try:
            self.clinic.backup()  # automatic backup every time the app closes
        except (OSError, sqlite3.Error):
            pass
        self.clinic.close()
        self.destroy()


def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME}: {APP_SUBTITLE}")
    parser.add_argument("--db", default=DB_FILE, help="SQLite database file")
    parser.add_argument("--demo", action="store_true",
                        help="load sample data and demo logins")
    args = parser.parse_args()

    clinic = Clinic(args.db)
    if args.demo:
        load_demo_data(clinic)
    VetApp(clinic, demo=args.demo).mainloop()


if __name__ == "__main__":
    main()
