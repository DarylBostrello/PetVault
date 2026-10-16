"""CalendarPopup: a month calendar that opens under a date field."""

import calendar as pycal
from datetime import date, timedelta
import tkinter as tk

from petvault.ui import theme
from petvault.ui.theme import (
    BORDER,
    CARD,
    MUTED,
    MUTED_DARK,
    NAV_HOVER,
    PEACH,
    PRIMARY,
    PRIMARY_H,
    TEXT,
)


class CalendarPopup(tk.Toplevel):
    """A small month calendar that opens under a date field."""

    def __init__(self, owner, on_pick):
        super().__init__(owner)
        self.withdraw()
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._on_pick = on_pick
        self._year, self._month = date.today().year, date.today().month
        self._selected = self._lo = self._hi = None
        self._days = []
        outer = tk.Frame(self, bg=BORDER)
        outer.pack()
        body = tk.Frame(outer, bg=CARD)
        body.pack(padx=1, pady=1)

        head = tk.Frame(body, bg=CARD)
        head.pack(fill="x", padx=8, pady=(8, 4))
        for text, step in (("<<", -12), ("<", -1)):
            self._nav(head, text, step).pack(side="left")
        for text, step in ((">>", 12), (">", 1)):
            self._nav(head, text, step).pack(side="right")
        self._title = tk.Label(head, bg=CARD, fg=TEXT, font=(theme.FONT, 10, "bold"))
        self._title.pack(expand=True)

        grid = tk.Frame(body, bg=CARD)
        grid.pack(padx=8)
        for col, name in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            tk.Label(grid, text=name, width=4, bg=CARD, fg=MUTED,
                     font=(theme.FONT, 9)).grid(row=0, column=col)
        self._cells = []
        for row in range(6):
            for col in range(7):
                cell = tk.Label(grid, width=4, bg=CARD, fg=TEXT, font=(theme.FONT, 10),
                                cursor="hand2")
                cell.grid(row=row + 1, column=col, pady=1)
                cell.bind("<Button-1>", lambda _e, r=row, c=col: self._click(r, c))
                cell.bind("<Enter>", lambda _e, r=row, c=col: self._hover(r, c, True))
                cell.bind("<Leave>", lambda _e, r=row, c=col: self._hover(r, c, False))
                self._cells.append(cell)
        today = tk.Label(body, text="Today", bg=CARD, fg=PRIMARY_H, cursor="hand2",
                         font=(theme.FONT, 9, "bold"))
        today.pack(pady=(4, 8))
        today.bind("<Button-1>", lambda _e: self._pick_today())

    def _nav(self, parent, text, step):
        label = tk.Label(parent, text=text, bg=CARD, fg=MUTED_DARK, padx=6,
                         cursor="hand2", font=(theme.FONT, 10, "bold"))
        label.bind("<Button-1>", lambda _e: self._shift(step))
        return label

    def show(self, current, lo, hi, x, y):
        day = current or date.today()
        self._year, self._month = day.year, day.month
        self._selected, self._lo, self._hi = current, lo, hi
        self._render()
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()

    def _shift(self, months):
        index = self._year * 12 + (self._month - 1) + months
        self._year, self._month = index // 12, index % 12 + 1
        self._render()
        return "break"

    def _blocked(self, day):
        return bool((self._lo and day < self._lo) or (self._hi and day > self._hi))

    def _base_bg(self, day):
        if day == self._selected:
            return PRIMARY
        return PEACH if day == date.today() else CARD

    def _render(self):
        self._title.configure(text=f"{pycal.month_name[self._month]} {self._year}")
        weeks = pycal.Calendar(6).monthdatescalendar(self._year, self._month)
        while len(weeks) < 6:
            weeks.append([weeks[-1][-1] + timedelta(days=i + 1) for i in range(7)])
        self._weeks = weeks
        self._days = []
        for r, week in enumerate(weeks):
            row = []
            for c, day in enumerate(week):
                blocked = self._blocked(day)
                fg = BORDER if blocked else (
                    TEXT if day.month == self._month else MUTED)
                self._cells[r * 7 + c].configure(text=str(day.day), fg=fg,
                                                 bg=self._base_bg(day))
                row.append(None if blocked else day)
            self._days.append(row)

    def _hover(self, r, c, inside):
        day = self._weeks[r][c]
        if self._days[r][c] is None:
            return
        self._cells[r * 7 + c].configure(
            bg=NAV_HOVER if inside and day != self._selected else self._base_bg(day))

    def _click(self, r, c):
        day = self._days[r][c]
        if day is not None:
            self._on_pick(day)
        return "break"

    def _pick_today(self):
        today = date.today()
        if not self._blocked(today):
            self._on_pick(today)
        return "break"
