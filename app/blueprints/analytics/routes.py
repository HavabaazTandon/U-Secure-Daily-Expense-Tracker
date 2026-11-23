"""Analytics page: charts and statistics built from the user's own records."""
from datetime import date
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from ...constants import CATEGORY_COLORS, COMPARISON_COLORS
from ...services import analytics_service as analytics
from ...utils import add_months, first_of_month

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

RANGES = {"3": "3 months", "6": "6 months", "12": "12 months", "all": "All time"}


@bp.route("/")
@login_required
def index():
    today = date.today()
    user_id = current_user.id
    range_key = request.args.get("range", "6")
    if range_key not in RANGES:
        range_key = "6"
    months = analytics.months_since_first_expense(user_id, today) if range_key == "all" else int(range_key)

    start = add_months(first_of_month(today), -(months - 1))
    monthly = analytics.monthly_breakdown(user_id, months, today)
    breakdown = analytics.category_breakdown(user_id, start, today)
    comparison = analytics.category_comparison(user_id, today)
    summary = analytics.dashboard_summary(user_id, today)
    month_stats = analytics.current_month_stats(user_id, today)
    insights = analytics.build_insights(user_id, today)

    chart_data = {
        "trend": {"labels": [m.start.strftime("%b %y") for m in monthly], "values": [float(m.total) for m in monthly]},
        "distribution": {
            "labels": [row["category"] for row in breakdown],
            "values": [float(row["total"]) for row in breakdown],
            "colors": [CATEGORY_COLORS[row["category"]] for row in breakdown],
        },
        "comparison": {
            "labels": [row["category"] for row in comparison],
            "current": [float(row["current"]) for row in comparison],
            "previous": [float(row["previous"]) for row in comparison],
            "colors": COMPARISON_COLORS,
            "current_label": summary["current_label"] + " (to date)",
            "previous_label": summary["previous_label"],
        },
    }
    return render_template(
        "analytics.html",
        ranges=RANGES,
        range_key=range_key,
        monthly=monthly,
        breakdown=breakdown,
        comparison=comparison,
        summary=summary,
        month_stats=month_stats,
        insights=insights,
        chart_data=chart_data,
        has_data=summary["count"] > 0,
        window_total=sum((row["total"] for row in breakdown), Decimal("0.00")),
    )
