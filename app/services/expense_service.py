"""Expense queries, filtering, sorting and pagination (always scoped to a user)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from flask import abort
from sqlalchemy import func, select

from ..constants import CATEGORIES
from ..extensions import db
from ..models import Expense

SORT_OPTIONS = {
    "date_desc": "Newest first",
    "date_asc": "Oldest first",
    "amount_desc": "Highest amount",
    "amount_asc": "Lowest amount",
}


def _parse_date(raw: str | None, label: str, errors: list[str]) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"{label} was not a valid date and was ignored.")
        return None


@dataclass
class ExpenseFilters:
    q: str = ""
    category: str = ""
    on_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    sort: str = "date_desc"
    page: int = 1
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_args(cls, args) -> "ExpenseFilters":
        errors: list[str] = []
        q = (args.get("q") or "").strip()[:100]

        category = (args.get("category") or "").strip()
        if category and category not in CATEGORIES:
            errors.append("That category filter is not available and was ignored.")
            category = ""

        on_date = _parse_date(args.get("date"), "The date filter", errors)
        date_from = _parse_date(args.get("date_from"), "The 'from' date", errors)
        date_to = _parse_date(args.get("date_to"), "The 'to' date", errors)
        if date_from and date_to and date_from > date_to:
            errors.append("The 'from' date was after the 'to' date, so the range was ignored.")
            date_from = date_to = None

        sort = args.get("sort") or "date_desc"
        if sort not in SORT_OPTIONS:
            sort = "date_desc"

        try:
            page = max(1, int(args.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        return cls(q, category, on_date, date_from, date_to, sort, page, errors)

    @property
    def is_active(self) -> bool:
        return bool(self.q or self.category or self.on_date or self.date_from or self.date_to)

    def as_query(self, **overrides) -> dict:
        """Query-string dict (empty values dropped) for building links."""
        data = {
            "q": self.q,
            "category": self.category,
            "date": self.on_date.isoformat() if self.on_date else "",
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
            "sort": self.sort if self.sort != "date_desc" else "",
            "page": self.page if self.page > 1 else "",
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v not in ("", None)}


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered_select(user_id: int, f: ExpenseFilters):
    stmt = select(Expense).where(Expense.user_id == user_id)
    if f.q:
        stmt = stmt.where(Expense.description.ilike(f"%{_escape_like(f.q)}%", escape="\\"))
    if f.category:
        stmt = stmt.where(Expense.category == f.category)
    if f.on_date:
        stmt = stmt.where(Expense.expense_date == f.on_date)
    if f.date_from:
        stmt = stmt.where(Expense.expense_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Expense.expense_date <= f.date_to)
    return stmt


def _ordered(stmt, sort: str):
    if sort == "date_asc":
        return stmt.order_by(Expense.expense_date.asc(), Expense.id.asc())
    if sort == "amount_desc":
        return stmt.order_by(Expense.amount.desc(), Expense.expense_date.desc(), Expense.id.desc())
    if sort == "amount_asc":
        return stmt.order_by(Expense.amount.asc(), Expense.expense_date.desc(), Expense.id.desc())
    return stmt.order_by(Expense.expense_date.desc(), Expense.id.desc())


def paginate(user_id: int, f: ExpenseFilters, per_page: int):
    stmt = _ordered(_filtered_select(user_id, f), f.sort)
    return db.paginate(stmt, page=f.page, per_page=per_page, error_out=False)


def filtered_total(user_id: int, f: ExpenseFilters) -> Decimal:
    base = _filtered_select(user_id, f).subquery()
    total = db.session.execute(select(func.sum(base.c.amount))).scalar()
    return Decimal(total) if total is not None else Decimal("0.00")


def get_owned_expense_or_404(expense_id: int, user_id: int) -> Expense:
    """Ownership check for every single-record operation (prevents IDOR).

    A record that belongs to somebody else is reported as 404, not 403, so
    its existence is not revealed either.
    """
    expense = db.session.execute(
        select(Expense).where(Expense.id == expense_id, Expense.user_id == user_id)
    ).scalar_one_or_none()
    if expense is None:
        abort(404)
    return expense


def create_expense(user_id: int, category: str, amount, expense_date: date, description: str) -> Expense:
    expense = Expense(
        user_id=user_id,
        category=category,
        amount=amount,
        expense_date=expense_date,
        description=(description or "").strip(),
    )
    db.session.add(expense)
    db.session.commit()
    return expense


def update_expense(expense: Expense, category: str, amount, expense_date: date, description: str) -> Expense:
    expense.category = category
    expense.amount = amount
    expense.expense_date = expense_date
    expense.description = (description or "").strip()
    db.session.commit()
    return expense


def delete_expense(expense: Expense) -> None:
    db.session.delete(expense)
    db.session.commit()
