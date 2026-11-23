"""Landing redirect and the Overview dashboard."""
from datetime import date

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from ...constants import CATEGORY_COLORS
from ...services import analytics_service as analytics

bp = Blueprint("main", __name__)


def _pct_width(value, maximum) -> int:
    if not maximum:
        return 0
    return max(2, round(float(value) / float(maximum) * 100)) if value else 0


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    today = date.today()
    user_id = current_user.id
    summary = analytics.dashboard_summary(user_id, today)
    window = analytics.month_window(today)
    trend = analytics.monthly_breakdown(user_id, 6, today)
    categories = analytics.category_breakdown(user_id, window["cur_start"], window["cur_end"])
    insights = analytics.build_insights(user_id, today)

    biggest = max(summary["current_total"], summary["previous_total"])
    compare = {
        "current": _pct_width(summary["current_total"], biggest),
        "previous": _pct_width(summary["previous_total"], biggest),
    }
    chart_data = {
        "trend": {
            "labels": [m.start.strftime("%b %y") for m in trend],
            "values": [float(m.total) for m in trend],
        },
        "categories": {
            "labels": [c["category"] for c in categories],
            "values": [float(c["total"]) for c in categories],
            "colors": [CATEGORY_COLORS[c["category"]] for c in categories],
        },
    }
    return render_template(
        "dashboard.html",
        summary=summary,
        trend=trend,
        categories=categories,
        insights=insights,
        compare=compare,
        chart_data=chart_data,
        has_trend_data=any(m.total > 0 for m in trend),
    )
