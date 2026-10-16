"""Colours, the shared font name and the ttk theme for tables and scrollbars."""

from tkinter import font as tkfont
from tkinter import ttk


# Soft, pet-friendly palette: cream, peach, mint, sky and rose.
BG = "#FFF8F1"          # page background (cream)
SIDEBAR = "#FFEBDD"     # sidebar (light peach)
NAV_HOVER = "#FFDCC6"
NAV_ACTIVE = "#FFC9A6"
CARD = "#FFFFFF"
FIELD = "#FFF4EA"       # input background
BORDER = "#F0D9C8"
HEADING = "#FFE6D5"     # table header
TEXT = "#4A342D"        # warm dark brown
MUTED = "#8C7068"
MUTED_DARK = "#6F5A52"
PRIMARY, PRIMARY_H = "#F4A070", "#EE8D56"   # soft orange
MINT, MINT_H = "#BFE8D4", "#A7DCC3"
ROSE, ROSE_H = "#F7B8B8", "#F2A0A0"
SAND, SAND_H = "#F3E3D6", "#EBD3C1"
PEACH, SKY, LAVENDER, MINT_BG, PINK = (
    "#FFE0CC", "#DCEBFA", "#E8E0F8", "#D9F2E6", "#FFDDE5")

BUTTON_KINDS = {
    "primary": (PRIMARY, PRIMARY_H),
    "mint": (MINT, MINT_H),
    "danger": (ROSE, ROSE_H),
    "ghost": (SAND, SAND_H),
}

DANGER_TEXT = "#B3392F"
OK_TEXT = "#2F8F5B"
FONT = "TkDefaultFont"  # replaced by the real font family in apply_theme()


def apply_theme(root):
    global FONT
    default = tkfont.nametofont("TkDefaultFont")
    default.configure(size=10)
    FONT = default.actual("family")

    root.configure(bg=BG)
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("Treeview", rowheight=30, background=CARD,
                    fieldbackground=CARD, foreground=TEXT, borderwidth=0,
                    font=(FONT, 10))
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Treeview.Heading", background=HEADING, foreground=TEXT,
                    font=(FONT, 10, "bold"), padding=(10, 8), relief="flat",
                    borderwidth=0)
    style.map("Treeview.Heading", background=[("active", NAV_HOVER)])
    style.map("Treeview", background=[("selected", NAV_ACTIVE)],
              foreground=[("selected", TEXT)])

    for bar in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(bar, background=BORDER, troughcolor=CARD,
                        bordercolor=CARD, lightcolor=BORDER, darkcolor=BORDER,
                        arrowcolor=MUTED, relief="flat")
        style.map(bar, background=[("active", NAV_ACTIVE)])
