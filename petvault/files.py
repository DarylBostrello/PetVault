"""CSV export, a tiny PDF writer, receipt and summary text, and opening files."""

import csv
import os
import subprocess
import sys
import textwrap

from petvault.utils import pdf_money


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def build_pdf(lines, mono=False):
    """A very small text-only PDF writer (A4, standard fonts).

    lines: strings, (text, size, bold) tuples, or ("row", size, columns) where
    columns is a list of (x position, text, bold). Returns the PDF as bytes."""
    page_w, page_h, margin = 595, 842, 56
    items = []
    for line in lines:
        if isinstance(line, str):
            items.append((11, [(margin, line, False)]))
        elif line[0] == "row":
            items.append((line[1], line[2]))
        else:
            items.append((line[1], [(margin, line[0], line[2])]))
    pages, current, y = [], [], page_h - margin
    for size, cols in items:
        leading = size * 1.5
        if y - leading < margin:
            pages.append(current)
            current, y = [], page_h - margin
        y -= leading
        current.append((size, cols, y))
    pages.append(current)

    def esc(text):
        text = text.encode("latin-1", "replace").decode("latin-1")
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    fonts = ("Courier", "Courier-Bold") if mono else ("Helvetica", "Helvetica-Bold")
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: f"<< /Type /Font /Subtype /Type1 /BaseFont /{fonts[0]} "
           f"/Encoding /WinAnsiEncoding >>".encode(),
        4: f"<< /Type /Font /Subtype /Type1 /BaseFont /{fonts[1]} "
           f"/Encoding /WinAnsiEncoding >>".encode(),
    }
    kids, number = [], 5
    for page in pages:
        content = "\n".join(
            f"BT /{'F2' if bold else 'F1'} {size} Tf {x} {y:.1f} Td "
            f"({esc(text)}) Tj ET"
            for size, cols, y in page for x, text, bold in cols)
        data = content.encode("latin-1", "replace")
        page_id, content_id = number, number + 1
        objects[content_id] = (b"<< /Length %d >>\nstream\n" % len(data)
                               + data + b"\nendstream")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>").encode()
        kids.append(f"{page_id} 0 R")
        number += 2
    objects[2] = (f"<< /Type /Pages /Kids [{' '.join(kids)}] "
                  f"/Count {len(kids)} >>").encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in sorted(objects):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def write_pdf(path, lines, mono=False):
    with open(path, "wb") as handle:
        handle.write(build_pdf(lines, mono))


def receipt_lines(invoice):
    """Lines for a one-page receipt of a paid invoice (a database row)."""
    def row(label, value):
        return ("row", 11, [(56, label, True), (190, value, False)])
    lines = [("PetVault Veterinary Clinic", 20, True),
             ("Official receipt", 13, False), "", "",
             row("Receipt no.", f"{invoice['id']:06d}"),
             row("Date paid", invoice["paid_on"] or invoice["issued_on"]),
             row("Issued on", invoice["issued_on"]), "",
             row("Patient", invoice["patient"]),
             row("Owner", invoice["owner"]), ""]
    for i, part in enumerate(textwrap.wrap(invoice["description"], 58) or [""]):
        lines.append(row("Description" if i == 0 else "", part))
    lines += ["", row("Amount paid", pdf_money(invoice["amount_cents"])),
              row("Payment method", invoice["payment_method"] or "-"), "", "",
              ("Thank you for trusting us with your pet.", 11, False)]
    return lines


def summary_lines(report):
    """Lines (monospaced) for a printable summary of a report period."""
    start, end = report["start"], report["end"]
    period = (start.strftime("%d %B %Y") if start == end
              else f"{start:%d %B %Y} to {end:%d %B %Y}")
    lines = [("PetVault: Clinic summary", 16, True), (period, 11, False), ""]

    def add(label, value):
        lines.append(f"{label:<30}{value:>16}")
    add("Appointments", report["appointments"])
    add("  Scheduled", report["scheduled"])
    add("  Completed", report["completed"])
    add("  Cancelled", report["cancelled"])
    add("Medical records (visits)", report["visits"])
    lines.append("")
    add("Invoices issued", report["issued_count"])
    add("  Value issued", pdf_money(report["issued_cents"]))
    add("Payments collected", report["collected_count"])
    add("  Amount collected", pdf_money(report["collected_cents"]))
    add("Still unpaid (issued here)", pdf_money(report["outstanding_cents"]))
    add("Voided invoices", report["void_count"])
    lines += ["", ("Veterinarian workload", 12, True),
              f"{'Veterinarian':<30}{'Appts':>8}{'Done':>8}"]
    for row in report["by_vet"]:
        lines.append(f"{row['vet'][:29]:<30}{row['total']:>8}{row['completed']:>8}")
    if not report["by_vet"]:
        lines.append("(no appointments in this period)")
    return lines


def open_file(path):
    """Open a file or folder with the system's default program."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except (OSError, AttributeError):
        return False
