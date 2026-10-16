"""The Patients screen."""

from datetime import date
import tkinter as tk

from petvault.ui import theme
from petvault.ui.constants import SPECIES
from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.dialogs.profile_dialog import ProfileDialog
from petvault.ui.helpers import add_field, ask_yes, selected_id
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import CARD, MUTED, TEXT
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.pill_button import PillButton
from petvault.ui.widgets.rounded_field import RoundedField
from petvault.utils import age_text, parse_weight


class PatientsPage(BasePage):
    title = "Patients"
    subtitle = "Register a pet together with its owner's details"
    SORTS = ["ID", "A - Z", "Z - A"]
    KEYS = ["id", "name", "species", "breed",
            lambda row: age_text(row["birth_date"]), "weight_kg",
            "owner_name", "owner_phone", "owner_email"]

    def build(self):
        if self.app.can("patients.edit"):
            self._build_form()
        table_card = Card(self)
        table_card.pack(fill="both", expand=True)
        bar = tk.Frame(table_card.body, bg=CARD)
        bar.pack(fill="x", pady=(0, 10))
        tk.Label(bar, text="All patients", bg=CARD, fg=TEXT,
                 font=(theme.FONT, 13, "bold")).pack(side="left")
        self.search = tk.StringVar()
        self.sort = tk.StringVar(value=self.SORTS[0])
        RoundedField(bar, self.search, width=230).pack(side="right")
        tk.Label(bar, text="Search", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="right", padx=8)
        RoundedField(bar, self.sort, choices=self.SORTS, strict=True,
                     width=130, on_pick=lambda _t: self.view_changed()).pack(
                         side="right", padx=(0, 16))
        tk.Label(bar, text="Sort by", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="right", padx=8)
        self.search.trace_add("write", lambda *_: self.view_changed())
        frame, self.tree = make_table(table_card.body, [
            ("id", "ID", 40), ("name", "Patient", 100),
            ("species", "Species", 75), ("breed", "Breed", 120),
            ("age", "Age", 60), ("weight_kg", "kg", 50),
            ("owner_name", "Owner", 140), ("owner_phone", "Phone", 120),
            ("owner_email", "Email", 170)])
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_profile())

        buttons = tk.Frame(table_card.body, bg=CARD)
        buttons.pack(fill="x", pady=(10, 0))
        PillButton(buttons, "Open profile", self.open_profile).pack(side="left")
        if self.app.can("patients.edit"):
            PillButton(buttons, "Edit patient", self.edit, kind="ghost").pack(
                side="left", padx=8)
        if self.app.can("patients.delete"):
            PillButton(buttons, "Delete", self.delete, kind="danger").pack(
                side="left")
        tk.Label(buttons, text="Tip: double-click a patient to open the profile.",
                 bg=CARD, fg=MUTED, font=(theme.FONT, 9)).pack(side="right")

    def _build_form(self):
        form = Card(self)
        form.pack(fill="x", pady=(0, 14))
        head = tk.Frame(form.body, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text="Register patient", bg=CARD, fg=TEXT,
                 font=(theme.FONT, 13, "bold")).pack(side="left")
        self.form_toggle = PillButton(head, "Hide form", self._toggle_form,
                                      kind="ghost", small=True)
        self.form_toggle.pack(side="right")
        tk.Label(form.body, text="The owner's name, phone and email are saved "
                 "with the patient.", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(anchor="w")
        tk.Frame(form.body, bg=CARD, height=10).pack()
        grid = tk.Frame(form.body, bg=CARD)
        grid.pack(fill="x")
        self.form_grid, self.form_shown = grid, True
        for col in range(5):
            grid.columnconfigure(col, weight=1, uniform="pf")

        def put(row, col, label, **kw):
            var, field, box = add_field(grid, label, pack=False, width=120, **kw)
            box.grid(row=row, column=col, sticky="we", pady=(0, 8),
                     padx=(0 if col == 0 else 10, 0))
            return var, field

        self.name, _ = put(0, 0, "Patient name")
        self.species, _ = put(0, 1, "Species", choices=SPECIES)
        self.breed, _ = put(0, 2, "Breed (optional)")
        self.born, _ = put(0, 3, "Born (type or pick)",
                           calendar=(None, date.today()))
        self.weight, _ = put(0, 4, "Weight in kg (optional)")
        self.owner, self.owner_box = put(1, 0, "Owner name", choices=[],
                                         on_pick=self._owner_chosen)
        self.phone, _ = put(1, 1, "Owner phone")
        self.email, _ = put(1, 2, "Owner email (optional)")
        self.owner_box.widget.bind("<FocusOut>", self._owner_left, add="+")
        PillButton(grid, "Register patient", self.add).grid(
            row=1, column=4, sticky="se", pady=(0, 8))

    def _toggle_form(self):
        """Fold the registration form away to make room for more table rows."""
        self.form_shown = not self.form_shown
        if self.form_shown:
            self.form_grid.pack(fill="x")
        else:
            self.form_grid.pack_forget()
        self.form_toggle.set_text("Hide form" if self.form_shown else "Show form")

    def _owner_chosen(self, _text=None):
        """Fill phone and email when an existing owner is picked."""
        contact = self.clinic.owner_contact(self.owner.get())
        if contact:
            self.phone.set(contact["owner_phone"] or "")
            self.email.set(contact["owner_email"] or "")

    def _owner_left(self, _event=None):
        if not self.phone.get().strip():
            self._owner_chosen()

    def add(self):
        def action():
            self.clinic.add_patient(
                self.name.get(), self.species.get(), self.owner.get(),
                self.phone.get(), breed=self.breed.get(),
                birth_date=self.born.get(),
                weight_kg=parse_weight(self.weight.get()),
                owner_email=self.email.get())
            for var in (self.name, self.breed, self.born, self.weight,
                        self.owner, self.phone, self.email):
                var.set("")
        self.app.commit(action, "Patient registered.")

    def open_profile(self):
        patient_id = selected_id(self, self.tree, "a patient")
        if patient_id is not None:
            ProfileDialog(self.app, patient_id)

    def edit(self):
        patient_id = selected_id(self, self.tree, "a patient")
        if patient_id is not None:
            self.edit_patient(patient_id)

    def edit_patient(self, patient_id):
        patient = self.clinic.get_patient(patient_id)
        fields = [
            {"key": "name", "label": "Patient name", "value": patient["name"]},
            {"key": "species", "label": "Species", "choices": SPECIES,
             "value": patient["species"]},
            {"key": "breed", "label": "Breed", "value": patient["breed"] or ""},
            {"key": "born", "label": "Born (type or pick)",
             "calendar": (None, date.today()),
             "value": patient["birth_date"] or ""},
            {"key": "weight", "label": "Weight in kg",
             "value": "" if patient["weight_kg"] is None
             else str(patient["weight_kg"])},
            {"heading": "Owner"},
            {"key": "owner", "label": "Owner name", "choices":
             self.clinic.owner_names(), "value": patient["owner_name"]},
            {"key": "phone", "label": "Owner phone",
             "value": patient["owner_phone"]},
            {"key": "email", "label": "Owner email",
             "value": patient["owner_email"] or ""},
        ]

        def submit(dlg):
            self.clinic.update_patient(
                patient_id, dlg.get("name"), dlg.get("species"), dlg.get("owner"),
                dlg.get("phone"), breed=dlg.get("breed"),
                birth_date=dlg.get("born"),
                weight_kg=parse_weight(dlg.get("weight")),
                owner_email=dlg.get("email"))
        FormDialog(self.app, f"Edit {patient['name']}", fields, submit,
                   message="Patient updated.")

    def delete(self):
        patient_id = selected_id(self, self.tree, "a patient")
        if patient_id is None:
            return
        name = self.clinic.get_patient(patient_id)["name"]
        if ask_yes(self, "Delete patient",
                   f"Delete {name}? This cannot be undone."):
            self.app.commit(lambda: self.clinic.delete_patient(patient_id),
                            f"{name} was deleted.")

    def refresh_list(self):
        rows = self.clinic.search_patients(self.search.get())
        mode = self.sort.get()
        if mode == "A - Z":
            rows = sorted(rows, key=lambda r: r["name"].lower())
        elif mode == "Z - A":
            rows = sorted(rows, key=lambda r: r["name"].lower(), reverse=True)
        fill_tree(self.tree, rows, self.KEYS)

    def refresh(self):
        if self.app.can("patients.edit"):
            self.owner_box.set_choices(self.clinic.owner_names())
        self.refresh_list()
