"""Settings and fixed values: file locations, date formats, roles, permissions, payment methods."""

import os


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(PROJECT_DIR, "petvault.db")
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
CURRENCY = "₱"  # shown in the app; change to "$", "€", etc. if you like
CURRENCY_CODE = "PHP"  # used in PDFs (the PDF's built-in fonts have no ₱ sign)
# ==========================================================================
# Interface
# ==========================================================================
APP_NAME = "PetVault"
APP_SUBTITLE = "Veterinary Clinic Patient & Appointment Management System"

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
