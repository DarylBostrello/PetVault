"""PillButton: a rounded button with hover and press feedback."""

import tkinter as tk
from tkinter import font as tkfont

from petvault.ui import theme
from petvault.ui.drawing import round_rect
from petvault.ui.theme import BUTTON_KINDS, CARD, TEXT


class PillButton(tk.Canvas):
    """A rounded button with hover and press feedback."""

    def __init__(self, parent, text, command, kind="primary", parent_bg=CARD,
                 small=False):
        label_font = tkfont.Font(family=theme.FONT, size=10, weight="bold")
        pad_x, pad_y = (28, 12) if small else (40, 18)
        width = label_font.measure(text) + pad_x
        height = label_font.metrics("linespace") + pad_y
        super().__init__(parent, width=width, height=height, bg=parent_bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._btn_fill, self._btn_hover = BUTTON_KINDS[kind]
        self._btn_command = command
        self._btn_size = (width, height)
        self._btn_shape = round_rect(self, 1, 1, width - 1, height - 1, 16,
                                     fill=self._btn_fill, outline=self._btn_fill)
        self._btn_text = self.create_text(width / 2, height / 2, text=text,
                                          fill=TEXT, font=(theme.FONT, 10, "bold"))
        self.bind("<Enter>", lambda _e: self._paint(self._btn_hover))
        self.bind("<Leave>", lambda _e: self._paint(self._btn_fill))
        self.bind("<ButtonPress-1>", lambda _e: self._paint(self._btn_hover))
        self.bind("<ButtonRelease-1>", self._release)

    def set_text(self, text):
        self.itemconfigure(self._btn_text, text=text)

    def set_kind(self, kind):
        """Change the colour (used by tab-like button rows)."""
        self._btn_fill, self._btn_hover = BUTTON_KINDS[kind]
        self._paint(self._btn_fill)

    def _paint(self, color):
        self.itemconfigure(self._btn_shape, fill=color, outline=color)

    def _release(self, event):
        width, height = self._btn_size
        inside = 0 <= event.x < width and 0 <= event.y < height
        self._paint(self._btn_hover if inside else self._btn_fill)
        if inside:
            self._btn_command()
