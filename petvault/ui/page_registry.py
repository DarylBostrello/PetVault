"""The list of screens (in menu order)."""

from petvault.ui.pages.admin import AdminPage
from petvault.ui.pages.appointments import AppointmentsPage
from petvault.ui.pages.billing import BillingPage
from petvault.ui.pages.dashboard import DashboardPage
from petvault.ui.pages.patients import PatientsPage
from petvault.ui.pages.records import RecordsPage
from petvault.ui.pages.reports import ReportsPage
from petvault.ui.pages.vets import VetsPage


PAGE_CLASSES = (DashboardPage, PatientsPage, VetsPage, AppointmentsPage,
                RecordsPage, BillingPage, ReportsPage, AdminPage)
