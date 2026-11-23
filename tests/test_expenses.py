"""Modules 3 and 4: expense management, validation, filtering, pagination."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select

from app.extensions import db
from app.models import Expense

from .conftest import add_expense


def all_expenses():
    return db.session.execute(select(Expense).order_by(Expense.id)).scalars().all()


# 9. Add ---------------------------------------------------------------------
def test_add_expense(auth_client, user):
    r = add_expense(auth_client, "Travel", "1,250.50", description="  Train ticket  ")
    assert r.status_code == 302
    (e,) = all_expenses()
    assert (e.category, e.amount, e.description, e.user_id) == ("Travel", Decimal("1250.50"), "Train ticket", user.id)


def test_amount_is_stored_exactly(auth_client):
    add_expense(auth_client, amount="0.10")
    add_expense(auth_client, amount="0.20")
    total = sum(e.amount for e in all_expenses())
    assert total == Decimal("0.30")  # float arithmetic would give 0.30000000000000004


# 10. View -------------------------------------------------------------------
def test_view_expenses_lists_only_formatted_records(auth_client):
    add_expense(auth_client, "Food", "1234567.00", description="Wedding feast")
    page = auth_client.get("/expenses/")
    assert page.status_code == 200
    assert b"Wedding feast" in page.data and "₹12,34,567.00".encode() in page.data


# 11. Edit -------------------------------------------------------------------
def test_edit_expense(auth_client):
    add_expense(auth_client, "Food", "100.00", description="Old")
    e = all_expenses()[0]
    assert auth_client.get(f"/expenses/{e.id}/edit").status_code == 200
    r = auth_client.post(
        f"/expenses/{e.id}/edit",
        data={"category": "Medical", "amount": "99.99", "expense_date": "2026-01-15", "description": "Pharmacy"},
    )
    assert r.status_code == 302
    db.session.expire_all()
    e = all_expenses()[0]
    assert (e.category, e.amount, e.expense_date, e.description) == ("Medical", Decimal("99.99"), date(2026, 1, 15), "Pharmacy")


def test_edit_form_is_prefilled(auth_client):
    add_expense(auth_client, "Shopping", "75.50", description="Shirt")
    e = all_expenses()[0]
    html = auth_client.get(f"/expenses/{e.id}/edit").get_data(as_text=True)
    assert 'value="75.50"' in html and "Shirt" in html


# 12. Delete -----------------------------------------------------------------
def test_delete_expense(auth_client):
    add_expense(auth_client)
    e = all_expenses()[0]
    assert auth_client.post(f"/expenses/{e.id}/delete").status_code == 302
    assert all_expenses() == []


def test_delete_requires_post(auth_client):
    add_expense(auth_client)
    e = all_expenses()[0]
    assert auth_client.get(f"/expenses/{e.id}/delete").status_code == 405
    assert len(all_expenses()) == 1


# 13. Invalid amount ---------------------------------------------------------
@pytest.mark.parametrize(
    "amount",
    ["-5", "0", "0.00", "abc", "", "NaN", "Infinity", "-Infinity", "1e999", "12.345", "99999999999", "1,2,3x", "10.5.5"],
)
def test_invalid_amounts_are_rejected(auth_client, amount):
    r = add_expense(auth_client, amount=amount)
    assert r.status_code == 400
    assert all_expenses() == []


# 14. Invalid category + SQL injection ---------------------------------------
@pytest.mark.parametrize("category", ["Groceries", "", "food", "Other ", "<script>alert(1)</script>"])
def test_invalid_categories_are_rejected(auth_client, category):
    assert add_expense(auth_client, category=category).status_code == 400
    assert all_expenses() == []


def test_sql_injection_in_category_is_rejected_and_table_survives(auth_client):
    payload = "Food'; DROP TABLE expenses; --"
    r = add_expense(auth_client, category=payload)
    assert r.status_code == 400
    assert b"Choose one of the available categories" in r.data
    assert "expenses" in inspect(db.engine).get_table_names()  # table still exists
    assert add_expense(auth_client).status_code == 302  # and still works
    assert len(all_expenses()) == 1


def test_sql_injection_in_description_and_search_is_inert(auth_client):
    payload = "x'); DROP TABLE expenses; --"
    assert add_expense(auth_client, description=payload).status_code == 302
    assert auth_client.get("/expenses/", query_string={"q": payload}).status_code == 200
    assert auth_client.get("/expenses/", query_string={"q": "' OR 1=1 --", "category": "' OR '1'='1"}).status_code == 200
    assert "expenses" in inspect(db.engine).get_table_names()
    assert all_expenses()[0].description == payload  # stored verbatim, never executed


def test_database_constraints_back_up_validation(app, user):
    from sqlalchemy.exc import IntegrityError

    db.session.add(Expense(user_id=user.id, category="Bogus", amount=Decimal("5"), expense_date=date.today()))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(Expense(user_id=user.id, category="Food", amount=Decimal("-5"), expense_date=date.today()))
    with pytest.raises(IntegrityError):
        db.session.commit()


# 15. Invalid date -----------------------------------------------------------
@pytest.mark.parametrize("value", ["", "not-a-date", "2026-13-01", "2026-02-30", "31/12/2025", "1999-12-31"])
def test_invalid_dates_are_rejected(auth_client, value):
    r = auth_client.post("/expenses/new", data={"category": "Food", "amount": "10", "expense_date": value})
    assert r.status_code == 400 and all_expenses() == []


def test_future_dates_are_rejected(auth_client):
    r = add_expense(auth_client, expense_date=date.today() + timedelta(days=30))
    assert r.status_code == 400 and b"cannot be in the future" in r.data


def test_missing_fields_are_rejected(auth_client):
    assert auth_client.post("/expenses/new", data={}).status_code == 400
    assert all_expenses() == []


def test_description_is_optional_but_limited(auth_client):
    assert add_expense(auth_client, description="").status_code == 302
    assert add_expense(auth_client, description="x" * 256).status_code == 400


# 16-17. Filtering -----------------------------------------------------------
@pytest.fixture()
def sample(auth_client):
    today = date.today()
    rows = [
        ("Food", "120.00", today, "Groceries"),
        ("Food", "60.00", today - timedelta(days=1), "Coffee beans"),
        ("Travel", "900.00", today - timedelta(days=5), "Bus pass"),
        ("Education", "2500.00", today - timedelta(days=10), "Course fee 100% off?"),
        ("Medical", "300.00", today - timedelta(days=20), "Pharmacy"),
    ]
    for category, amount, d, desc in rows:
        add_expense(auth_client, category, amount, d, desc)
    return auth_client


def descriptions(response):
    html = response.get_data(as_text=True)
    return [d for d in ["Groceries", "Coffee beans", "Bus pass", "Course fee", "Pharmacy"] if d in html]


def test_category_filter(sample):
    assert descriptions(sample.get("/expenses/", query_string={"category": "Food"})) == ["Groceries", "Coffee beans"]


def test_single_date_filter(sample):
    d = (date.today() - timedelta(days=5)).isoformat()
    assert descriptions(sample.get("/expenses/", query_string={"date": d})) == ["Bus pass"]


def test_date_range_filter(sample):
    r = sample.get("/expenses/", query_string={
        "date_from": (date.today() - timedelta(days=10)).isoformat(),
        "date_to": (date.today() - timedelta(days=1)).isoformat(),
    })
    assert descriptions(r) == ["Coffee beans", "Bus pass", "Course fee"]


def test_combined_filters(sample):
    r = sample.get("/expenses/", query_string={"category": "Food", "q": "coffee"})
    assert descriptions(r) == ["Coffee beans"]


def test_search_is_case_insensitive_and_treats_wildcards_literally(sample):
    assert descriptions(sample.get("/expenses/", query_string={"q": "PHARMA"})) == ["Pharmacy"]
    assert descriptions(sample.get("/expenses/", query_string={"q": "%"})) == ["Course fee"]  # only the literal "%"
    assert descriptions(sample.get("/expenses/", query_string={"q": "_"})) == []


def test_sorting(sample):
    html = sample.get("/expenses/", query_string={"sort": "amount_desc"}).get_data(as_text=True)
    assert html.index("Course fee") < html.index("Bus pass") < html.index("Pharmacy") < html.index("Groceries")
    html = sample.get("/expenses/", query_string={"sort": "date_asc"}).get_data(as_text=True)
    assert html.index("Pharmacy") < html.index("Groceries")
    html = sample.get("/expenses/", query_string={"sort": "amount_asc"}).get_data(as_text=True)
    assert html.index("Coffee beans") < html.index("Groceries")


def test_invalid_filter_values_are_ignored_safely(sample):
    r = sample.get("/expenses/", query_string={"category": "Nope", "date": "garbage", "sort": "evil", "page": "abc"})
    assert r.status_code == 200 and b"was ignored" in r.data
    assert len(descriptions(r)) == 5


def test_reversed_date_range_is_ignored(sample):
    r = sample.get("/expenses/", query_string={"date_from": "2026-12-31", "date_to": "2026-01-01"})
    assert r.status_code == 200 and b"range was ignored" in r.data


def test_filter_summary_shows_count_total_and_clear_link(sample):
    html = sample.get("/expenses/", query_string={"category": "Food"}).get_data(as_text=True)
    assert "2 transactions match your filters" in html
    assert "₹180.00" in html and "Clear filters" in html


def test_no_match_state(sample):
    html = sample.get("/expenses/", query_string={"q": "zzzz"}).get_data(as_text=True)
    assert "No transactions match" in html


def test_pagination(auth_client, app):
    for i in range(25):
        add_expense(auth_client, "Food", "10.00", date.today(), f"Item {i:02d}")
    per_page = app.config["EXPENSES_PER_PAGE"]
    p1 = auth_client.get("/expenses/").get_data(as_text=True)
    p3 = auth_client.get("/expenses/", query_string={"page": 3}).get_data(as_text=True)
    assert p1.count("<tr>") - 1 == per_page and "25 transactions" in p1
    assert p3.count("<tr>") - 1 == 5
    assert "page=2" in p1 and 'aria-current="page"' in p3
    assert auth_client.get("/expenses/", query_string={"page": 99}).status_code == 200  # empty, not an error
