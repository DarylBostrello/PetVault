"""The Appointments screen."""

from datetime import date
import tkinter as tk
from tkinter import messagebox

from petvault.config import CURRENCY, PAYMENT_METHODS
from petvault.errors import ClinicError
from petvault.ui import theme
from petvault.ui.constants import TIME_SLOTS
from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.helpers import add_field, ask_yes, choice_id, selected_id
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import CARD, MUTED
from petvault.ui.widgets.pill_button import PillButton
from petvault.ui.widgets.rounded_field import RoundedField
from petvault.utils import parse_date, parse_datetime, parse_money_to_cents


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
                     font=(theme.FONT, 9), wraplength=220, justify="left").pack(
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
                     on_pick=lambda _t: self.view_changed()).pack(side="right")
        tk.Label(bar, text="Sort by", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="right", padx=8)
        # filter control on the left: pick what to filter by, then type or pick
        tk.Label(bar, text="Filter by", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="left")
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
        self.filter_text.trace_add("write", lambda *_: self.view_changed())
        self.filter_status.trace_add("write", lambda *_: self.view_changed())

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
        self.view_changed()

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
