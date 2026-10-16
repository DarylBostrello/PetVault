"""The Reports screen."""

from datetime import date
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox

from petvault.database import Clinic
from petvault.errors import ClinicError
from petvault.files import summary_lines, write_csv, write_pdf
from petvault.ui import theme
from petvault.ui.helpers import add_field, offer_open
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table, reset_page
from petvault.ui.theme import (
    CARD,
    LAVENDER,
    MINT_BG,
    MUTED,
    PINK,
    PRIMARY_H,
    SKY,
    TEXT,
)
from petvault.ui.widgets.pill_button import PillButton
from petvault.ui.widgets.stat_card import StatCard
from petvault.utils import money, parse_date


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
                 "this date.", bg=CARD, fg=MUTED, font=(theme.FONT, 9),
                 wraplength=220, justify="left").pack(anchor="w", pady=(0, 14))
        self.kind.set("Daily")
        self.day.set(date.today().isoformat())
        tk.Label(form.body, text="Export", bg=CARD, fg=PRIMARY_H,
                 font=(theme.FONT, 10, "bold")).pack(anchor="w", pady=(0, 6))
        for text, command, kind in (
                ("Summary (PDF)", self.export_pdf, "primary"),
                ("Appointments (CSV)", self.export_appointments, "ghost"),
                ("Invoices (CSV)", self.export_invoices, "ghost"),
                ("All patients (CSV)", self.export_patients, "ghost")):
            PillButton(form.body, text, command, kind=kind).pack(
                anchor="w", pady=3)

        self.heading = tk.StringVar()
        tk.Label(right.body, textvariable=self.heading, bg=CARD, fg=TEXT,
                 font=(theme.FONT, 13, "bold"), anchor="w").pack(fill="x",
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
                 font=(theme.FONT, 11, "bold")).pack(anchor="w", pady=(14, 6))
        frame, self.vet_tree = make_table(right.body, [
            ("vet", "Veterinarian", 200), ("total", "Appointments", 110),
            ("completed", "Completed", 100)], height=3, paged=False)
        frame.pack(fill="x")
        tk.Label(right.body, text="Appointments in this period", bg=CARD,
                 fg=TEXT, font=(theme.FONT, 11, "bold")).pack(anchor="w",
                                                        pady=(14, 6))
        frame, self.appt_tree = make_table(right.body, [
            ("id", "ID", 40), ("scheduled_at", "When", 125),
            ("patient", "Patient", 90), ("owner", "Owner", 110),
            ("vet", "Vet", 110), ("reason", "Reason", 150),
            ("status", "Status", 85)])
        frame.pack(fill="both", expand=True)
        self.kind.trace_add("write", lambda *_: (reset_page(self.appt_tree),
                                                 self.refresh()))
        self.day.trace_add("write", lambda *_: (reset_page(self.appt_tree),
                                                self.refresh()))

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
