"""Database models: users, expenses and login attempts."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import BigInteger, CheckConstraint, Index, event
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import CATEGORIES
from .extensions import db, login_manager
from .utils import utcnow


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ignores foreign keys unless this pragma is switched on."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Money(TypeDecorator):
    """Store money as integer paise: exact arithmetic, no float rounding.

    Python code works with :class:`decimal.Decimal` rupee values; the database
    column holds ``amount * 100`` as an integer.
    """

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError("Amount must be a finite number.")
        return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(int(value)) / 100).quantize(Decimal("0.01"))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    expenses = db.relationship(
        "Expense",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    # -- passwords ---------------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        method = current_app.config.get("PASSWORD_HASH_METHOD", "scrypt")
        self.password_hash = generate_password_hash(raw_password, method=method)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # -- Flask-Login -------------------------------------------------------
    def session_fingerprint(self) -> str:
        return hashlib.sha256(self.password_hash.encode("utf-8")).hexdigest()[:16]

    def get_id(self) -> str:
        """Session id = user id + password fingerprint.

        Changing the password changes the fingerprint, which signs out every
        other session that still carries the old one.
        """
        return f"{self.id}.{self.session_fingerprint()}"

    @property
    def initial(self) -> str:
        return (self.username or "U")[:1].upper()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.id}>"


@login_manager.user_loader
def load_user(session_id: str):
    user_part, _, fingerprint = (session_id or "").partition(".")
    if not user_part.isdigit() or not fingerprint:
        return None
    user = db.session.get(User, int(user_part))
    if user is None:
        return None
    if not hmac.compare_digest(user.session_fingerprint(), fingerprint):
        return None
    return user


class Expense(db.Model):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        CheckConstraint(
            "category IN (" + ", ".join(f"'{c}'" for c in CATEGORIES) + ")",
            name="ck_expenses_category_allowed",
        ),
        Index("ix_expenses_user_date", "user_id", "expense_date"),
        Index("ix_expenses_user_category", "user_id", "category"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category = db.Column(db.String(20), nullable=False)
    amount = db.Column(Money, nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="expenses")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Expense {self.id} {self.category}>"


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_email_time", "email", "attempted_at"),)

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, index=True)
    attempted_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    success = db.Column(db.Boolean, nullable=False, default=False)
