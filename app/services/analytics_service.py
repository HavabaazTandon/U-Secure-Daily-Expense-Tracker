"""Financial calculations. Every number is computed from the user's own records.

All functions take an explicit ``user_id`` and ``today`` so they are easy to
test and can never read another user's data. No machine learning is involved:
these are sums, counts, averages and percentage changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from ..constants import CATEGORIES
from ..extensions import db
from ..models import Expense
from ..utils import (
    add_months,
    days_in_month,
    first_of_month,
    format_money,
    month_key,
    month_label,
)

ZERO = Decimal("0.00")
TWO_PLACES = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(value if value is not None else 0).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def pct_change(current: Decimal, previous: Decimal) -> Decimal | None:
    """Percentage change from ``previous`` to ``current``; None if undefined."""
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------
def period_totals(user_id: int, start: date, end: date) -> dict[str, Decimal]:
    """Category totals for expenses dated ``start`` .. ``end`` (inclusive)."""
    rows = db.session.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.user_id == user_id, Expense.expense_date >= start, Expense.expense_date <= end)
        .group_by(Expense.category)
    ).all()
    return {category: _q(total) for category, total in rows}


def period_total(user_id: int, start: date, end: date) -> Decimal:
    total = db.session.execute(
        select(func.sum(Expense.amount)).where(
            Expense.user_id == user_id, Expense.expense_date >= start, Expense.expense_date <= end
        )
    ).scalar()
    return _q(total)


def month_window(today: date) -> dict:
    """Date boundaries for the current month, previous month and the same days."""
    cur_start = first_of_month(today)
    prev_start = add_months(cur_start, -1)
    prev_last_day = days_in_month(prev_start)
    prev_end = prev_start.replace(day=prev_last_day)
    same_days_end = prev_start.replace(day=min(today.day, prev_last_day))
    return {
        "cur_start": cur_start,
        "cur_end": today,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "same_days_end": same_days_end,
    }


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------
def dashboard_summary(user_id: int, today: date) -> dict:
    count, total, highest = db.session.execute(
        select(func.count(Expense.id), func.sum(Expense.amount), func.max(Expense.amount)).where(
            Expense.user_id == user_id
        )
    ).one()
    lifetime_total = _q(total)
    average = _q(lifetime_total / count) if count else ZERO

    highest_expense = db.session.execute(
        select(Expense)
        .where(Expense.user_id == user_id)
        .order_by(Expense.amount.desc(), Expense.expense_date.desc(), Expense.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    w = month_window(today)
    current_total = period_total(user_id, w["cur_start"], w["cur_end"])
    previous_total = period_total(user_id, w["prev_start"], w["prev_end"])
    same_days_total = period_total(user_id, w["prev_start"], w["same_days_end"])

    recent = list(
        db.session.execute(
            select(Expense)
            .where(Expense.user_id == user_id)
            .order_by(Expense.expense_date.desc(), Expense.id.desc())
            .limit(6)
        ).scalars()
    )
    return {
        "count": count,
        "lifetime_total": lifetime_total,
        "average": average,
        "highest": _q(highest) if highest is not None else ZERO,
        "highest_expense": highest_expense,
        "current_total": current_total,
        "previous_total": previous_total,
        "same_days_total": same_days_total,
        "change_vs_same_days": pct_change(current_total, same_days_total),
        "change_vs_full_month": pct_change(current_total, previous_total),
        "current_label": month_label(w["cur_start"], short=False),
        "previous_label": month_label(w["prev_start"], short=False),
        "previous_name": w["prev_start"].strftime("%B"),
        "recent": recent,
        "today": today,
    }


# ---------------------------------------------------------------------------
# Monthly breakdown (one query, aggregated in Python)
# ---------------------------------------------------------------------------
@dataclass
class MonthStats:
    key: str
    label: str
    start: date
    total: Decimal
    count: int
    average: Decimal | None
    largest: Decimal | None
    top_category: str | None


def monthly_breakdown(user_id: int, months: int, today: date) -> list[MonthStats]:
    """Statistics for the last ``months`` calendar months, oldest first."""
    if months < 1:
        return []
    first = add_months(first_of_month(today), -(months - 1))
    rows = db.session.execute(
        select(Expense.expense_date, Expense.amount, Expense.category).where(
            Expense.user_id == user_id, Expense.expense_date >= first, Expense.expense_date <= today
        )
    ).all()

    buckets: dict[str, dict] = {}
    for expense_date, amount, category in rows:
        bucket = buckets.setdefault(
            month_key(expense_date), {"total": ZERO, "count": 0, "largest": ZERO, "cats": {}}
        )
        bucket["total"] += amount
        bucket["count"] += 1
        bucket["largest"] = max(bucket["largest"], amount)
        bucket["cats"][category] = bucket["cats"].get(category, ZERO) + amount

    result = []
    for offset in range(months):
        start = add_months(first, offset)
        data = buckets.get(month_key(start))
        if data:
            top = max(data["cats"].items(), key=lambda kv: (kv[1], kv[0]))[0]
            result.append(
                MonthStats(
                    month_key(start), month_label(start), start, _q(data["total"]), data["count"],
                    _q(data["total"] / data["count"]), _q(data["largest"]), top,
                )
            )
        else:
            result.append(MonthStats(month_key(start), month_label(start), start, ZERO, 0, None, None, None))
    return result


def months_since_first_expense(user_id: int, today: date, cap: int = 36) -> int:
    first = db.session.execute(
        select(func.min(Expense.expense_date)).where(Expense.user_id == user_id)
    ).scalar()
    if first is None:
        return 1
    span = (today.year - first.year) * 12 + (today.month - first.month) + 1
    return max(1, min(span, cap))


# ---------------------------------------------------------------------------
# Category views
# ---------------------------------------------------------------------------
def category_breakdown(user_id: int, start: date, end: date) -> list[dict]:
    """Per-category total, count, average and share of spending in a window."""
    rows = db.session.execute(
        select(Expense.category, func.sum(Expense.amount), func.count(Expense.id), func.max(Expense.amount))
        .where(Expense.user_id == user_id, Expense.expense_date >= start, Expense.expense_date <= end)
        .group_by(Expense.category)
    ).all()
    grand_total = sum((_q(total) for _, total, _, _ in rows), ZERO)
    breakdown = []
    for category, total, count, largest in rows:
        total = _q(total)
        breakdown.append(
            {
                "category": category,
                "total": total,
                "count": count,
                "average": _q(total / count),
                "largest": _q(largest),
                "share": (total / grand_total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                if grand_total
                else Decimal("0.0"),
            }
        )
    breakdown.sort(key=lambda row: (-row["total"], row["category"]))
    return breakdown


def category_comparison(user_id: int, today: date) -> list[dict]:
    """Current month (to date) against the previous month, per category."""
    w = month_window(today)
    current = period_totals(user_id, w["cur_start"], w["cur_end"])
    previous = period_totals(user_id, w["prev_start"], w["prev_end"])
    same_days = period_totals(user_id, w["prev_start"], w["same_days_end"])
    rows = []
    for category in CATEGORIES:
        cur = current.get(category, ZERO)
        prev = previous.get(category, ZERO)
        same = same_days.get(category, ZERO)
        rows.append(
            {
                "category": category,
                "current": cur,
                "previous": prev,
                "same_days": same,
                "delta": cur - same,
                "change": pct_change(cur, same),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Month statistics and insights
# ---------------------------------------------------------------------------
def current_month_stats(user_id: int, today: date) -> dict:
    w = month_window(today)
    count, total, largest = db.session.execute(
        select(func.count(Expense.id), func.sum(Expense.amount), func.max(Expense.amount)).where(
            Expense.user_id == user_id,
            Expense.expense_date >= w["cur_start"],
            Expense.expense_date <= w["cur_end"],
        )
    ).one()
    total = _q(total)
    days_elapsed = today.day
    return {
        "total": total,
        "count": count,
        "average_transaction": _q(total / count) if count else ZERO,
        "largest": _q(largest) if largest is not None else ZERO,
        "days_elapsed": days_elapsed,
        "daily_average": _q(total / days_elapsed),
    }


def build_insights(user_id: int, today: date) -> list[dict]:
    """Plain-language insights. Each one states the numbers it was built from."""
    summary = dashboard_summary(user_id, today)
    if summary["count"] == 0:
        return []

    w = month_window(today)
    insights: list[dict] = []
    month_stats = current_month_stats(user_id, today)
    this_month = category_breakdown(user_id, w["cur_start"], w["cur_end"])

    # 1. Highest spending category (this month, otherwise all time)
    if this_month:
        top = this_month[0]
        insights.append(
            {
                "title": "Highest spending category",
                "text": f"{top['category']} leads this month at {format_money(top['total'])}, "
                f"{top['share']}% of what you have spent so far.",
            }
        )
    else:
        overall = category_breakdown(user_id, date(1970, 1, 1), today)
        if overall:
            top = overall[0]
            insights.append(
                {
                    "title": "Highest spending category",
                    "text": f"Nothing recorded this month yet. Across all records, {top['category']} "
                    f"is highest at {format_money(top['total'])} ({top['share']}%).",
                }
            )

    # 2. Most expensive transaction
    biggest = summary["highest_expense"]
    if biggest is not None:
        insights.append(
            {
                "title": "Most expensive transaction",
                "text": f"{format_money(biggest.amount)} on {biggest.category}, "
                f"dated {biggest.expense_date.strftime('%d %b %Y').lstrip('0')}.",
            }
        )

    # 3. Average daily spending (current month)
    if month_stats["count"]:
        days = month_stats["days_elapsed"]
        insights.append(
            {
                "title": "Average daily spending",
                "text": f"{format_money(month_stats['daily_average'])} a day this month "
                f"({format_money(month_stats['total'])} over {days} day{'s' if days != 1 else ''}).",
            }
        )

    # 4. Monthly change (same days of the previous month, so the comparison is fair)
    change = summary["change_vs_same_days"]
    prev_name = summary["previous_name"]
    if change is not None:
        direction = "higher" if change > 0 else "lower" if change < 0 else "the same as"
        if change == 0:
            text = f"Spending so far matches the same days of {prev_name} exactly."
        else:
            text = f"Spending so far is {abs(change)}% {direction} than the same days of {prev_name} " \
                   f"({format_money(summary['current_total'])} against {format_money(summary['same_days_total'])})."
        insights.append({"title": "Change from last month", "text": text})
    elif summary["same_days_total"] == 0 and summary["current_total"] > 0:
        insights.append(
            {
                "title": "Change from last month",
                "text": f"No spending was recorded for the same days of {prev_name}, "
                "so a percentage change cannot be calculated.",
            }
        )

    # 5. Category with the largest increase
    increases = [row for row in category_comparison(user_id, today) if row["delta"] > 0]
    if increases:
        row = max(increases, key=lambda r: (r["delta"], r["category"]))
        insights.append(
            {
                "title": "Biggest increase",
                "text": f"{row['category']} is up {format_money(row['delta'])} on the same days of {prev_name}.",
            }
        )

    # 6. Monthly summary
    if month_stats["count"]:
        insights.append(
            {
                "title": "This month in short",
                "text": f"{month_stats['count']} transaction{'s' if month_stats['count'] != 1 else ''} "
                f"totalling {format_money(month_stats['total'])}, averaging "
                f"{format_money(month_stats['average_transaction'])} each.",
            }
        )
    return insights
