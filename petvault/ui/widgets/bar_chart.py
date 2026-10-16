"""BarChart: the simple bar chart on the dashboard."""

import tkinter as tk

from petvault.ui import theme
from petvault.ui.drawing import round_rect
from petvault.ui.theme import (
    BORDER,
    CARD,
    MUTED,
    MUTED_DARK,
    NAV_ACTIVE,
    PRIMARY,
    TEXT,
)


class BarChart(tk.Canvas):
    """A simple bar chart. set_data([(label, value, highlighted), ...])."""

    def __init__(self, parent, bg=CARD):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, height=180)
        self._chart_data = []
        self.bind("<Configure>", lambda _e: self._draw())

    def set_data(self, data):
        self._chart_data = list(data)
        self._draw()

    def _draw(self):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 60 or height < 80 or not self._chart_data:
            return
        self.delete("all")
        left, right, top, bottom = 8, 8, 24, 28
        slot = (width - left - right) / len(self._chart_data)
        bar = min(slot * 0.62, 38)
        peak = max(1, max(value for _label, value, _flag in self._chart_data))
        base = height - bottom
        self.create_line(left, base, width - right, base, fill=BORDER)
        for i, (label, value, current) in enumerate(self._chart_data):
            cx = left + slot * (i + 0.5)
            bar_h = (base - top) * value / peak
            color = PRIMARY if current else NAV_ACTIVE
            if value > 0:
                round_rect(self, cx - bar / 2, base - bar_h, cx + bar / 2, base,
                           8, fill=color, outline=color)
            self.create_text(cx, base - bar_h - 9, text=str(value), fill=TEXT,
                             font=(theme.FONT, 9, "bold"))
            self.create_text(cx, base + 14, text=label,
                             fill=MUTED_DARK if current else MUTED,
                             font=(theme.FONT, 8))
