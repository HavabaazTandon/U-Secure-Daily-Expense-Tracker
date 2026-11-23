"""Security controls: isolation, IDOR, CSRF, XSS, headers, cookies, safe errors."""
import logging
import re
from datetime import date

import pytest
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import Expense, User

from .conftest import PASSWORD, add_expense, csrf_token, login, make_user

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "<svg/onload=alert(1)>",
    "'; alert(document.cookie); //",
]


# --- user data isolation & IDOR ---------------------------------------------------
@pytest.fixture()
def two_users(app):
    ada = make_user("ada@example.com", "Ada")
    grace = make_user("grace@example.com", "Grace")
    a, g = app.test_client(), app.test_client()
    login(a, "ada@example.com")
    login(g, "grace@example.com")
    add_expense(a, "Food", "111.00", date.today(), "Ada private lunch")
    add_expense(g, "Travel", "222.00", date.today(), "Grace private trip")
    ada_exp = db.session.execute(select(Expense).where(Expense.user_id == ada.id)).scalar_one()
    return a, g, ada_exp


def test_users_only_see_their_own_records(two_users):
    a, g, _ = two_users
    for url in ["/dashboard", "/expenses/", "/analytics/"]:
        body = a.get(url).get_data(as_text=True)
        assert "Grace private trip" not in body and "₹222.00" not in body, url
        body = g.get(url).get_data(as_text=True)
        assert "Ada private lunch" not in body and "₹111.00" not in body, url


def test_search_cannot_reach_other_users_records(two_users):
    a, _, _ = two_users
    assert b"Grace private trip" not in a.get("/expenses/", query_string={"q": "Grace"}).data


def test_idor_edit_is_blocked(two_users):
    _, g, ada_exp = two_users
    assert g.get(f"/expenses/{ada_exp.id}/edit").status_code == 404
    r = g.post(f"/expenses/{ada_exp.id}/edit", data={"category": "Other", "amount": "1", "expense_date": "2026-01-01", "description": "hacked"})
    assert r.status_code == 404
    db.session.expire_all()
    stored = db.session.get(Expense, ada_exp.id)
    assert stored.description == "Ada private lunch" and str(stored.amount) == "111.00"


def test_idor_delete_is_blocked(two_users):
    _, g, ada_exp = two_users
    assert g.post(f"/expenses/{ada_exp.id}/delete").status_code == 404
    assert db.session.get(Expense, ada_exp.id) is not None


def test_idor_unknown_ids_look_identical_to_foreign_ids(two_users):
    _, g, ada_exp = two_users
    assert g.get(f"/expenses/{ada_exp.id}/edit").status_code == g.get("/expenses/99999/edit").status_code == 404


def test_deleting_user_cascades_to_expenses(two_users, app):
    _, _, ada_exp = two_users
    exp_id, user_id = ada_exp.id, ada_exp.user_id
    db.session.delete(db.session.get(User, user_id))
    db.session.commit()
    db.session.expire_all()
    remaining = db.session.execute(select(Expense.id)).scalars().all()
    assert exp_id not in remaining and len(remaining) == 1  # only Grace's expense is left


# --- CSRF -------------------------------------------------------------------------------
def csrf_login(client):
    token = csrf_token(client, "/login")
    r = client.post("/login", data={"email": "ada@example.com", "password": PASSWORD, "csrf_token": token})
    assert r.status_code == 302
    return client


def test_forms_require_csrf_token(csrf_app):
    make_user()
    client = csrf_app.test_client()
    r = client.post("/login", data={"email": "ada@example.com", "password": PASSWORD})
    assert r.status_code == 400 and b"Security check failed" in r.data
    r = client.post("/register", data={"username": "X1", "email": "x@example.com", "password": PASSWORD, "confirm_password": PASSWORD})
    assert r.status_code == 400
    assert db.session.execute(select(User).where(User.email == "x@example.com")).first() is None


def test_login_with_valid_token_works_and_forged_token_fails(csrf_app):
    make_user()
    client = csrf_app.test_client()
    r = client.post("/login", data={"email": "ada@example.com", "password": PASSWORD, "csrf_token": "forged"})
    assert r.status_code == 400
    csrf_login(client)


def test_state_changing_actions_need_csrf(csrf_app):
    make_user()
    client = csrf_login(csrf_app.test_client())
    new_page = "/expenses/new"
    data = {"category": "Food", "amount": "10", "expense_date": date.today().isoformat(), "description": "x"}

    assert client.post(new_page, data=data).status_code == 400
    assert db.session.execute(select(Expense)).first() is None
    assert client.post(new_page, data={**data, "csrf_token": csrf_token(client, new_page)}).status_code == 302
    exp = db.session.execute(select(Expense)).scalar_one()

    assert client.post(f"/expenses/{exp.id}/edit", data=data).status_code == 400
    assert client.post(f"/expenses/{exp.id}/delete").status_code == 400
    assert db.session.get(Expense, exp.id) is not None
    assert client.post("/account/password", data={"current_password": PASSWORD, "new_password": "Another-pass-1", "confirm_password": "Another-pass-1"}).status_code == 400
    assert client.post("/account/profile", data={"username": "Evil", "email": "ada@example.com"}).status_code == 400

    token = csrf_token(client, "/expenses/")
    assert client.post(f"/expenses/{exp.id}/delete", data={"csrf_token": token}).status_code == 302
    assert db.session.get(Expense, exp.id) is None


def test_logout_needs_csrf_token(csrf_app):
    make_user()
    client = csrf_login(csrf_app.test_client())
    assert client.post("/logout").status_code == 400
    assert client.get("/dashboard").status_code == 200  # still signed in
    token = csrf_token(client, "/dashboard")
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_every_post_form_in_the_ui_carries_a_token(csrf_app):
    make_user()
    client = csrf_login(csrf_app.test_client())
    for url in ["/dashboard", "/expenses/new", "/account/", "/analytics/"]:
        html = client.get(url).get_data(as_text=True)
        for form in re.findall(r"<form[^>]*method=\"post\".*?</form>", html, flags=re.S | re.I):
            assert 'name="csrf_token"' in form, f"{url}: {form[:80]}"


# --- XSS --------------------------------------------------------------------------------------
@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_descriptions_are_escaped_everywhere(auth_client, payload):
    assert add_expense(auth_client, description=payload[:255]).status_code == 302
    exp = db.session.execute(select(Expense)).scalar_one()
    for url in ["/expenses/", "/dashboard", f"/expenses/{exp.id}/edit"]:
        html = auth_client.get(url).get_data(as_text=True)
        assert payload not in html, f"unescaped payload on {url}"
        assert "&lt;" in html or "&#39;" in html or "&#34;" in html


def test_xss_in_search_term_is_escaped(auth_client):
    html = auth_client.get("/expenses/", query_string={"q": "<script>alert(1)</script>"}).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_markup_cannot_be_registered_as_username(client):
    r = client.post("/register", data={"username": "<script>alert(1)</script>", "email": "x@example.com", "password": PASSWORD, "confirm_password": PASSWORD})
    assert r.status_code == 400


def test_no_inline_scripts_or_styles_in_pages(auth_client):
    add_expense(auth_client)
    for url in ["/dashboard", "/expenses/", "/expenses/new", "/analytics/", "/account/", "/login"]:
        html = auth_client.get(url).get_data(as_text=True)
        assert not re.search(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", html), url
        assert not re.search(r"\sstyle=", html), url
        assert not re.search(r"\son(click|load|error|submit)=", html, flags=re.I), url


# --- headers, cookies, config --------------------------------------------------------------------
def test_security_headers(auth_client):
    r = auth_client.get("/dashboard")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
    assert "Referrer-Policy" in r.headers


def test_session_cookie_flags(app, user):
    client = app.test_client()
    r = login(client)
    cookie = next(c for c in r.headers.getlist("Set-Cookie") if c.startswith("u_session="))
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_production_config_hardens_cookies_and_requires_secret():
    overrides = {"SECRET_KEY": "x" * 40, "SQLALCHEMY_DATABASE_URI": "sqlite://", "LOG_TO_FILE": False}
    app = create_app("production", overrides)
    assert app.config["SESSION_COOKIE_SECURE"] is True and app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_NAME"].startswith("__Host-") and app.config["DEBUG"] is False
    with app.app_context():
        db.create_all()
    r = app.test_client().get("/login", base_url="https://localhost")
    assert "max-age=" in r.headers["Strict-Transport-Security"]
    assert "Secure" in " ".join(r.headers.getlist("Set-Cookie"))
    with pytest.raises(RuntimeError):
        create_app("production", {"SECRET_KEY": None, "LOG_TO_FILE": False})


def test_secret_key_is_not_hard_coded_in_source():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    for path in list((root / "app").rglob("*.py")) + [root / ".env.example"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"SECRET_KEY\s*=\s*['\"][^'\"]{8,}['\"]", text) or path.name == "config.py", path


# --- safe errors and logging ------------------------------------------------------------------------
def test_unhandled_error_shows_generic_page(app):
    @app.route("/boom")
    def boom():
        raise RuntimeError("secret internal detail /etc/passwd")

    app.config["PROPAGATE_EXCEPTIONS"] = False
    r = app.test_client().get("/boom")
    assert r.status_code == 500
    body = r.get_data(as_text=True)
    assert "Something went wrong" in body and "secret internal detail" not in body and "Traceback" not in body


def test_not_found_page_is_generic(auth_client):
    r = auth_client.get("/does-not-exist")
    assert r.status_code == 404 and b"Traceback" not in r.data and b"Page not found" in r.data


def test_logs_never_contain_passwords_or_email_addresses(client, user, caplog):
    caplog.set_level(logging.INFO)
    login(client, email="victim@example.com", password="Super-secret-Pw-1")
    login(client)
    assert "Super-secret-Pw-1" not in caplog.text and PASSWORD not in caplog.text
    assert "victim@example.com" not in caplog.text and "ada@example.com" not in caplog.text
    assert "auth.login_failed" in caplog.text


def test_account_page_lists_security_information(auth_client):
    login(auth_client.application.test_client(), password="wrong-Pass-1")  # one failed attempt
    html = auth_client.get("/account/").get_data(as_text=True)
    assert "Security information" in html and "Recent sign-in activity" in html and "Signed in" in html
    assert "pbkdf2" in html and "Member since" in html
