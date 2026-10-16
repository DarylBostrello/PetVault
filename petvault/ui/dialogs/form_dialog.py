"""FormDialog: a small rounded pop-up form used for edits, payments, voiding and more."""

import tkinter as tk
from tkinter import messagebox

from petvault.errors import ClinicError
from petvault.ui import theme
from petvault.ui.dialogs.modal import make_modal
from petvault.ui.helpers import add_field, choice_id
from petvault.ui.theme import BG, CARD, MUTED, PRIMARY_H, TEXT
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.pill_button import PillButton


class FormDialog(tk.Toplevel):
    """A small rounded pop-up form.

    fields: a list of dicts {"key", "label", "choices", "strict", "calendar",
    "secret", "value"}, or {"heading": "Section title"}.
    on_submit(dialog) saves the data; it may raise ClinicError (the dialog then
    stays open and shows the message) or return a message for the status bar.
    """

    def __init__(self, app, title, fields, on_submit, submit_text="Save",
                 message="Saved.", hint=None, width=300):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self._on_submit = on_submit
        self._message = message
        self.vars, self.fields = {}, {}

        card = Card(self, parent_bg=BG, pad=20)
        card.pack(padx=18, pady=18)
        tk.Label(card.body, text=title, bg=CARD, fg=TEXT,
                 font=(theme.FONT, 14, "bold")).pack(anchor="w")
        if hint:
            tk.Label(card.body, text=hint, bg=CARD, fg=MUTED, font=(theme.FONT, 9),
                     justify="left", wraplength=width).pack(anchor="w", pady=(2, 0))
        tk.Frame(card.body, bg=CARD, height=10).pack()
        for spec in fields:
            if "heading" in spec:
                tk.Label(card.body, text=spec["heading"], bg=CARD, fg=PRIMARY_H,
                         font=(theme.FONT, 10, "bold")).pack(anchor="w", pady=(4, 6))
                continue
            var, field, _box = add_field(
                card.body, spec["label"], choices=spec.get("choices"),
                strict=spec.get("strict", False), width=width,
                calendar=spec.get("calendar"), secret=spec.get("secret", False))
            var.set(spec.get("value", ""))
            self.vars[spec["key"]] = var
            self.fields[spec["key"]] = field
        buttons = tk.Frame(card.body, bg=CARD)
        buttons.pack(fill="x", pady=(8, 0))
        PillButton(buttons, submit_text, self._save).pack(side="right")
        PillButton(buttons, "Cancel", self.destroy, kind="ghost").pack(
            side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        make_modal(self, app)

    # helpers for on_submit callbacks
    def get(self, key):
        return self.vars[key].get().strip()

    def choice_text(self, key, label):
        """The list item a dropdown field points to (error if unclear)."""
        choice = self.fields[key].resolve()
        if choice is None:
            raise ClinicError(f"Please choose {label} from the list.")
        return choice

    def choice_id(self, key, label):
        return choice_id(self.fields[key], label)

    def _save(self):
        try:
            message = self._on_submit(self)
        except ClinicError as err:
            messagebox.showerror("Cannot save", str(err), parent=self)
            return
        self.app.status.set(message or self._message)
        self.destroy()
        self.app.refresh_all()
