"""Low-level table helpers: filling rows, sizing columns, auto-hiding scrollbars."""

from tkinter import font as tkfont

from petvault.ui import theme


def autohide(bar):
    """Scrollbar callback that hides the bar when everything already fits."""
    def update(first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            bar.grid_remove()
        else:
            bar.grid()
        bar.set(first, last)
    return update


def fit_columns(tree):
    """Make every column as wide as its heading and data need, and share any
    spare room between the columns. If it cannot all fit, a scrollbar appears."""
    spec = getattr(tree, "_spec", None)
    if not spec:
        return
    body = tkfont.Font(family=theme.FONT, size=10)
    head = tkfont.Font(family=theme.FONT, size=10, weight="bold")
    everything = getattr(tree, "_all_values", None)
    items = tree.get_children()
    wanted = []
    for index, (key, heading, _base) in enumerate(spec):
        width = head.measure(heading) + 24
        if everything:
            for values in everything[:500]:
                width = max(width, body.measure(str(values[index])) + 16)
        else:
            for item in items:
                width = max(width, body.measure(str(tree.set(item, key))) + 16)
        wanted.append(max(width, 36))
    total = sum(wanted)
    extra = max(0, (tree.winfo_width() or 0) - total)
    for (key, _heading, _base), width in zip(spec, wanted):
        tree.column(key, width=int(width + extra * width / total),
                    stretch=False)


PAGE_SIZE = 30


def row_values(row, keys):
    values = []
    for key in keys:
        value = key(row) if callable(key) else row[key]
        values.append("" if value is None else value)
    return values


def show_rows(tree, rows, keys, tag_key=None):
    """Put exactly these rows into the table."""
    tree.delete(*tree.get_children())
    for index, row in enumerate(rows):
        iid = str(row["id"]) if "id" in row.keys() else None
        tags = ["odd" if index % 2 else "even"]
        if tag_key:
            tags.append(row[tag_key])
        tree.insert("", "end", iid=iid, values=row_values(row, keys),
                    tags=tuple(tags))
    fit_columns(tree)
