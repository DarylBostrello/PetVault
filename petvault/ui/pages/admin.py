"""The Admin screen: staff accounts and backups."""

import os
import sqlite3
import tkinter as tk
from tkinter import messagebox

from petvault.config import ROLE_BY_LABEL, ROLE_LABELS
from petvault.errors import ClinicError
from petvault.files import open_file
from petvault.ui import theme
from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.helpers import add_field, ask_yes, card_title, selected_id
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import BG, CARD, MUTED_DARK
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.pill_button import PillButton


class AdminPage(BasePage):
    title = "Admin"
    subtitle = "Staff accounts and database backups"
    roles = ("admin",)
    KEYS = ["id", "username", "full_name", lambda r: ROLE_LABELS[r["role"]]]

    def build(self):
        form = Card(self)
        form.pack(side="left", fill="y", padx=(0, 16))
        card_title(form.body, "Add user", "Staff sign in with these details.")
        self.full_name, _, _ = add_field(form.body, "Full name")
        self.username, _, _ = add_field(form.body, "Username")
        self.role, _, _ = add_field(form.body, "Role",
                                    choices=list(ROLE_BY_LABEL), strict=True)
        self.password, _, _ = add_field(form.body, "Password (6+ characters)",
                                        secret=True)
        self.confirm, _, _ = add_field(form.body, "Confirm password", secret=True)
        PillButton(form.body, "Add user", self.add).pack(anchor="e")

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        users = Card(right)
        users.pack(fill="both", expand=True)
        card_title(users.body, "Users")
        frame, self.tree = make_table(users.body, [
            ("id", "ID", 40), ("username", "Username", 140),
            ("full_name", "Name", 200), ("role", "Role", 130)])
        frame.pack(fill="both", expand=True)
        buttons = tk.Frame(users.body, bg=CARD)
        buttons.pack(fill="x", pady=(10, 0))
        PillButton(buttons, "Reset password", self.reset_password,
                   kind="ghost").pack(side="left")
        PillButton(buttons, "Delete user", self.delete, kind="danger").pack(
            side="left", padx=8)

        backup = Card(right)
        backup.pack(fill="x", pady=(16, 0))
        card_title(backup.body, "Database backup",
                   "A copy is also saved automatically every time the app is "
                   "closed (the last 10 are kept).")
        self.backup_note = tk.StringVar()
        tk.Label(backup.body, textvariable=self.backup_note, bg=CARD, fg=MUTED_DARK,
                 font=(theme.FONT, 10), justify="left", wraplength=560).pack(
                     anchor="w", pady=(0, 10))
        row = tk.Frame(backup.body, bg=CARD)
        row.pack(fill="x")
        PillButton(row, "Back up now", self.backup_now).pack(side="left")
        PillButton(row, "Open backup folder", self.open_folder,
                   kind="ghost").pack(side="left", padx=8)

    def add(self):
        def action():
            if self.password.get() != self.confirm.get():
                raise ClinicError("The two passwords do not match.")
            role_label = self.role.get().strip()
            if role_label not in ROLE_BY_LABEL:
                raise ClinicError("Please choose a role from the list.")
            self.clinic.create_user(self.username.get(), self.full_name.get(),
                                    ROLE_BY_LABEL[role_label], self.password.get())
            for var in (self.full_name, self.username, self.role, self.password,
                        self.confirm):
                var.set("")
        self.app.commit(action, "User added.")

    def reset_password(self):
        user_id = selected_id(self, self.tree, "a user")
        if user_id is None:
            return
        fields = [{"key": "new", "label": "New password (6+ characters)",
                   "secret": True},
                  {"key": "confirm", "label": "Confirm new password",
                   "secret": True}]

        def submit(dlg):
            if dlg.get("new") != dlg.get("confirm"):
                raise ClinicError("The two passwords do not match.")
            self.clinic.set_password(user_id, dlg.get("new"))
        FormDialog(self.app, "Reset password", fields, submit,
                   message="Password changed.")

    def delete(self):
        user_id = selected_id(self, self.tree, "a user")
        if user_id is None:
            return
        if ask_yes(self, "Delete user", "Delete this account?"):
            self.app.commit(
                lambda: self.clinic.delete_user(user_id, self.app.user["id"]),
                "User deleted.")

    def backup_now(self):
        try:
            path = self.clinic.backup()
        except (OSError, sqlite3.Error) as err:
            messagebox.showerror("Backup", f"The backup failed:\n{err}",
                                 parent=self)
            return
        self.app.status.set("Backup saved.")
        self.refresh()
        messagebox.showinfo("Backup", f"Backup saved to:\n{path}", parent=self)

    def open_folder(self):
        os.makedirs(self.clinic.backup_dir, exist_ok=True)
        if not open_file(self.clinic.backup_dir):
            messagebox.showinfo("Backups", "Backups are saved in:\n"
                                + self.clinic.backup_dir, parent=self)

    def refresh(self):
        fill_tree(self.tree, self.clinic.list_users(), self.KEYS)
        last = self.clinic.last_backup()
        where = f"Backups folder: {self.clinic.backup_dir}"
        if last:
            self.backup_note.set(f"Last backup: {last[1]:%d %b %Y, %H:%M}.\n{where}")
        else:
            self.backup_note.set(f"No backup yet.\n{where}")
