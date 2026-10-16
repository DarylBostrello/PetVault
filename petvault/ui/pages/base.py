"""BasePage: what every screen has in common."""

import tkinter as tk

from petvault.config import ROLES
from petvault.ui.helpers import card_title
from petvault.ui.tables import reset_page
from petvault.ui.theme import BG
from petvault.ui.widgets.card import Card


class BasePage(tk.Frame):
    title = ""
    subtitle = ""
    roles = ROLES

    def __init__(self, app, parent):
        super().__init__(parent, bg=BG)
        self.app = app
        self.clinic = app.clinic
        self.build()

    def side_layout(self, form_title, hint=None, with_form=True):
        """Form card on the left (optional), content card on the right."""
        form = None
        if with_form:
            form = Card(self)
            form.pack(side="left", fill="y", padx=(0, 16))
            card_title(form.body, form_title, hint)
        right = Card(self)
        right.pack(side="left", fill="both", expand=True)
        return form, right

    def preselect_patient(self, patient_id):
        """Called when another screen sends the user here for one patient."""

    def view_changed(self):
        """The search, filter or sort changed: start again from the first page."""
        reset_page(self.tree)
        self.refresh_list()

    def build(self):
        raise NotImplementedError

    def refresh(self):
        raise NotImplementedError
