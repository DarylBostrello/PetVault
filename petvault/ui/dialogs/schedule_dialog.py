"""ScheduleDialog: edit a veterinarian's weekly hours and days off."""

import tkinter as tk
from tkinter import messagebox

from petvault.config import DEFAULT_END, DEFAULT_START, WEEKDAYS
from petvault.errors import ClinicError
from petvault.ui import theme
from petvault.ui.constants import SCHEDULE_TIMES
from petvault.ui.dialogs.modal import make_modal
from petvault.ui.helpers import add_field
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import BG, CARD, MUTED, OK_TEXT, PRIMARY_H, TEXT
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.pill_button import PillButton
from petvault.ui.widgets.rounded_field import RoundedField
from petvault.ui.widgets.toggle_button import ToggleButton


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
                 fg=TEXT, font=(theme.FONT, 14, "bold")).pack(anchor="w")
        tk.Label(card.body, text="Appointments can only be booked inside these "
                 "hours and never on days off.", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(anchor="w", pady=(2, 10))
        body = tk.Frame(card.body, bg=CARD)
        body.pack()

        left = tk.Frame(body, bg=CARD)
        left.pack(side="left", fill="y", padx=(0, 28))
        tk.Label(left, text="Weekly hours", bg=CARD, fg=PRIMARY_H,
                 font=(theme.FONT, 10, "bold")).pack(anchor="w", pady=(0, 6))
        schedule = {r["weekday"]: r for r in self.clinic.get_schedule(vet_id)}
        self.rows = []
        for weekday, name in enumerate(WEEKDAYS):
            row = tk.Frame(left, bg=CARD)
            row.pack(fill="x", pady=3)
            sched = schedule.get(weekday)
            tk.Label(row, text=name, width=10, anchor="w", bg=CARD, fg=TEXT,
                     font=(theme.FONT, 10)).pack(side="left")
            toggle = ToggleButton(row, value=bool(sched["working"]) if sched else True)
            toggle.pack(side="left", padx=(0, 10))
            start, end = tk.StringVar(), tk.StringVar()
            start.set(sched["start_time"] if sched else DEFAULT_START)
            end.set(sched["end_time"] if sched else DEFAULT_END)
            start_field = RoundedField(row, start, choices=SCHEDULE_TIMES,
                                       strict=True, width=100)
            start_field.pack(side="left")
            tk.Label(row, text="to", bg=CARD, fg=MUTED, font=(theme.FONT, 9)).pack(
                side="left", padx=6)
            end_field = RoundedField(row, end, choices=SCHEDULE_TIMES,
                                     strict=True, width=100)
            end_field.pack(side="left")
            self.rows.append((weekday, toggle, start_field, end_field))
        foot = tk.Frame(left, bg=CARD)
        foot.pack(fill="x", pady=(12, 0))
        self.note = tk.StringVar()
        tk.Label(foot, textvariable=self.note, bg=CARD, fg=OK_TEXT,
                 font=(theme.FONT, 9)).pack(side="left")
        PillButton(foot, "Save weekly hours", self._save_hours).pack(side="right")

        right = tk.Frame(body, bg=CARD)
        right.pack(side="left", fill="both")
        tk.Label(right, text="Days off and leave", bg=CARD, fg=PRIMARY_H,
                 font=(theme.FONT, 10, "bold")).pack(anchor="w", pady=(0, 6))
        frame, self.tree = make_table(right, [
            ("start_date", "From", 95), ("end_date", "To", 95),
            ("note", "Note", 140)], height=5, paged=False)
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
