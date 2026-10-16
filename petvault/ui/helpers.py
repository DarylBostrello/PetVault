"""Small helpers shared by the screens: card titles, labelled fields, selection and prompts."""

import tkinter as tk
from tkinter import messagebox

from petvault.errors import ClinicError
from petvault.files import open_file
from petvault.ui import theme
from petvault.ui.theme import CARD, MUTED, TEXT
from petvault.ui.widgets.rounded_field import RoundedField


def card_title(parent, text, hint=None, bg=CARD):
    tk.Label(parent, text=text, bg=bg, fg=TEXT,
             font=(theme.FONT, 13, "bold")).pack(anchor="w")
    if hint:
        tk.Label(parent, text=hint, bg=bg, fg=MUTED,
                 font=(theme.FONT, 9)).pack(anchor="w")
    tk.Frame(parent, bg=bg, height=10).pack()


def add_field(parent, label, choices=None, strict=False, width=220, pack=True,
              on_pick=None, calendar=None, secret=False):
    """Label above a rounded field. Returns (variable, field, container).
    Pass choices for a searchable dropdown, calendar=(min, max) for a date
    picker, secret=True for a password box."""
    box = tk.Frame(parent, bg=CARD)
    tk.Label(box, text=label, bg=CARD, fg=MUTED,
             font=(theme.FONT, 9)).pack(anchor="w", pady=(0, 3))
    var = tk.StringVar()
    field = RoundedField(box, var, choices=choices, strict=strict, width=width,
                         on_pick=on_pick, calendar=calendar, secret=secret)
    field.pack(fill="x")
    if pack:
        box.pack(fill="x", pady=(0, 10))
    return var, field, box


def choice_id(field, label):
    """The id at the start of the choice a dropdown field points to,
    e.g. '12 - Buddy (Maria Santos)' gives 12."""
    choice = field.resolve()
    if choice is None:
        raise ClinicError(f"Please choose a {label} from the list.")
    return int(choice.split(" - ", 1)[0])


def selected_id(page, tree, what):
    """The id of the highlighted table row, or None (with a friendly message)."""
    selected = tree.selection()
    if not selected:
        messagebox.showinfo(f"Select {what}",
                            f"Select {what} in the table first.", parent=page)
        return None
    return int(selected[0])


def ask_yes(page, title, text):
    return messagebox.askyesno(title, text, parent=page)


def offer_open(page, path):
    if messagebox.askyesno("Saved", f"Saved to:\n{path}\n\nOpen it now?",
                           parent=page):
        if not open_file(path):
            messagebox.showinfo("Open file", "Could not open the file "
                                "automatically. You can find it at:\n" + path,
                                parent=page)
