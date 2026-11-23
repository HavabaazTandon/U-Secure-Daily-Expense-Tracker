"""Modules 2, 5, 6: dashboard figures, analytics calculations and insights."""
from datetime import date
from decimal import Decimal

import pytest

from app.services import analytics_service as an
from app.services import expense_service as svc
from app.utils import add_months, format_money, indian_group, money_parts

from .conftest import add_expense, make_user

TODAY = date(2026, 11, 20)


def D(value):
    return Decimal(value)


@pytest.fixture()
def seeded(app, user):
    rows = [
        # November 2026 (current month, to date)
        ("Food", "100.00", date(2026, 11, 3), "Groceries"),
        ("Food", "50.00", date(2026, 11, 10), "Snacks"),
        ("Travel", "400.00", date(2026, 11, 15), "Flight"),
        ("Shopping", "25.50", date(2026, 11, 20), "Notebook"),
        # October 2026 (previous month; 500 of it falls on days 1-20)
        ("Medical", "300.00", date(2026, 10, 1), "Dentist"),
        ("Food", "200.00", date(2026, 10, 5), "Dinner"),
        ("Travel", "100.00", date(2026, 10, 25), "Taxi"),
        # September 2026
        ("Education", "1000.00", date(2026, 9, 12), "Course"),
    ]
    for category, amount, d, desc in rows:
        svc.create_expense(user.id, category, D(amount), d, desc)
    return user


# --- dashboard summary ------------------------------------------------------
def test_dashboard_summary_figures(seeded):
    s = an.dashboard_summary(seeded.id, TODAY)
    assert s["count"] == 8
    assert s["lifetime_total"] == D("2175.50")
    assert s["average"] == D("271.94")  # 2175.50 / 8 = 271.9375
    assert s["highest"] == D("1000.00") and s["highest_expense"].category == "Education"
    assert s["current_total"] == D("575.50")
    assert s["previous_total"] == D("600.00")
    assert s["same_days_total"] == D("500.00")
    assert s["change_vs_same_days"] == D("15.1")
    assert s["change_vs_full_month"] == D("-4.1")
    assert [e.description for e in s["recent"]][:2] == ["Notebook", "Flight"]


def test_dashboard_summary_for_empty_account(app, user):
    s = an.dashboard_summary(user.id, TODAY)
    assert s["count"] == 0 and s["lifetime_total"] == 0 and s["average"] == 0
    assert s["highest_expense"] is None and s["change_vs_same_days"] is None
    assert an.build_insights(user.id, TODAY) == []


# --- month windows -----------------------------------------------------------
def test_month_window_handles_short_months_and_leap_years():
    w = an.month_window(date(2026, 3, 31))
    assert (w["prev_start"], w["prev_end"], w["same_days_end"]) == (date(2026, 2, 1), date(2026, 2, 28), date(2026, 2, 28))
    assert an.month_window(date(2028, 3, 31))["same_days_end"] == date(2028, 2, 29)
    assert an.month_window(date(2026, 1, 15))["prev_start"] == date(2025, 12, 1)


def test_add_months_wraps_years():
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert add_months(date(2026, 11, 20), 3) == date(2027, 2, 1)


def test_pct_change_is_none_when_base_is_zero():
    assert an.pct_change(D("10"), D("0")) is None
    assert an.pct_change(D("150"), D("100")) == D("50.0")
    assert an.pct_change(D("50"), D("100")) == D("-50.0")


# --- monthly trend & stats -----------------------------------------------------
def test_monthly_breakdown(seeded):
    months = an.monthly_breakdown(seeded.id, 4, TODAY)
    assert [m.key for m in months] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    aug, sep, octo, nov = months
    assert (aug.total, aug.count, aug.average, aug.top_category) == (D("0.00"), 0, None, None)
    assert (sep.total, sep.top_category) == (D("1000.00"), "Education")
    assert (octo.total, octo.count, octo.top_category, octo.largest) == (D("600.00"), 3, "Medical", D("300.00"))
    assert (nov.total, nov.count, nov.average, nov.top_category) == (D("575.50"), 4, D("143.88"), "Travel")


def test_months_since_first_expense(seeded, app):
    assert an.months_since_first_expense(seeded.id, TODAY) == 3  # Sep, Oct, Nov
    other = make_user("new@example.com", "New")
    assert an.months_since_first_expense(other.id, TODAY) == 1


def test_current_month_stats(seeded):
    s = an.current_month_stats(seeded.id, TODAY)
    assert s["total"] == D("575.50") and s["count"] == 4 and s["largest"] == D("400.00")
    assert s["average_transaction"] == D("143.88") and s["days_elapsed"] == 20
    assert s["daily_average"] == D("28.78")


# --- categories --------------------------------------------------------------------
def test_category_breakdown_shares(seeded):
    rows = an.category_breakdown(seeded.id, date(2026, 11, 1), TODAY)
    assert [(r["category"], r["total"], r["share"]) for r in rows] == [
        ("Travel", D("400.00"), D("69.5")),
        ("Food", D("150.00"), D("26.1")),
        ("Shopping", D("25.50"), D("4.4")),
    ]
    assert rows[1]["count"] == 2 and rows[1]["average"] == D("75.00") and rows[1]["largest"] == D("100.00")


def test_category_comparison(seeded):
    rows = {r["category"]: r for r in an.category_comparison(seeded.id, TODAY)}
    assert (rows["Food"]["current"], rows["Food"]["previous"], rows["Food"]["delta"]) == (D("150"), D("200"), D("-50"))
    assert rows["Travel"]["previous"] == D("100") and rows["Travel"]["same_days"] == D("0") and rows["Travel"]["change"] is None
    assert rows["Medical"]["change"] == D("-100.0")
    assert rows["Education"]["current"] == 0 and rows["Other"]["previous"] == 0
    assert list(rows) == ["Food", "Travel", "Education", "Shopping", "Medical", "Other"]


# --- insights -----------------------------------------------------------------------
def test_insights_use_real_numbers(seeded):
    text = " | ".join(i["text"] for i in an.build_insights(seeded.id, TODAY))
    assert "Travel leads this month at ₹400.00, 69.5%" in text
    assert "₹1,000.00 on Education, dated 12 Sep 2026" in text
    assert "₹28.78 a day this month" in text
    assert "15.1% higher than the same days of October" in text
    assert "Travel is up ₹400.00" in text
    assert "4 transactions totalling ₹575.50" in text


def test_insights_when_nothing_spent_this_month(app, user):
    svc.create_expense(user.id, "Food", D("80"), date(2026, 9, 1), "Old")
    insights = an.build_insights(user.id, TODAY)
    assert "Nothing recorded this month yet" in insights[0]["text"]


def test_analytics_never_include_other_users(seeded, app):
    other = make_user("other@example.com", "Other")
    svc.create_expense(other.id, "Food", D("9999.00"), date(2026, 11, 2), "Secret")
    assert an.dashboard_summary(seeded.id, TODAY)["current_total"] == D("575.50")
    assert an.dashboard_summary(other.id, TODAY)["current_total"] == D("9999.00")
    assert all(r["total"] < D("9999") for r in an.category_breakdown(seeded.id, date(2020, 1, 1), TODAY))


# --- formatting --------------------------------------------------------------------
def test_indian_money_formatting():
    assert indian_group("1234567") == "12,34,567"
    assert format_money(D("1234567.5")) == "₹12,34,567.50"
    assert format_money(D("0")) == "₹0.00" and format_money(None) == "₹0.00"
    assert format_money(D("-1500")) == "-₹1,500.00"
    assert money_parts(D("999.99")) == ("₹", "999", ".99")


# --- pages ---------------------------------------------------------------------------
def test_dashboard_and_analytics_render_with_data(auth_client):
    today = date.today()
    add_expense(auth_client, "Food", "120.00", today, "Weekly groceries")
    add_expense(auth_client, "Travel", "80.00", today, "Metro card")
    dash = auth_client.get("/dashboard")
    assert dash.status_code == 200
    html = dash.get_data(as_text=True)
    assert "₹200.00" in html and "Weekly groceries" in html and 'id="trendChart"' in html
    assert '"Food"' in html and "chart-data" in html
    page = auth_client.get("/analytics/")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    for needle in ["Monthly spending trend", "Category distribution", "Category comparison", "Spending breakdown", "Monthly expense statistics"]:
        assert needle in body
    assert 'id="comparisonChart"' in body


def test_analytics_ranges_and_invalid_range(auth_client):
    add_expense(auth_client)
    for r in ["3", "6", "12", "all", "bogus", "-1", "9999"]:
        assert auth_client.get("/analytics/", query_string={"range": r}).status_code == 200


def test_empty_states(auth_client):
    assert b"No expenses yet" in auth_client.get("/dashboard").data
    assert b"Nothing to analyse yet" in auth_client.get("/analytics/").data
    assert b"No expenses yet" in auth_client.get("/expenses/").data
