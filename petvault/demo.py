"""Sample data and demo logins for the --demo option."""

from datetime import date, datetime, timedelta

from petvault.config import DATETIME_FMT, ROLE_LABELS
from petvault.database import Clinic
from petvault.utils import parse_money_to_cents


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
