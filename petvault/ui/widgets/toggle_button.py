"""ToggleButton: a small on/off pill (for example Working / Day off)."""

import tkinter as tk

from petvault.ui import theme
from petvault.ui.drawing import round_rect
from petvault.ui.theme import CARD, MINT, ROSE, TEXT


class ToggleButton(tk.Canvas):
    """A small on/off pill, for example 'Working' / 'Day off'."""

    def __init__(self, parent, on_text="Working", off_text="Day off", value=True,
                 parent_bg=CARD, command=None):
        super().__init__(parent, width=100, height=32, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._tg_texts = (on_text, off_text)
        self._tg_on = bool(value)
        self._tg_command = command
        self.bind("<Button-1>", self._flip)
        self._draw()

    def get(self):
        return self._tg_on

    def set(self, value):
        self._tg_on = bool(value)
        self._draw()

    def _flip(self, _event):
        self.set(not self._tg_on)
        if self._tg_command:
            self._tg_command(self._tg_on)

    def _draw(self):
        self.delete("all")
        fill = MINT if self._tg_on else ROSE
        round_rect(self, 1, 1, 99, 31, 16, fill=fill, outline=fill)
        self.create_text(50, 16, text=self._tg_texts[0 if self._tg_on else 1],
                         fill=TEXT, font=(theme.FONT, 9, "bold"))
