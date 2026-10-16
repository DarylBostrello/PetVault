"""NavButton: a sidebar menu item shaped like a pill."""

import tkinter as tk

from petvault.ui import theme
from petvault.ui.drawing import round_rect
from petvault.ui.theme import NAV_ACTIVE, NAV_HOVER, SIDEBAR, TEXT


class NavButton(tk.Canvas):
    """A sidebar menu item shaped like a pill."""

    def __init__(self, parent, text, command):
        super().__init__(parent, width=10, height=42, bg=SIDEBAR,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._nav_text, self._nav_command = text, command
        self._nav_active = self._nav_hover = False
        self._nav_width = 0
        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self._nav_command())

    def _on_resize(self, event):
        self._nav_width = event.width
        self._draw()

    def _set_hover(self, value):
        self._nav_hover = value
        self._draw()

    def set_active(self, value):
        self._nav_active = value
        self._draw()

    def _draw(self):
        if not self._nav_width:
            return
        self.delete("all")
        if self._nav_active:
            fill = NAV_ACTIVE
        elif self._nav_hover:
            fill = NAV_HOVER
        else:
            fill = SIDEBAR
        round_rect(self, 2, 2, self._nav_width - 2, 40, 16, fill=fill,
                   outline=fill)
        self.create_text(20, 21, text=self._nav_text, anchor="w", fill=TEXT,
                         font=(theme.FONT, 11, "bold" if self._nav_active else "normal"))
