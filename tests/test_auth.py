"""Module 1: authentication, sessions, brute-force protection."""
from sqlalchemy import select

from app.extensions import db
from app.models import LoginAttempt, User

from .conftest import PASSWORD, login, make_user


def register(client, email="new@example.com", username="Newbie", password=PASSWORD, confirm=None):
    return client.post(
        "/register",
        data={"username": username, "email": email, "password": password, "confirm_password": confirm or password},
    )


# 1. Registration ----------------------------------------------------------
def test_registration_creates_user_and_redirects_to_login(client):
    response = register(client)
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    user = db.session.execute(select(User).where(User.email == "new@example.com")).scalar_one()
    assert user.username == "Newbie"


def test_registration_normalises_email_case(client):
    register(client, email="  MiXed@Example.COM ")
    assert db.session.execute(select(User).where(User.email == "mixed@example.com")).scalar_one()


def test_registration_validates_input(client):
    assert register(client, email="not-an-email").status_code == 400
    assert register(client, password="short1").status_code == 400
    assert register(client, password="onlyletters").status_code == 400
    assert register(client, password="password123").status_code == 400  # too common
    assert register(client, confirm="Different-pass-1").status_code == 400
    assert db.session.execute(select(User)).first() is None


# 2. Duplicate e-mail ------------------------------------------------------
def test_duplicate_email_is_rejected(client, user):
    response = register(client, email="ADA@example.com")
    assert response.status_code == 400
    assert b"already exists" in response.data
    assert len(db.session.execute(select(User)).scalars().all()) == 1


# 3. Password hashing ------------------------------------------------------
def test_password_is_hashed_never_plaintext(user):
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("pbkdf2:")  # scrypt in production, fast PBKDF2 in the test config
    assert user.check_password(PASSWORD)
    assert not user.check_password("wrong-password-1")


def test_same_password_gets_different_salt(app):
    a = make_user("a@example.com", "A")
    b = make_user("b@example.com", "B")
    assert a.password_hash != b.password_hash


# 4. Successful login ------------------------------------------------------
def test_successful_login(client, user):
    response = login(client)
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200


def test_login_is_case_insensitive_on_email(client, user):
    assert login(client, email="ADA@Example.com").status_code == 302


# 5. Incorrect login -------------------------------------------------------
def test_wrong_password_gives_generic_message(client, user):
    response = login(client, password="Wrong-pass-9")
    assert response.status_code == 401
    assert b"Incorrect email or password." in response.data


def test_unknown_email_gives_same_generic_message(client, user):
    known = login(client, password="Wrong-pass-9")
    unknown = login(client, email="nobody@example.com", password="Wrong-pass-9")
    assert unknown.status_code == known.status_code == 401
    assert b"Incorrect email or password." in unknown.data
    assert b"no account" not in unknown.data.lower()


# 6. Failed login recording ------------------------------------------------
def test_failed_and_successful_logins_are_recorded(client, user):
    login(client, password="Wrong-pass-9")
    login(client, email="nobody@example.com", password="x")
    attempts = db.session.execute(select(LoginAttempt).order_by(LoginAttempt.id)).scalars().all()
    assert [a.success for a in attempts] == [False, False]
    assert {a.email for a in attempts} == {"ada@example.com", "nobody@example.com"}
    login(client)
    assert db.session.execute(select(LoginAttempt).order_by(LoginAttempt.id.desc())).scalars().first().success is True


def test_account_locks_after_repeated_failures_and_resets_on_success(app, client, user):
    limit = app.config["LOGIN_MAX_FAILED_ATTEMPTS"]
    for _ in range(limit):
        assert login(client, password="Wrong-pass-9").status_code == 401
    locked = login(client)  # even the correct password is refused while locked
    assert locked.status_code == 429 and b"Too many unsuccessful attempts" in locked.data
    # Lock-out is per e-mail: another account is unaffected.
    make_user("grace@example.com", "Grace")
    assert login(client, email="grace@example.com").status_code == 302


def test_failed_attempts_before_a_success_do_not_count(app, client, user):
    for _ in range(app.config["LOGIN_MAX_FAILED_ATTEMPTS"] - 1):
        login(client, password="Wrong-pass-9")
    assert login(client).status_code == 302
    client.post("/logout")
    for _ in range(app.config["LOGIN_MAX_FAILED_ATTEMPTS"] - 1):
        assert login(client, password="Wrong-pass-9").status_code == 401
    assert login(client).status_code == 302


# 7. Rate limiting ---------------------------------------------------------
def test_login_endpoint_is_rate_limited(limited_app):
    make_user()
    client = limited_app.test_client()
    codes = [login(client, password="Wrong-pass-9").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]


def test_rate_limit_applies_only_to_post(limited_app):
    client = limited_app.test_client()
    assert all(client.get("/login").status_code == 200 for _ in range(10))


# 8. Protected routes ------------------------------------------------------
def test_protected_pages_redirect_anonymous_users(client):
    for url in ["/dashboard", "/expenses/", "/expenses/new", "/analytics/", "/account/"]:
        response = client.get(url)
        assert response.status_code == 302, url
        assert "/login" in response.headers["Location"], url


def test_post_endpoints_require_login(client):
    for url in ["/expenses/new", "/expenses/1/delete", "/account/profile", "/account/password", "/logout"]:
        assert client.post(url).status_code == 302, url


# 9. Logout ----------------------------------------------------------------
def test_logout_ends_session(auth_client):
    response = auth_client.post("/logout")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    assert auth_client.get("/dashboard").status_code == 302


def test_logout_rejects_get(auth_client):
    assert auth_client.get("/logout").status_code == 405
    assert auth_client.get("/dashboard").status_code == 200  # still signed in


# 10. Open redirect --------------------------------------------------------
def test_login_next_parameter_only_allows_local_paths(client, user):
    ok = client.post("/login?next=/analytics/", data={"email": "ada@example.com", "password": PASSWORD})
    assert ok.headers["Location"].endswith("/analytics/")
    client.post("/logout")
    for evil in ["https://evil.example/", "//evil.example/", "/\\evil.example", "/\t/evil", "javascript:alert(1)"]:
        r = client.post("/login", query_string={"next": evil}, data={"email": "ada@example.com", "password": PASSWORD})
        assert r.headers["Location"].endswith("/dashboard"), evil
        client.post("/logout")


# 11. Profile & password management ----------------------------------------
def test_change_password_success_and_old_password_stops_working(app, auth_client, user):
    new = "Brand-new-pass-7"
    r = auth_client.post(
        "/account/password", data={"current_password": PASSWORD, "new_password": new, "confirm_password": new}
    )
    assert r.status_code == 302
    fresh = app.test_client()
    assert login(fresh, password=PASSWORD).status_code == 401
    assert login(fresh, password=new).status_code == 302
    assert auth_client.get("/dashboard").status_code == 200  # current session survives


def test_change_password_requires_correct_current_password(auth_client):
    r = auth_client.post(
        "/account/password",
        data={"current_password": "Wrong-pass-9", "new_password": "Brand-new-pass-7", "confirm_password": "Brand-new-pass-7"},
    )
    assert r.status_code == 400 and b"current password is incorrect" in r.data


def test_change_password_signs_out_other_sessions(app, auth_client, user):
    other_device = app.test_client()
    login(other_device)
    assert other_device.get("/dashboard").status_code == 200
    new = "Brand-new-pass-7"
    auth_client.post("/account/password", data={"current_password": PASSWORD, "new_password": new, "confirm_password": new})
    assert other_device.get("/dashboard").status_code == 302


def test_update_profile_name(auth_client, user):
    r = auth_client.post("/account/profile", data={"username": "Ada L", "email": "ada@example.com"})
    assert r.status_code == 302
    assert db.session.get(User, user.id).username == "Ada L"


def test_changing_email_needs_current_password_and_stays_unique(auth_client, user, other_user):
    r = auth_client.post("/account/profile", data={"username": "Ada", "email": "new@example.com"})
    assert r.status_code == 400
    r = auth_client.post(
        "/account/profile", data={"username": "Ada", "email": "grace@example.com", "current_password": PASSWORD}
    )
    assert r.status_code == 400 and b"Another account already uses" in r.data
    r = auth_client.post(
        "/account/profile", data={"username": "Ada", "email": "new@example.com", "current_password": PASSWORD}
    )
    assert r.status_code == 302 and db.session.get(User, user.id).email == "new@example.com"
