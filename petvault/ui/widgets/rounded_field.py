"""RoundedField: a rounded text box that can also be a searchable dropdown or a date picker."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from petvault.errors import ClinicError
from petvault.ui import theme
from petvault.ui.drawing import round_rect
from petvault.ui.theme import (
    BORDER,
    CARD,
    FIELD,
    MUTED_DARK,
    NAV_ACTIVE,
    PRIMARY,
    TEXT,
)
from petvault.ui.widgets.calendar_popup import CalendarPopup
from petvault.utils import parse_date


class RoundedField(tk.Frame):
    """A rounded text box.

    * choices: it becomes a searchable dropdown. Type to narrow the list down,
      use Up/Down and Enter, or click an item. With strict=True the text must
      end up matching one of the choices (see resolve()); otherwise the choices
      are only suggestions and any text is allowed.
    * calendar=(earliest, latest): it gets a date picker (either may be None).
    * secret=True: the text is hidden (passwords).
    """

    HEIGHT = 38

    def __init__(self, parent, variable, choices=None, strict=False, width=240,
                 parent_bg=CARD, on_pick=None, calendar=None, secret=False):
        super().__init__(parent, bg=parent_bg, width=width, height=self.HEIGHT)
        self._variable = variable
        self._choices = None if choices is None else list(choices)
        self._calendar = calendar
        self._strict = strict
        self._on_pick = on_pick
        self._focused = False
        self._shown = False
        self._typing = False
        self._popup = self._listbox = self._scrollbar = self._cal = None
        self._size = (0, 0)

        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._canvas.bind("<Configure>", self._redraw)

        has_arrow = self._choices is not None or self._calendar is not None
        right = 38 if has_arrow else 14
        self.widget = tk.Entry(self, textvariable=variable, relief="flat",
                               bd=0, highlightthickness=0, bg=FIELD, fg=TEXT,
                               insertbackground=TEXT, font=(theme.FONT, 10),
                               show="\u2022" if secret else "")
        self.widget.place(x=14, y=7, relwidth=1, width=-(14 + right), height=24)
        self.widget.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.widget.bind("<FocusOut>", self._on_focus_out, add="+")

        if has_arrow:
            self._canvas.bind("<Button-1>", self._toggle)
            self.widget.bind("<Escape>", self._escape)
            # clicking anywhere else in the window closes the open list/calendar
            self.winfo_toplevel().bind("<Button-1>", self._outside_click, add="+")
        if self._choices is not None:
            self.widget.bind("<Button-1>",
                             lambda _e: self.after_idle(self._open, True),
                             add="+")
            self.widget.bind("<KeyPress>", self._key_pressed, add="+")
            variable.trace_add("write", self._text_changed)
            self.widget.bind("<Down>", self._down)
            self.widget.bind("<Up>", self._up)
            self.widget.bind("<Return>", self._enter)

    # -- public ----------------------------------------------------------------
    def set_choices(self, choices):
        self._choices = list(choices)

    def resolve(self):
        """The choice the text stands for: an exact match, or the only choice
        that contains the typed text. None when there is no clear match."""
        text = self._variable.get().strip().lower()
        if not text or not self._choices:
            return None
        for choice in self._choices:
            if choice.lower() == text:
                return choice
        hits = [c for c in self._choices if text in c.lower()]
        return hits[0] if len(hits) == 1 else None

    # -- drawing -----------------------------------------------------------------
    def _set_focus(self, value):
        self._focused = value
        self._draw()

    def _redraw(self, event):
        self._size = (event.width, event.height)
        self._draw()

    def _draw(self):
        width, height = self._size
        if not width:
            return
        self._canvas.delete("all")
        round_rect(self._canvas, 1, 1, width - 2, height - 2, 14, fill=FIELD,
                   outline=PRIMARY if self._focused else BORDER,
                   width=2 if self._focused else 1)
        if self._calendar is not None:  # small calendar icon
            x, y = width - 32, height / 2 - 8
            c = self._canvas
            c.create_rectangle(x, y + 3, x + 16, y + 16, outline=MUTED_DARK, width=2)
            c.create_rectangle(x, y + 3, x + 16, y + 7, fill=MUTED_DARK,
                               outline=MUTED_DARK)
            c.create_line(x + 4, y, x + 4, y + 5, fill=MUTED_DARK, width=2)
            c.create_line(x + 12, y, x + 12, y + 5, fill=MUTED_DARK, width=2)
        elif self._choices is not None:  # small arrow showing it is a dropdown
            x, y = width - 22, height / 2
            self._canvas.create_polygon(x - 5, y - 2, x + 5, y - 2, x, y + 4,
                                        fill=MUTED_DARK, outline=MUTED_DARK)

    # -- the dropdown list --------------------------------------------------------
    def _matches(self, show_all=False):
        text = self._variable.get().strip().lower()
        if show_all or not text or any(c.lower() == text for c in self._choices):
            return list(self._choices)
        return [c for c in self._choices if text in c.lower()]

    def _build_popup(self):
        popup = tk.Toplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)
        try:
            popup.attributes("-topmost", True)
        except tk.TclError:
            pass
        border = tk.Frame(popup, bg=BORDER)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._scrollbar = ttk.Scrollbar(inner, orient="vertical")
        box = tk.Listbox(inner, activestyle="none", exportselection=False,
                         relief="flat", bd=0, highlightthickness=0, bg=CARD,
                         fg=TEXT, selectbackground=NAV_ACTIVE,
                         selectforeground=TEXT, font=(theme.FONT, 10),
                         yscrollcommand=self._scrollbar.set)
        self._scrollbar.configure(command=box.yview)
        box.pack(side="left", fill="both", expand=True)
        box.bind("<ButtonPress-1>", self._click_item)
        box.bind("<Motion>", self._hover)
        self._popup, self._listbox = popup, box

    def _open(self, show_all=False):
        if not self._choices:
            return
        items = self._matches(show_all)
        if not items:
            self._close()
            return
        if self._popup is None:
            self._build_popup()
        if self._cal is not None:
            self._cal.withdraw()
        box = self._listbox
        box.delete(0, "end")
        for item in items:
            box.insert("end", item)

        rows = min(len(items), 8)
        measure = tkfont.Font(family=theme.FONT, size=10)
        digit = max(measure.measure("0"), 1)
        need = max(measure.measure(item) for item in items) + 28
        box.configure(height=rows,
                      width=max(int(need / digit) + 1,
                                int(self.winfo_width() / digit)))
        if len(items) > rows:
            self._scrollbar.pack(side="right", fill="y", before=box)
        else:
            self._scrollbar.pack_forget()

        text = self._variable.get().strip().lower()
        index = next((i for i, item in enumerate(items) if item.lower() == text),
                     0 if text and not show_all else None)
        if index is not None:
            self._highlight(index)

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        self._popup.geometry(f"+{x}+{y}")
        self._popup.deiconify()
        self._popup.lift()
        self._shown = True

    def _open_calendar(self):
        if self._popup is not None:
            self._popup.withdraw()
        if self._cal is None:
            self._cal = CalendarPopup(self, self._pick_date)
        try:
            current = parse_date(self._variable.get())
        except ClinicError:
            current = None
        low, high = self._calendar
        self._cal.show(current, low, high, self.winfo_rootx(),
                       self.winfo_rooty() + self.winfo_height() + 2)
        self._shown = True

    def _pick_date(self, day):
        self._variable.set(day.isoformat())
        self._close()
        self.widget.focus_set()
        self.widget.icursor("end")
        if self._on_pick:
            self._on_pick(day.isoformat())

    def _close(self):
        if self._popup is not None:
            self._popup.withdraw()
        if self._cal is not None:
            self._cal.withdraw()
        self._shown = False

    def _highlight(self, index):
        box = self._listbox
        box.selection_clear(0, "end")
        box.selection_set(index)
        box.activate(index)
        box.see(index)

    def _move(self, step):
        size = self._listbox.size()
        current = self._listbox.curselection()
        if current:
            index = (current[0] + step) % size
        else:
            index = 0 if step > 0 else size - 1
        self._highlight(index)

    def _pick(self, text):
        self._variable.set(text)
        self._close()
        self.widget.icursor("end")
        self.widget.focus_set()
        if self._on_pick:
            self._on_pick(text)

    def _commit(self):
        """On leaving a strict field, turn partly typed text into the one
        choice it matches (for example 'bud' becomes '1 - Buddy (Maria)')."""
        if not self._strict or not self._choices:
            return
        choice = self.resolve()
        if choice is not None:
            if choice != self._variable.get():
                self._variable.set(choice)
            if self._on_pick:
                self._on_pick(choice)

    # -- events --------------------------------------------------------------------
    def _toggle(self, _event):
        if self._shown:
            self._close()
            return
        self.widget.focus_set()
        if self._calendar is not None:
            self._open_calendar()
        elif self._choices is not None:
            self._open(show_all=True)

    def _key_pressed(self, _event):
        # Remember that the text is being edited by hand, not set by the program.
        self._typing = True
        self.after(80, self._clear_typing)

    def _clear_typing(self):
        self._typing = False

    def _text_changed(self, *_args):
        """Search as you type: refresh the list whenever the text changes."""
        if self._typing and self._choices:
            self._open()

    def _down(self, _event):
        if self._shown:
            self._move(1)
        else:
            self._open(show_all=True)
        return "break"

    def _up(self, _event):
        if self._shown:
            self._move(-1)
        return "break"

    def _enter(self, _event):
        if self._shown:
            selected = self._listbox.curselection()
            if selected:
                self._pick(self._listbox.get(selected[0]))
                return "break"
            self._close()
        self._commit()
        return "break"

    def _escape(self, _event):
        if self._shown:
            self._close()
            return "break"

    def _click_item(self, event):
        index = self._listbox.nearest(event.y)
        self._pick(self._listbox.get(index))
        return "break"  # stops Tk from moving the keyboard focus to the list

    def _hover(self, event):
        self._highlight(self._listbox.nearest(event.y))

    def _outside_click(self, event):
        if not self._shown:
            return
        clicked = str(event.widget)
        inside = [str(self.widget), str(self._canvas)]
        inside += [str(w) for w in (self._popup, self._cal) if w is not None]
        if clicked in inside[:2] or any(clicked.startswith(p) for p in inside[2:]):
            return
        self._close()

    def _on_focus_out(self, _event):
        self._set_focus(False)
        if self._choices is not None or self._calendar is not None:
            self.after(120, self._finish_edit)

    def _finish_edit(self):
        try:
            try:
                focused = self.focus_get()
            except KeyError:
                focused = None
            if focused is self.widget:
                return
            self._close()
            self._commit()
        except tk.TclError:
            pass  # the field was closed or destroyed in the meantime
