"""StatCard: a pastel summary tile."""

import tkinter as tk

from petvault.ui import theme
from petvault.ui.theme import BG, MUTED_DARK, TEXT
from petvault.ui.widgets.card import Card


class StatCard(Card):
    """A pastel summary tile."""

    def __init__(self, parent, title, fill, parent_bg=BG, compact=False):
        super().__init__(parent, fill=fill, border=fill, radius=22,
                         pad=14 if compact else 18, parent_bg=parent_bg)
        self.value = tk.StringVar(value="0")
        tk.Label(self.body, textvariable=self.value, bg=fill, fg=TEXT,
                 font=(theme.FONT, 20 if compact else 26, "bold")).pack(anchor="w")
        tk.Label(self.body, text=title, bg=fill, fg=MUTED_DARK,
                 font=(theme.FONT, 10)).pack(anchor="w")
