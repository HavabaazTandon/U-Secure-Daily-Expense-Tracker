"""Shared pytest fixtures and helpers."""
import re
from datetime import date

import pytest

from flask import g

from app import create_app
from app.extensions import db
from app.services import auth_service

PASSWORD = "Sturdy-pass-42"


def build_app(overrides=None):
    """Create a testing app.

    The fixtures keep one app context open for the whole test so tests can query
    the database directly. Flask-Login caches the current user on ``flask.g``,
    which (like the CSRF token cache) would then leak between requests; in
    production every request gets its own context. Clearing them before each
    request restores real behaviour.
    """
    app = create_app("testing", overrides)

    def _isolate_request_state():
        for key in ("_login_user", "csrf_token", "csrf_valid"):
            g.pop(key, None)

    # Must run before CSRFProtect's own check, hence inserted at the front.
    app.before_request_funcs.setdefault(None, []).insert(0, _isolate_request_state)

    return app


@pytest.fixture()
def app():
    app = build_app()
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def csrf_app():
    """Application with CSRF protection switched on (as in production)."""
    app = build_app({"WTF_CSRF_ENABLED": True})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def limited_app():
    """Application with rate limiting enabled and a tiny login quota."""
    app = build_app(
        {"RATELIMIT_ENABLED": True, "LOGIN_RATE_LIMIT": "3 per minute", "LOGIN_MAX_FAILED_ATTEMPTS": 50}
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(email="ada@example.com", username="Ada", password=PASSWORD):
    return auth_service.create_user(username, email, password)


def login(client, email="ada@example.com", password=PASSWORD, follow=False):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=follow)


@pytest.fixture()
def user(app):
    return make_user()


@pytest.fixture()
def auth_client(app, user):
    client = app.test_client()
    assert login(client).status_code == 302
    return client


@pytest.fixture()
def other_user(app):
    return make_user("grace@example.com", "Grace")


def add_expense(client, category="Food", amount="250.00", expense_date=None, description="Lunch"):
    return client.post(
        "/expenses/new",
        data={
            "category": category,
            "amount": amount,
            "expense_date": (expense_date or date.today()).isoformat(),
            "description": description,
        },
    )


def csrf_token(client, url="/login"):
    html = client.get(url).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(
        r'value="([^"]+)"[^>]*name="csrf_token"', html
    )
    assert match, "no CSRF token found on " + url
    return match.group(1)
