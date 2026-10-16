"""Card: a rounded panel."""

import tkinter as tk

from petvault.ui.drawing import round_rect
from petvault.ui.theme import BG, BORDER, CARD


class Card(tk.Frame):
    """A rounded panel. Put content in card.body."""

    def __init__(self, parent, fill=CARD, border=BORDER, radius=20, pad=18,
                 parent_bg=BG):
        super().__init__(parent, bg=parent_bg)
        self._fill, self._border, self._radius = fill, border, radius
        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._canvas.bind("<Configure>", self._redraw)

    def _redraw(self, event):
        self._canvas.delete("all")
        round_rect(self._canvas, 1, 1, event.width - 2, event.height - 2,
                   self._radius, fill=self._fill, outline=self._border)
