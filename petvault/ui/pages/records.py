"""The Medical Records screen."""

from datetime import date
import tkinter as tk

from petvault.ui import theme
from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.helpers import add_field, ask_yes, choice_id, selected_id
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import CARD, TEXT
from petvault.ui.widgets.pill_button import PillButton
from petvault.utils import parse_date


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
                 font=(theme.FONT, 13, "bold"), anchor="w").pack(fill="x",
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
