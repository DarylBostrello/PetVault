"""The Clinic class: every database operation and business rule (no screens in here)."""

import calendar as pycal
import os
import sqlite3
from datetime import date, datetime, timedelta

from petvault.config import (
    DATETIME_FMT,
    DATE_FMT,
    DB_FILE,
    DEFAULT_END,
    DEFAULT_START,
    PAYMENT_METHODS,
    ROLES,
    SLOT_MINUTES,
    WEEKDAYS,
)
from petvault.errors import ClinicError
from petvault.schema import MIGRATIONS, SCHEMA
from petvault.security import check_password, hash_password
from petvault.utils import parse_date, plural, require, slot_times, to_minutes


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
