"""ProfileDialog: everything about one patient on a single screen."""

import tkinter as tk

from petvault.config import CURRENCY
from petvault.ui import theme
from petvault.ui.dialogs.modal import center_over
from petvault.ui.drawing import draw_paw
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import BG, DANGER_TEXT, MUTED_DARK, OK_TEXT, PEACH, TEXT
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.pill_button import PillButton
from petvault.utils import age_text, money


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
                 font=(theme.FONT, 18, "bold")).pack(anchor="w")
        facts = [patient["species"]]
        if patient["breed"]:
            facts.append(patient["breed"])
        if patient["birth_date"]:
            facts.append(age_text(patient["birth_date"]) + " old")
        if patient["weight_kg"]:
            facts.append(f"{patient['weight_kg']} kg")
        tk.Label(info, text="  |  ".join(facts), bg=PEACH, fg=MUTED_DARK,
                 font=(theme.FONT, 10)).pack(anchor="w")
        owner = tk.Frame(head.body, bg=PEACH)
        owner.pack(side="right")
        tk.Label(owner, text="Owner", bg=PEACH, fg=MUTED_DARK,
                 font=(theme.FONT, 9)).pack(anchor="e")
        for text, size, weight in ((patient["owner_name"], 12, "bold"),
                                   (patient["owner_phone"], 10, "normal"),
                                   (patient["owner_email"] or "", 10, "normal")):
            tk.Label(owner, text=text, bg=PEACH, fg=TEXT,
                     font=(theme.FONT, size, weight)).pack(anchor="e")

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
                 font=(theme.FONT, 11, "bold")).pack(side="right")

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
