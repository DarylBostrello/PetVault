"""VetApp: the main window, sidebar and navigation, plus the program's main() entry point."""

import argparse
import sqlite3
from datetime import date
import tkinter as tk
from tkinter import messagebox

from petvault.config import (
    APP_NAME,
    APP_SUBTITLE,
    DB_FILE,
    PERMISSIONS,
    ROLE_LABELS,
)
from petvault.database import Clinic
from petvault.demo import load_demo_data
from petvault.errors import ClinicError
from petvault.ui import theme
from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.drawing import draw_paw
from petvault.ui.helpers import ask_yes
from petvault.ui.icon import set_window_icon
from petvault.ui.login import LoginView
from petvault.ui.page_registry import PAGE_CLASSES
from petvault.ui.theme import BG, MUTED, PRIMARY, SIDEBAR, TEXT, apply_theme
from petvault.ui.widgets.nav_button import NavButton
from petvault.ui.widgets.pill_button import PillButton


class VetApp(tk.Tk):
    def __init__(self, clinic, demo=False):
        super().__init__()
        self.clinic = clinic
        self.demo = demo
        self.user = None
        self.title(f"{APP_NAME}: {APP_SUBTITLE}")
        set_window_icon(self)
        self.minsize(1100, 660)
        self.center(1240, 780)
        apply_theme(self)

        self.status = tk.StringVar(value=f"Welcome to {APP_NAME}.")
        self.page_title = tk.StringVar()
        self.page_sub = tk.StringVar()
        self.nav, self.pages = {}, {}
        self.shell = self.login = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_login()

    def center(self, width, height):
        width = min(width, self.winfo_screenwidth() - 40)
        height = min(height, self.winfo_screenheight() - 90)
        x = (self.winfo_screenwidth() - width) // 2
        y = max((self.winfo_screenheight() - height) // 2 - 20, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # -- sign in / out ---------------------------------------------------------------
    def show_login(self):
        if self.shell is not None:
            self.shell.destroy()
            self.shell = None
        self.user = None
        self.nav, self.pages = {}, {}
        self.login = LoginView(self)
        self.login.pack(fill="both", expand=True)

    def start_session(self, user):
        self.user = dict(user)
        if self.login is not None:
            self.login.destroy()
            self.login = None
        self.status.set(f"Signed in as {self.user['full_name']}.")
        self.shell = tk.Frame(self, bg=BG)
        self.shell.pack(fill="both", expand=True)
        self.build_sidebar(self.shell)
        self.build_content(self.shell)
        self.refresh_all()
        self.show_page("Dashboard")

    def logout(self):
        if ask_yes(self, "Log out", "Log out of PetVault?"):
            self.show_login()

    def change_password(self):
        fields = [{"key": "old", "label": "Current password", "secret": True},
                  {"key": "new", "label": "New password (6+ characters)",
                   "secret": True},
                  {"key": "confirm", "label": "Confirm new password",
                   "secret": True}]

        def submit(dlg):
            if dlg.get("new") != dlg.get("confirm"):
                raise ClinicError("The two new passwords do not match.")
            self.clinic.change_password(self.user["id"], dlg.get("old"),
                                        dlg.get("new"))
        FormDialog(self, "Change password", fields, submit,
                   message="Your password was changed.")

    def can(self, action):
        return (self.user is not None
                and self.user["role"] in PERMISSIONS.get(action, ()))

    def allowed_pages(self):
        return [c for c in PAGE_CLASSES if self.user["role"] in c.roles]

    # -- layout ----------------------------------------------------------------------------
    def build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=SIDEBAR, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", padx=20, pady=(26, 22))
        logo = tk.Canvas(brand, width=46, height=46, bg=SIDEBAR,
                         highlightthickness=0, bd=0)
        logo.pack(side="left")
        draw_paw(logo, 0, 0, 46, PRIMARY)
        names = tk.Frame(brand, bg=SIDEBAR)
        names.pack(side="left", padx=12)
        tk.Label(names, text=APP_NAME, bg=SIDEBAR, fg=TEXT,
                 font=(theme.FONT, 17, "bold")).pack(anchor="w")
        tk.Label(names, text="Veterinary Clinic", bg=SIDEBAR, fg=MUTED,
                 font=(theme.FONT, 9)).pack(anchor="w")

        # the signed-in user sits at the bottom (packed first to keep its space)
        user_box = tk.Frame(sidebar, bg=SIDEBAR)
        user_box.pack(side="bottom", fill="x", padx=18, pady=16)
        tk.Label(user_box, text=self.user["full_name"], bg=SIDEBAR, fg=TEXT,
                 font=(theme.FONT, 10, "bold"), wraplength=170,
                 justify="left").pack(anchor="w")
        tk.Label(user_box, text=ROLE_LABELS[self.user["role"]], bg=SIDEBAR,
                 fg=MUTED, font=(theme.FONT, 9)).pack(anchor="w", pady=(0, 8))
        PillButton(user_box, "Change password", self.change_password,
                   kind="ghost", parent_bg=SIDEBAR, small=True).pack(
                       anchor="w", pady=(0, 6))
        PillButton(user_box, "Log out", self.logout, kind="ghost",
                   parent_bg=SIDEBAR, small=True).pack(anchor="w")

        for page_class in self.allowed_pages():
            button = NavButton(
                sidebar, page_class.title,
                lambda name=page_class.title: self.show_page(name))
            button.pack(fill="x", padx=14, pady=3)
            self.nav[page_class.title] = button

    def build_content(self, parent):
        content = tk.Frame(parent, bg=BG)
        content.pack(side="left", fill="both", expand=True)

        top = tk.Frame(content, bg=BG)
        top.pack(fill="x", padx=28, pady=(22, 12))
        heading = tk.Frame(top, bg=BG)
        heading.pack(side="left")
        tk.Label(heading, textvariable=self.page_title, bg=BG, fg=TEXT,
                 font=(theme.FONT, 20, "bold")).pack(anchor="w")
        tk.Label(heading, textvariable=self.page_sub, bg=BG, fg=MUTED,
                 font=(theme.FONT, 10)).pack(anchor="w")
        tk.Label(top, text=date.today().strftime("%A, %d %B %Y"), bg=BG,
                 fg=MUTED, font=(theme.FONT, 10)).pack(side="right")

        tk.Label(content, textvariable=self.status, bg=BG, fg=MUTED,
                 anchor="w", font=(theme.FONT, 9)).pack(side="bottom", fill="x",
                                                  padx=28, pady=(0, 12))

        holder = tk.Frame(content, bg=BG)
        holder.pack(fill="both", expand=True, padx=28, pady=(0, 8))
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        for page_class in self.allowed_pages():
            page = page_class(self, holder)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[page_class.title] = page

    def show_page(self, name):
        page = self.pages[name]
        page.refresh()
        page.tkraise()
        self.page_title.set(page.title)
        self.page_sub.set(page.subtitle)
        for title, button in self.nav.items():
            button.set_active(title == name)

    def go_to(self, name, patient_id=None):
        """Open a screen, optionally with one patient already chosen."""
        if name not in self.pages:
            return
        self.show_page(name)
        if patient_id is not None:
            self.pages[name].preselect_patient(patient_id)

    # -- shared data for dropdowns ------------------------------------------------------------
    def patient_choices(self):
        return [f"{r['id']} - {r['name']} ({r['owner_name']})"
                for r in self.clinic.search_patients("")]

    def patient_text(self, patient_id):
        return next((c for c in self.patient_choices()
                     if c.startswith(f"{patient_id} - ")), "")

    def vet_choices(self):
        return [f"{r['id']} - {r['name']}" for r in self.clinic.list_vets()]

    # -- actions -----------------------------------------------------------------------------------
    def commit(self, action, message):
        """Run a database action, report errors in a dialog, refresh on success."""
        try:
            action()
        except ClinicError as err:
            messagebox.showerror("Cannot complete action", str(err),
                                 parent=self)
            return False
        self.status.set(message)
        self.refresh_all()
        return True

    def refresh_all(self):
        for page in self.pages.values():
            page.refresh()

    def on_close(self):
        try:
            self.clinic.backup()  # automatic backup every time the app closes
        except (OSError, sqlite3.Error):
            pass
        self.clinic.close()
        self.destroy()


def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME}: {APP_SUBTITLE}")
    parser.add_argument("--db", default=DB_FILE, help="SQLite database file")
    parser.add_argument("--demo", action="store_true",
                        help="load sample data and demo logins")
    args = parser.parse_args()

    clinic = Clinic(args.db)
    if args.demo:
        load_demo_data(clinic)
    VetApp(clinic, demo=args.demo).mainloop()
