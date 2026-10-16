"""Database and business-rule tests. Needs no Tk:  python tests/test_database.py"""
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from types import SimpleNamespace
from petvault.database import Clinic
from petvault.errors import ClinicError
from petvault.files import build_pdf, write_pdf, write_csv, summary_lines, receipt_lines
assert "tkinter" not in sys.modules, "the database layer must not import Tk"
pv = SimpleNamespace(Clinic=Clinic, ClinicError=ClinicError, build_pdf=build_pdf, write_pdf=write_pdf,
                     write_csv=write_csv, summary_lines=summary_lines, receipt_lines=receipt_lines)
from datetime import date, datetime, timedelta

tmp = tempfile.mkdtemp()
c = pv.Clinic(os.path.join(tmp, "t.db"))
ClinicError = pv.ClinicError

def raises(fn, text=""):
    try: fn()
    except ClinicError as e:
        assert text.lower() in str(e).lower(), (text, str(e)); return str(e)
    raise AssertionError("expected ClinicError: " + text)

# ---- users and passwords
assert c.user_count() == 0
a = c.create_user("Admin", "Boss", "admin", "secret1")
raises(lambda: c.create_user("admin", "X", "vet", "secret1"), "taken")           # case-insensitive unique
raises(lambda: c.create_user("bob", "Bob", "vet", "123"), "6 characters")
raises(lambda: c.create_user("bob", "Bob", "wizard", "secret1"), "role")
assert c.authenticate("admin", "secret1")["id"] == a and c.authenticate("ADMIN", "secret1") is not None
assert c.authenticate("admin", "nope") is None and c.authenticate("ghost", "secret1") is None
assert "secret1" not in c.conn.execute("SELECT password_hash FROM users").fetchone()[0]
raises(lambda: c.delete_user(a, a), "signed in")
raises(lambda: c.delete_user(a, 999), "at least one administrator")
r = c.create_user("rec", "Desk", "receptionist", "desk123")
c.change_password(r, "desk123", "newpass1"); assert c.authenticate("rec", "newpass1")
raises(lambda: c.change_password(r, "wrong", "another1"), "not correct")
c.set_password(r, "reset123"); assert c.authenticate("rec", "reset123")
c.delete_user(r, a); assert c.user_count() == 1
print("users OK")

# ---- patients: edit/delete rules
p1 = c.add_patient("Buddy", "Dog", "Maria", "0917", breed="Lab", birth_date="2020-01-01", weight_kg=20)
p2 = c.add_patient("Mimi", "Cat", "Maria", "0917")
c.update_patient(p2, "Mimi II", "Cat", "Maria S.", "0918", breed="Persian", weight_kg=4.2, owner_email="m@x.com")
assert c.get_patient(p2)["name"] == "Mimi II" and c.get_patient(p2)["owner_phone"] == "0918"
raises(lambda: c.update_patient(p2, "", "Cat", "M", "1"), "required")
v1 = c.add_vet("Dr. A", "GP"); v2 = c.add_vet("Dr. B")
assert len(c.get_schedule(v1)) == 7 and c.get_schedule(v1)[6]["working"] == 0   # Sunday off by default
c.update_vet(v2, "Dr. Bee", "Surgery"); assert c.get_vet(v2)["name"] == "Dr. Bee"
print("patients/vets OK")

# ---- schedules, days off, free slots
def next_weekday(wd, weeks=1):
    d = date.today() + timedelta(days=1)
    while d.weekday() != wd: d += timedelta(days=1)
    return d + timedelta(weeks=weeks - 1)
monday, sunday = next_weekday(0), next_weekday(6)
slots = c.free_slots(v1, monday); print("Monday slots:", slots[0], "...", slots[-1], len(slots))
assert slots[0] == "08:00" and slots[-1] == "17:30" and len(slots) == 20
assert c.free_slots(v1, sunday) == []
def at(d, hhmm): return datetime.combine(d, datetime.strptime(hhmm, "%H:%M").time())
raises(lambda: c.book_appointment(p1, v1, at(sunday, "10:00"), "x"), "does not work")
raises(lambda: c.book_appointment(p1, v1, at(monday, "07:30"), "x"), "works 08:00 to 18:00")
raises(lambda: c.book_appointment(p1, v1, at(monday, "18:00"), "x"), "works")
c.set_schedule(v1, [(w, w < 5, "09:00" if w == 0 else "08:00", "12:00" if w == 0 else "18:00") for w in range(7)])
assert c.free_slots(v1, monday) == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]
raises(lambda: c.set_schedule(v1, [(0, True, "10:00", "10:10")]), "at least 30")
off = c.add_day_off(v1, monday.isoformat(), None, "Training")
assert c.free_slots(v1, monday) == [] and len(c.list_days_off(v1)) == 1
raises(lambda: c.book_appointment(p1, v1, at(monday, "10:00"), "x"), "on leave")
raises(lambda: c.add_day_off(v1, "2026-10-10", "2026-10-01"), "before")
c.delete_day_off(off); assert len(c.free_slots(v1, monday)) == 6
print("schedules OK")

# ---- booking, overlap, reschedule
a1 = c.book_appointment(p1, v1, at(monday, "10:00"), "Checkup")
assert "10:00" not in c.free_slots(v1, monday) and "10:30" in c.free_slots(v1, monday) and "09:30" in c.free_slots(v1, monday)
raises(lambda: c.book_appointment(p2, v1, at(monday, "10:00"), "x"), "already booked")
assert "10:00" in c.free_slots(v1, monday, exclude_id=a1)                 # own slot stays free when rescheduling
c.reschedule_appointment(a1, v1, at(monday, "11:00"), "Checkup 2")
appt = c.get_appointment(a1); assert appt["scheduled_at"].endswith("11:00") and appt["reason"] == "Checkup 2"
c.reschedule_appointment(a1, v1, at(monday, "11:00"), "same slot again")   # allowed (its own slot)
raises(lambda: c.reschedule_appointment(a1, v1, at(sunday, "10:00"), "x"), "does not work")
raises(lambda: c.reschedule_appointment(a1, v1, datetime.now() - timedelta(days=1), "x"), "past")
print("booking/reschedule OK")

# ---- complete visit: record + invoice in one transaction
n_rec = c.conn.execute("select count(*) from medical_records").fetchone()[0]
raises(lambda: c.complete_appointment(a1, record={"diagnosis": " "}, invoice=None), "Diagnosis")
assert c.get_appointment(a1)["status"] == "scheduled"                     # nothing half-saved
raises(lambda: c.complete_appointment(a1, record={"diagnosis": "ok"}, invoice={"description": "x", "amount_cents": 1, "method": "Crypto"}), "payment method")
assert c.get_appointment(a1)["status"] == "scheduled" and c.conn.execute("select count(*) from medical_records").fetchone()[0] == n_rec
res = c.complete_appointment(a1, record={"diagnosis": "Healthy", "treatment": "Booster", "notes": ""},
                             invoice={"description": "Checkup", "amount_cents": 125000, "method": None})
print("complete ->", res)
assert c.get_appointment(a1)["status"] == "completed" and res["record_id"] and res["invoice_id"]
inv = c.get_invoice(res["invoice_id"]); assert inv["paid"] == 0 and inv["appointment_id"] == a1
assert c.get_record(res["record_id"])["appointment_id"] == a1
raises(lambda: c.complete_appointment(a1), "already completed")
a2 = c.book_appointment(p1, v1, at(monday, "09:00"), "Quick")
r2 = c.complete_appointment(a2, record=None, invoice={"description": "Visit", "amount_cents": 50000, "method": "Cash"})
inv2 = c.get_invoice(r2["invoice_id"]); assert inv2["paid"] == 1 and inv2["payment_method"] == "Cash" and inv2["paid_on"] == date.today().isoformat()
print("complete visit OK")

# ---- invoices: edit/delete/pay rules, lists
raises(lambda: c.update_invoice(inv2["id"], "x", 1), "Paid invoices")
raises(lambda: c.void_invoice(inv2["id"], "x"), "Paid invoices")
c.update_invoice(inv["id"], "Checkup + booster", 130000); assert c.get_invoice(inv["id"])["amount_cents"] == 130000
raises(lambda: c.pay_invoice(inv["id"], "Crypto"), "payment method")
assert [r["status"] for r in c.list_invoices("all")] == ["Unpaid", "Paid"] and len(c.list_invoices("paid")) == 1
assert c.outstanding_total_cents() == 130000 and c.outstanding_total_cents(p1) == 130000 and c.outstanding_total_cents(p2) == 0
c.pay_invoice(inv["id"], "Card"); raises(lambda: c.pay_invoice(inv["id"], "Cash"), "already paid")
assert c.outstanding_total_cents() == 0
base = c.outstanding_total_cents()
tmp_inv = c.create_invoice(p1, "Wrong patient", 10000); assert c.outstanding_total_cents() == base + 10000
raises(lambda: c.void_invoice(tmp_inv, "   "), "Reason")
c.void_invoice(tmp_inv, "Entered by mistake")
v = c.get_invoice(tmp_inv)
assert v["voided"] == 1 and v["void_reason"] == "Entered by mistake" and v["voided_on"] == date.today().isoformat()
assert c.outstanding_total_cents() == base                                   # void money is not "owed"
assert [r["status"] for r in c.list_invoices("void")] == ["Void"] and c.list_invoices("void")[0]["tag"] == "void"
assert tmp_inv not in [r["id"] for r in c.list_invoices("outstanding")] and tmp_inv in [r["id"] for r in c.list_invoices("all")]
raises(lambda: c.void_invoice(tmp_inv, "again"), "already void")
raises(lambda: c.update_invoice(tmp_inv, "x", 1), "Void invoices")
raises(lambda: c.pay_invoice(tmp_inv, "Cash"), "void invoice cannot be paid")
assert not hasattr(c, "delete_invoice")                                       # invoices can no longer be deleted
print("void OK")
print("billing OK")

# ---- deletes are blocked when history exists
msg = raises(lambda: c.delete_patient(p1), "cannot be deleted"); print("blocked:", msg)
raises(lambda: c.delete_vet(v1), "cannot be deleted")
c.delete_patient(p2); c.delete_vet(v2)
rid = res["record_id"]; c.update_record(rid, v1, date.today(), "Healthy!", "Booster", "ok"); assert c.get_record(rid)["diagnosis"] == "Healthy!"
c.delete_record(rid); raises(lambda: c.get_record(rid), "No medical record")
c.delete_appointment(a2); assert c.get_invoice(r2["invoice_id"])["appointment_id"] is None   # invoice stays, link cleared
print("edit/delete OK")

# ---- dashboard and reports
assert c.stats()["patients"] == 1
weeks = c.weekly_counts(); assert len(weeks) == 8 and all(w[0].weekday() == 0 for w in weeks); print("weeks:", [(d.strftime('%m-%d'), n) for d, n in weeks])
s, e = pv.Clinic.period_bounds("Monthly", date(2026, 2, 10)); assert (s, e) == (date(2026, 2, 1), date(2026, 2, 28))
assert pv.Clinic.period_bounds("Daily", date(2026, 2, 10)) == (date(2026, 2, 10),) * 2
rep = c.report_summary(date.today() - timedelta(days=30), date.today() + timedelta(days=60))
print({k: v for k, v in rep.items() if k not in ("by_vet",)}); assert rep["appointments"] >= 1
rows = c.report_appointments(date.today(), date.today() + timedelta(days=60)); inv_rows = c.report_invoices(date.today(), date.today())
assert len(inv_rows) == 3 and sorted(r["status"] for r in inv_rows) == ["Paid", "Paid", "Void"]
assert rep["void_count"] == 1 and rep["issued_count"] == 2, (rep["void_count"], rep["issued_count"])   # void invoice is not counted as issued
print("reports OK")

# ---- migration from the previous schema (no new columns, no new tables)
old = os.path.join(tmp, "old.db")
import sqlite3
o = sqlite3.connect(old); o.executescript("""
CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, species TEXT NOT NULL, breed TEXT, birth_date TEXT, weight_kg REAL, owner_name TEXT NOT NULL, owner_phone TEXT NOT NULL, owner_email TEXT);
CREATE TABLE veterinarians (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, specialty TEXT);
CREATE TABLE appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL, vet_id INTEGER NOT NULL, scheduled_at TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled');
CREATE TABLE medical_records (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL, vet_id INTEGER NOT NULL, visit_date TEXT NOT NULL, diagnosis TEXT NOT NULL, treatment TEXT, notes TEXT);
CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL, issued_on TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 0);
INSERT INTO patients (name, species, owner_name, owner_phone) VALUES ('Old', 'Dog', 'Owner', '1');
INSERT INTO veterinarians (name) VALUES ('Dr Old');
INSERT INTO invoices (patient_id, description, amount_cents, issued_on, paid) VALUES (1, 'old invoice', 500, '2026-01-01', 1);
"""); o.commit(); o.close()
m = pv.Clinic(old)
cols = {r["name"] for r in m.conn.execute("pragma table_info(invoices)")}
assert {"payment_method", "paid_on", "appointment_id", "voided", "void_reason", "voided_on"} <= cols and len(m.get_schedule(1)) == 7
assert m.list_invoices("paid")[0]["description"] == "old invoice"
print("migration OK (old data kept, new columns/schedules added)")

# ---- backup
path = c.backup(); assert os.path.exists(path)
b = pv.Clinic(path); assert b.user_count() == 1; b.close()
for i in range(15):
    open(os.path.join(c.backup_dir, f"petvault-2020010100{i:04d}.db"), "wb").write(b"x")
c.backup()
files = sorted(os.listdir(c.backup_dir)); print("backup files kept:", len(files)); assert len(files) == 10 and files[-1] > "petvault-2021"
assert c.last_backup()[0].startswith("petvault-")
print("backup OK")

# ---- PDF / CSV
inv_row = c.get_invoice(inv["id"])
data = pv.build_pdf(pv.receipt_lines(inv_row))
assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
open(os.path.join(tmp, "receipt.pdf"), "wb").write(data)
pv.write_pdf(os.path.join(tmp, "summary.pdf"), pv.summary_lines(rep), mono=True)
pv.write_csv(os.path.join(tmp, "x.csv"), ["a", "b"], [[1, "x, y"], [2, "é"]]); print(open(os.path.join(tmp, "x.csv"), encoding="utf-8-sig").read().strip().splitlines())
long = [f"line {i}" for i in range(200)]
import re
big = pv.build_pdf(long); pages = big.count(b"/Type /Page "); assert pages >= 4 and (b"/Count %d" % pages) in big; print("pages for 200 lines:", pages)
print("files OK")
print("ALL CLINIC TESTS PASSED")
