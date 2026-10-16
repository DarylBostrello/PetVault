"""Helpers to place a dialog over the main window and block the window behind it."""

import tkinter as tk


def center_over(window, parent):
    """Place a dialog in the middle of the main window."""
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
    y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
    window.geometry(f"+{x}+{y}")


def make_modal(window, parent):
    """Show a dialog on top of the main window and block the window behind it."""
    window.transient(parent)
    center_over(window, parent)
    window.deiconify()
    try:
        window.wait_visibility()
        window.grab_set()
    except tk.TclError:
        pass  # some window managers refuse the grab; the dialog still works
    window.focus_set()
