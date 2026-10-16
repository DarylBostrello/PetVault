"""The Billing screen."""

import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox

from petvault.config import CURRENCY, PAYMENT_METHODS
from petvault.files import receipt_lines, write_pdf
from petvault.ui import theme
from petvault.ui.dialogs.form_dialog import FormDialog
from petvault.ui.helpers import add_field, choice_id, offer_open, selected_id
from petvault.ui.pages.base import BasePage
from petvault.ui.tables import fill_tree, make_table
from petvault.ui.theme import CARD, MUTED, TEXT
from petvault.ui.widgets.pill_button import PillButton
from petvault.ui.widgets.rounded_field import RoundedField
from petvault.utils import money, parse_money_to_cents


class BillingPage(BasePage):
    title = "Billing"
    subtitle = "Invoices, payments and receipts"
    roles = ("admin", "receptionist")
    SHOW = ["Outstanding", "Paid", "Void", "All"]
    SORTS = ["ID", "Date (Oldest)", "Date (Newest)", "A - Z", "Z - A"]
    KEYS = ["id", "issued_on", "patient", "owner", "description", "amount",
            "status", "method"]

    def build(self):
        form, right = self.side_layout("Create invoice")
        self.patient, self.patient_box, _ = add_field(
            form.body, "Patient", choices=[], strict=True)
        self.description, _, _ = add_field(form.body, "Description")
        self.amount, _, _ = add_field(form.body, f"Amount ({CURRENCY})")
        PillButton(form.body, "Create invoice", self.create).pack(anchor="e")

        head = tk.Frame(right.body, bg=CARD)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Invoices", bg=CARD, fg=TEXT,
                 font=(theme.FONT, 13, "bold")).pack(side="left")
        self.sort = tk.StringVar(value=self.SORTS[1])
        self.show = tk.StringVar(value=self.SHOW[0])
        RoundedField(head, self.sort, choices=self.SORTS, strict=True,
                     width=140, on_pick=lambda _t: self.view_changed()).pack(
                         side="right")
        tk.Label(head, text="Sort by", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="right", padx=8)
        RoundedField(head, self.show, choices=self.SHOW, strict=True,
                     width=130, on_pick=lambda _t: self.view_changed()).pack(
                         side="right", padx=(0, 16))
        tk.Label(head, text="Show", bg=CARD, fg=MUTED,
                 font=(theme.FONT, 9)).pack(side="right", padx=8)
        frame, self.tree = make_table(right.body, [
            ("id", "ID", 40), ("issued_on", "Issued", 90),
            ("patient", "Patient", 90), ("owner", "Owner", 120),
            ("description", "Description", 200),
            ("amount", f"Amount ({CURRENCY})", 100), ("status", "Status", 70),
            ("method", "Method", 90)])
        frame.pack(fill="both", expand=True)

        footer = tk.Frame(right.body, bg=CARD)
        footer.pack(fill="x", pady=(12, 0))
        PillButton(footer, "Record payment", self.pay, kind="mint").pack(
            side="left")
        PillButton(footer, "Receipt (PDF)", self.receipt, kind="ghost").pack(
            side="left", padx=8)
        PillButton(footer, "Edit", self.edit, kind="ghost").pack(side="left")
        PillButton(footer, "Void", self.void, kind="danger").pack(
            side="left", padx=8)
        self.total = tk.StringVar()
        tk.Label(footer, textvariable=self.total, bg=CARD, fg=TEXT,
                 font=(theme.FONT, 12, "bold")).pack(side="right")

    def preselect_patient(self, patient_id):
        self.patient.set(self.app.patient_text(patient_id))

    def create(self):
        def action():
            patient_id = choice_id(self.patient_box, "patient")
            cents = parse_money_to_cents(self.amount.get())
            self.clinic.create_invoice(patient_id, self.description.get(),
                                       cents)
            self.description.set("")
            self.amount.set("")
        self.app.commit(action, "Invoice created.")

    def pay(self):
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if invoice["voided"]:
            messagebox.showinfo("Record payment", "A void invoice cannot be paid.",
                                parent=self)
            return
        if invoice["paid"]:
            messagebox.showinfo("Record payment", "This invoice is already paid.",
                                parent=self)
            return
        fields = [{"key": "method", "label": "Payment method",
                   "choices": PAYMENT_METHODS, "strict": True, "value": "Cash"}]

        def submit(dlg):
            self.clinic.pay_invoice(invoice_id,
                                    dlg.choice_text("method", "a payment method"))
            return f"Invoice {invoice_id} marked as paid."
        FormDialog(self.app, "Record payment", fields, submit,
                   submit_text="Mark as paid",
                   hint=f"Invoice {invoice_id} for {invoice['patient']}: "
                   f"{money(invoice['amount_cents'])}")

    def receipt(self):
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if not invoice["paid"]:
            messagebox.showinfo("Receipt", "Receipts can only be made for paid "
                                "invoices. Record the payment first.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"receipt-{invoice_id:06d}.pdf")
        if not path:
            return
        try:
            write_pdf(path, receipt_lines(invoice))
        except OSError as err:
            messagebox.showerror("Receipt", f"Could not save the file:\n{err}",
                                 parent=self)
            return
        offer_open(self, path)

    def edit(self):
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if invoice["voided"] or invoice["paid"]:
            messagebox.showinfo(
                "Edit invoice", "Only unpaid invoices can be changed. "
                "Paid and void invoices are kept as they are.", parent=self)
            return
        fields = [{"key": "description", "label": "Description",
                   "value": invoice["description"]},
                  {"key": "amount", "label": f"Amount ({CURRENCY})",
                   "value": f"{invoice['amount_cents'] / 100:.2f}"}]

        def submit(dlg):
            self.clinic.update_invoice(
                invoice_id, dlg.get("description"),
                parse_money_to_cents(dlg.get("amount")))
        FormDialog(self.app, f"Edit invoice {invoice_id}", fields, submit,
                   message="Invoice updated.")

    def void(self):
        """Cancel an unpaid invoice. It stays in the list marked Void."""
        invoice_id = selected_id(self, self.tree, "an invoice")
        if invoice_id is None:
            return
        invoice = self.clinic.get_invoice(invoice_id)
        if invoice["voided"]:
            messagebox.showinfo("Void invoice", "This invoice is already void.",
                                parent=self)
            return
        if invoice["paid"]:
            messagebox.showinfo(
                "Void invoice", "Paid invoices cannot be voided because they "
                "record a payment.", parent=self)
            return
        fields = [{"key": "reason", "label": "Reason for voiding"}]

        def submit(dlg):
            self.clinic.void_invoice(invoice_id, dlg.get("reason"))
            return f"Invoice {invoice_id} voided."
        FormDialog(self.app, "Void invoice", fields, submit,
                   submit_text="Void invoice",
                   hint=f"Invoice {invoice_id} for {invoice['patient']}: "
                   f"{money(invoice['amount_cents'])}. It stays in the list "
                   "marked Void and no longer counts as money owed.")

    def _sorted(self, rows):
        mode = self.sort.get()
        if mode == "ID":
            return sorted(rows, key=lambda r: r["id"])
        if mode == "Date (Newest)":
            return sorted(rows, key=lambda r: (r["issued_on"], r["id"]),
                          reverse=True)
        if mode == "A - Z":
            return sorted(rows, key=lambda r: r["patient"].lower())
        if mode == "Z - A":
            return sorted(rows, key=lambda r: r["patient"].lower(),
                          reverse=True)
        return list(rows)  # oldest date first, the order the database gives

    def refresh_list(self):
        shown = {"Paid": "paid", "Void": "void", "All": "all"}.get(
            self.show.get(), "outstanding")
        rows = self._sorted(self.clinic.list_invoices(shown))
        fill_tree(self.tree, rows, self.KEYS, tag_key="tag")

    def refresh(self):
        self.patient_box.set_choices(self.app.patient_choices())
        self.refresh_list()
        self.total.set(
            f"Outstanding: {money(self.clinic.outstanding_total_cents())}")
