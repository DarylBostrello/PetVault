"""LoginView: the sign-in screen (and first-run administrator setup)."""

import tkinter as tk

from petvault.config import APP_NAME, APP_SUBTITLE
from petvault.demo import DEMO_USERS
from petvault.errors import ClinicError
from petvault.ui import theme
from petvault.ui.drawing import draw_paw
from petvault.ui.helpers import add_field
from petvault.ui.theme import BG, CARD, DANGER_TEXT, MUTED, PRIMARY, TEXT
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.pill_button import PillButton


class LoginView(tk.Frame):
    """The first screen: sign in, or create the first administrator account."""

    def __init__(self, app):
        super().__init__(app, bg=BG)
        self.app = app
        self.first_run = app.clinic.user_count() == 0
        card = Card(self, parent_bg=BG, radius=28, pad=30)
        card.place(relx=0.5, rely=0.5, anchor="center")
        logo = tk.Canvas(card.body, width=56, height=56, bg=CARD,
                         highlightthickness=0, bd=0)
        logo.pack()
        draw_paw(logo, 0, 0, 56, PRIMARY)
        tk.Label(card.body, text=APP_NAME, bg=CARD, fg=TEXT,
                 font=(theme.FONT, 24, "bold")).pack(pady=(6, 0))
        tk.Label(card.body, text=APP_SUBTITLE, bg=CARD, fg=MUTED, font=(theme.FONT, 10),
                 wraplength=300, justify="center").pack(pady=(0, 16))
        if self.first_run:
            tk.Label(card.body, text="Welcome! Create the first administrator "
                     "account.", bg=CARD, fg=TEXT, font=(theme.FONT, 10, "bold"),
                     wraplength=300).pack(pady=(0, 10))
            self.full_name, _, _ = add_field(card.body, "Full name", width=300)
        self.username, self.username_box, _ = add_field(card.body, "Username",
                                                        width=300)
        self.password, self.password_box, _ = add_field(
            card.body, "Password", width=300, secret=True)
        self.confirm = None
        if self.first_run:
            self.confirm, self.confirm_box, _ = add_field(
                card.body, "Confirm password", width=300, secret=True)
        last = self.confirm_box if self.first_run else self.password_box
        last.widget.bind("<Return>", lambda _e: self.submit())
        self.message = tk.StringVar()
        tk.Label(card.body, textvariable=self.message, bg=CARD, fg=DANGER_TEXT,
                 font=(theme.FONT, 9), wraplength=300).pack(pady=(0, 6))
        PillButton(card.body, "Create account" if self.first_run else "Sign in",
                   self.submit).pack(fill="x")
        if app.demo and not self.first_run:
            working = [f"{u} / {p}" for u, _n, _r, p in DEMO_USERS
                       if app.clinic.authenticate(u, p)]
            if working:
                tk.Label(card.body, text="Demo logins:\n" + "\n".join(working),
                         bg=CARD, fg=MUTED, font=(theme.FONT, 9),
                         justify="left").pack(pady=(14, 0))
        self.after(150, lambda: self.username_box.widget.focus_set())

    def submit(self):
        clinic = self.app.clinic
        try:
            if self.first_run:
                if self.password.get() != self.confirm.get():
                    raise ClinicError("The two passwords do not match.")
                clinic.create_user(self.username.get(), self.full_name.get(),
                                   "admin", self.password.get())
            user = clinic.authenticate(self.username.get(), self.password.get())
            if user is None:
                raise ClinicError("Wrong username or password.")
        except ClinicError as err:
            self.message.set(str(err))
            return
        self.app.start_session(user)
