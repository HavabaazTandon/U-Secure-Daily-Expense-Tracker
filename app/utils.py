"""Small helpers: time, money formatting and safe redirects."""
from __future__ import annotations

import calendar
import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores no timezone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def first_of_month(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    """Return the first day of the month ``months`` away from ``d``'s month."""
    index = d.year * 12 + (d.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(d: date, short: bool = True) -> str:
    return d.strftime("%b %Y" if short else "%B %Y")


def indian_group(integer_digits: str) -> str:
    """Group digits the Indian way: 1,23,45,678."""
    if len(integer_digits) <= 3:
        return integer_digits
    head, tail = integer_digits[:-3], integer_digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def money_parts(value, symbol: str = "\u20b9") -> tuple[str, str, str]:
    """Split an amount into (symbol, integer part, decimals) for display."""
    amount = Decimal(value if value is not None else 0).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    return f"{sign}{symbol}", indian_group(whole), f".{cents}"


def format_money(value, symbol: str = "\u20b9") -> str:
    sign_symbol, whole, cents = money_parts(value, symbol)
    return f"{sign_symbol}{whole}{cents}"


def is_safe_redirect_target(target: str | None) -> bool:
    """Allow only same-site relative paths (prevents open redirects)."""
    if not target or not isinstance(target, str):
        return False
    if any(ord(ch) < 32 for ch in target):
        return False
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parts = urlparse(target)
    return not parts.scheme and not parts.netloc


def fingerprint(value: str) -> str:
    """Short one-way fingerprint - used so logs never contain e-mail addresses."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
