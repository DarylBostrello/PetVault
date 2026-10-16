"""The Pager class: shows 10 table rows at a time with Previous / Next."""

from petvault.ui.table_rows import PAGE_SIZE, row_values, show_rows


class Pager:
    """Shows PAGE_SIZE rows of a table at a time, with Previous / Next buttons."""

    def __init__(self, tree, bar, label, summary):
        self.tree, self.bar, self.label, self.summary = tree, bar, label, summary
        self.rows, self.keys, self.tag_key = [], [], None
        self.page = 0

    def pages(self):
        return max(1, -(-len(self.rows) // PAGE_SIZE))

    def set_rows(self, rows, keys, tag_key):
        self.rows, self.keys, self.tag_key = rows, keys, tag_key
        self.tree._all_values = [row_values(r, keys) for r in rows]
        self.show()

    def show(self):
        self.page = max(0, min(self.page, self.pages() - 1))
        start = self.page * PAGE_SIZE
        show_rows(self.tree, self.rows[start:start + PAGE_SIZE], self.keys,
                  self.tag_key)
        total = len(self.rows)
        self.label.set(f"Page {self.page + 1} of {self.pages()}")
        self.summary.set(f"Showing {start + 1 if total else 0}-"
                         f"{min(start + PAGE_SIZE, total)} of {total}")
        if total > PAGE_SIZE:
            self.bar.grid()
        else:
            self.bar.grid_remove()

    def step(self, delta):
        self.page += delta
        self.show()
