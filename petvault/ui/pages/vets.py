"""The Veterinarians screen."""

import tkinter as tk

from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.dialogs.schedule_dialog import ScheduleDialog
from petvault.ui.helpers import add_field, ask_yes, card_title, selected_id
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import CARD
from petvault.ui.widgets.pill_button import PillButton


class VetsPage(BasePage):
    title = "Veterinarians"
    subtitle = "The doctors who attend to your patients"
    KEYS = ["id", "name", "specialty"]

    def build(self):
        manage = self.app.can("vets.manage")
        form, right = self.side_layout("Add veterinarian", with_form=manage)
        if manage:
            self.name, _, _ = add_field(form.body, "Name")
            self.specialty, _, _ = add_field(form.body, "Specialty (optional)")
            PillButton(form.body, "Add veterinarian", self.add).pack(anchor="e")
        card_title(right.body, "Veterinarians")
        frame, self.tree = make_table(right.body, [
            ("id", "ID", 50), ("name", "Name", 240),
            ("specialty", "Specialty", 240)])
        frame.pack(fill="both", expand=True)
        if manage:
            buttons = tk.Frame(right.body, bg=CARD)
            buttons.pack(fill="x", pady=(10, 0))
            PillButton(buttons, "Working hours", self.schedule).pack(side="left")
            PillButton(buttons, "Edit", self.edit, kind="ghost").pack(
                side="left", padx=8)
            PillButton(buttons, "Delete", self.delete, kind="danger").pack(
                side="left")

    def add(self):
        def action():
            self.clinic.add_vet(self.name.get(), self.specialty.get())
            self.name.set("")
            self.specialty.set("")
        self.app.commit(action, "Veterinarian added (Monday to Saturday, "
                        "08:00 to 18:00 by default).")

    def schedule(self):
        vet_id = selected_id(self, self.tree, "a veterinarian")
        if vet_id is not None:
            ScheduleDialog(self.app, vet_id)

    def edit(self):
        vet_id = selected_id(self, self.tree, "a veterinarian")
        if vet_id is None:
            return
        vet = self.clinic.get_vet(vet_id)
        fields = [{"key": "name", "label": "Name", "value": vet["name"]},
                  {"key": "specialty", "label": "Specialty",
                   "value": vet["specialty"] or ""}]

        def submit(dlg):
            self.clinic.update_vet(vet_id, dlg.get("name"), dlg.get("specialty"))
        FormDialog(self.app, f"Edit {vet['name']}", fields, submit,
                   message="Veterinarian updated.")

    def delete(self):
        vet_id = selected_id(self, self.tree, "a veterinarian")
        if vet_id is None:
            return
        name = self.clinic.get_vet(vet_id)["name"]
        if ask_yes(self, "Delete veterinarian",
                   f"Delete {name}? This cannot be undone."):
            self.app.commit(lambda: self.clinic.delete_vet(vet_id),
                            f"{name} was deleted.")

    def refresh(self):
        fill_tree(self.tree, self.clinic.list_vets(), self.KEYS)
