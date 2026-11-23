"""Authentication business logic: user creation, login-attempt monitoring."""
from __future__ import annotations

from datetime import timedelta

from flask import current_app
from sqlalchemy import delete, func, select
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import LoginAttempt, User
from ..utils import utcnow

_DUMMY_HASH: dict[str, str] = {}


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def get_user_by_email(email: str) -> User | None:
    return db.session.execute(
        select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()


def create_user(username: str, email: str, password: str) -> User:
    user = User(username=username.strip(), email=normalize_email(email))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def verify_credentials(email: str, password: str) -> User | None:
    """Check credentials in (roughly) constant time.

    For unknown e-mails we still verify against a dummy hash, so response time
    does not reveal whether an account exists.
    """
    user = get_user_by_email(email)
    if user is None:
        method = current_app.config.get("PASSWORD_HASH_METHOD", "scrypt")
        dummy = _DUMMY_HASH.get(method)
        if dummy is None:
            dummy = _DUMMY_HASH[method] = generate_password_hash("not-a-real-password", method=method)
        check_password_hash(dummy, password)
        return None
    return user if user.check_password(password) else None


# --------------------------------------------------------------------------
# Login attempt monitoring
# --------------------------------------------------------------------------
def record_login_attempt(email: str, success: bool) -> None:
    db.session.add(LoginAttempt(email=normalize_email(email), success=success))
    db.session.commit()


def failed_attempts_in_window(email: str, now=None) -> int:
    """Failed attempts in the lock-out window, ignoring those before the last success."""
    email = normalize_email(email)
    now = now or utcnow()
    window = timedelta(minutes=current_app.config["LOGIN_LOCKOUT_MINUTES"])
    last_success = db.session.execute(
        select(func.max(LoginAttempt.attempted_at)).where(
            LoginAttempt.email == email, LoginAttempt.success.is_(True)
        )
    ).scalar()
    since = now - window
    if last_success and last_success > since:
        since = last_success
    return db.session.execute(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.email == email,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at > since,
        )
    ).scalar_one()


def is_locked_out(email: str, now=None) -> bool:
    return failed_attempts_in_window(email, now) >= current_app.config["LOGIN_MAX_FAILED_ATTEMPTS"]


def recent_activity(email: str, limit: int = 8) -> list[LoginAttempt]:
    return list(
        db.session.execute(
            select(LoginAttempt)
            .where(LoginAttempt.email == normalize_email(email))
            .order_by(LoginAttempt.attempted_at.desc(), LoginAttempt.id.desc())
            .limit(limit)
        ).scalars()
    )


def failed_attempts_last_day(email: str, now=None) -> int:
    now = now or utcnow()
    return db.session.execute(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.email == normalize_email(email),
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at > now - timedelta(days=1),
        )
    ).scalar_one()


def prune_old_attempts(days: int = 90) -> None:
    db.session.execute(
        delete(LoginAttempt).where(LoginAttempt.attempted_at < utcnow() - timedelta(days=days))
    )
    db.session.commit()
