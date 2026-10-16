"""The Dashboard screen."""

from datetime import date, timedelta
import tkinter as tk

from petvault.config import APP_NAME, APP_SUBTITLE
from petvault.ui import theme
from petvault.ui.drawing import draw_paw
from petvault.ui.helpers import card_title
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import (
    BG,
    CARD,
    LAVENDER,
    MINT_BG,
    MUTED,
    MUTED_DARK,
    PEACH,
    PINK,
    SKY,
    TEXT,
)
from petvault.ui.widgets.bar_chart import BarChart
from petvault.ui.widgets.card import Card
from petvault.ui.widgets.stat_card import StatCard
from petvault.utils import money


class DashboardPage(BasePage):
    title = "Dashboard"
    subtitle = "Today at a glance"
    KEYS = ["time", "patient", "owner", "vet", "reason", "status"]

    def build(self):
        banner = Card(self, fill=PEACH, border=PEACH, radius=26, pad=20)
        banner.pack(fill="x")
        paw = tk.Canvas(banner.body, width=64, height=64, bg=PEACH,
                        highlightthickness=0, bd=0)
        paw.pack(side="right", padx=(10, 4))
        draw_paw(paw, 0, 0, 64, "#F8BE98")
        tk.Label(banner.body, text=f"Welcome to {APP_NAME}", bg=PEACH, fg=TEXT,
                 font=(theme.FONT, 18, "bold")).pack(anchor="w")
        tk.Label(banner.body, text=APP_SUBTITLE, bg=PEACH, fg=MUTED_DARK,
                 font=(theme.FONT, 10)).pack(anchor="w", pady=(2, 0))

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=14)
        self.cards = {}
        spec = [("patients", "Registered patients", SKY),
                ("today", "Appointments today", LAVENDER),
                ("vets", "Veterinarians", MINT_BG),
                ("balance", "Outstanding balance", PINK)]
        for col, (key, title, color) in enumerate(spec):
            card = StatCard(row, title, color)
            card.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 14, 0))
            row.columnconfigure(col, weight=1, uniform="stat")
            self.cards[key] = card

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="both", expand=True)
        today_card = Card(bottom)
        today_card.pack(side="left", fill="both", expand=True)
        card_title(today_card.body, "Today's appointments")
        frame, self.tree = make_table(today_card.body, [
            ("time", "Time", 60), ("patient", "Patient", 100),
            ("owner", "Owner", 130), ("vet", "Veterinarian", 130),
            ("reason", "Reason", 150), ("status", "Status", 80)], paged=False)
        frame.pack(fill="both", expand=True)
        self.empty_note = tk.Label(today_card.body, text="", bg=CARD, fg=MUTED,
                                   font=(theme.FONT, 10))
        self.empty_note.pack(anchor="w", pady=(6, 0))

        chart_card = Card(bottom)
        chart_card.pack(side="left", fill="y", padx=(16, 0))
        card_title(chart_card.body, "Appointments per week",
                   "Week starting on Monday, cancelled not counted")
        self.chart = BarChart(chart_card.body)
        self.chart.configure(width=330)
        self.chart.pack(fill="both", expand=True)

    def refresh(self):
        stats = self.clinic.stats()
        self.cards["patients"].value.set(str(stats["patients"]))
        self.cards["today"].value.set(str(stats["today"]))
        self.cards["vets"].value.set(str(stats["vets"]))
        self.cards["balance"].value.set(money(stats["outstanding_cents"]))
        rows = self.clinic.todays_appointments()
        fill_tree(self.tree, rows, self.KEYS, tag_key="status")
        self.empty_note.configure(
            text="" if rows else "No appointments today.")
        this_monday = date.today() - timedelta(days=date.today().weekday())
        self.chart.set_data([(f"{d:%b} {d.day}", n, d == this_monday)
                             for d, n in self.clinic.weekly_counts()])
