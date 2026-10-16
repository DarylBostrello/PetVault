"""Small pure helpers: parsing dates, times and money, formatting, slot times."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from petvault.config import (
    CURRENCY,
    CURRENCY_CODE,
    DATETIME_FMT,
    DATE_FMT,
    SLOT_MINUTES,
)
from petvault.errors import ClinicError


def parse_date(text: str) -> date:
    try:
        return datetime.strptime(text.strip(), DATE_FMT).date()
    except ValueError:
        raise ClinicError(f"Invalid date '{text}'. Use YYYY-MM-DD.")


def parse_datetime(text: str) -> datetime:
    try:
        return datetime.strptime(text.strip(), DATETIME_FMT)
    except ValueError:
        raise ClinicError(f"Invalid date/time '{text}'. Use YYYY-MM-DD HH:MM.")


def parse_money_to_cents(text: str) -> int:
    try:
        amount = Decimal(text.strip().replace(",", ""))
    except InvalidOperation:
        raise ClinicError(f"Invalid amount '{text}'.")
    if amount < 0:
        raise ClinicError("Amount cannot be negative.")
    return int((amount * 100).quantize(Decimal("1")))


def require(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ClinicError(f"{label} is required.")
    return value


def to_minutes(text: str) -> int:
    try:
        hours, minutes = text.strip().split(":")
        hours, minutes = int(hours), int(minutes)
    except ValueError:
        raise ClinicError(f"Invalid time '{text}'. Use HH:MM.")
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ClinicError(f"Invalid time '{text}'. Use HH:MM.")
    return hours * 60 + minutes


def from_minutes(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def slot_times(start: str, end: str):
    """Every appointment start time between start and end (last slot must fit)."""
    return [from_minutes(m) for m in
            range(to_minutes(start), to_minutes(end) - SLOT_MINUTES + 1,
                  SLOT_MINUTES)]


def plural(count, word):
    return f"{count} {word if count == 1 else word + 's'}"


def money(cents):
    return f"{CURRENCY}{cents / 100:,.2f}"


def pdf_money(cents):
    return f"{CURRENCY_CODE} {cents / 100:,.2f}"


def age_text(birth_date):
    """'2020-03-14' -> '6y 7m'. Returns '' when the date is missing/invalid."""
    if not birth_date:
        return ""
    try:
        born = datetime.strptime(birth_date, DATE_FMT).date()
    except ValueError:
        return ""
    today = date.today()
    months = ((today.year - born.year) * 12 + today.month - born.month
              - (1 if today.day < born.day else 0))
    years, months = divmod(max(months, 0), 12)
    return f"{years}y {months}m" if years else f"{months}m"


def parse_weight(text):
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ClinicError(f"Invalid weight '{text}'. Enter a number in kg.")
