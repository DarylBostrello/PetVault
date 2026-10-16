"""Builds tables (with scrollbars and the pager) and fills them with rows."""

import tkinter as tk
from tkinter import ttk

from petvault.ui import theme
from petvault.ui.pager import Pager
from petvault.ui.table_rows import autohide, fit_columns, show_rows
from petvault.ui.theme import BG, CARD, MUTED, TEXT
from petvault.ui.widgets.pill_button import PillButton


def reset_page(tree):
    """Go back to the first page (call when the search, filter or sort changes)."""
    pager = getattr(tree, "_pager", None)
    if pager is not None:
        pager.page = 0


def make_table(parent, columns, height=6, paged=True):
    """columns: list of (key, heading, width). Returns (frame, tree)."""
    frame = tk.Frame(parent, bg=CARD)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns],
                        show="headings", height=height, selectmode="browse")
    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, minwidth=30, anchor="w", stretch=False)
    vbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=autohide(vbar), xscrollcommand=autohide(hbar))
    tree.grid(row=0, column=0, sticky="nsew")
    vbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
    hbar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
    tree._spec = columns
    tree._all_values = None
    tree._pager = None
    if paged:
        bar = tk.Frame(frame, bg=CARD)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        summary, label = tk.StringVar(), tk.StringVar()
        pager = Pager(tree, bar, label, summary)
        tk.Label(bar, textvariable=summary, bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="left")
        PillButton(bar, "Next", lambda: pager.step(1), kind="ghost",
                   small=True).pack(side="right")
        tk.Label(bar, textvariable=label, bg=CARD, fg=TEXT,
                 font=(theme.FONT, 10, "bold")).pack(side="right", padx=10)
        PillButton(bar, "Previous", lambda: pager.step(-1), kind="ghost",
                   small=True).pack(side="right")
        bar.grid_remove()
        tree._pager = pager
    tree.bind("<Configure>", lambda _event: fit_columns(tree))
    tree.tag_configure("odd", background=BG)
    tree.tag_configure("even", background=CARD)
    tree.tag_configure("completed", foreground="#2F8F5B")
    tree.tag_configure("cancelled", foreground="#B0A09A")
    tree.tag_configure("paid", foreground="#2F8F5B")
    tree.tag_configure("void", foreground="#B0A09A")
    return frame, tree


def fill_tree(tree, rows, keys, tag_key=None):
    """keys may be column names or functions that take the row. Tables with a
    pager show PAGE_SIZE rows at a time."""
    pager = getattr(tree, "_pager", None)
    if pager is None:
        show_rows(tree, rows, keys, tag_key)
    else:
        pager.set_rows(list(rows), keys, tag_key)
