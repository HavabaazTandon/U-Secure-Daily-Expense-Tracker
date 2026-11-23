"""WTForms definitions. Every rule here is enforced on the server."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import current_app
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, PasswordField, RadioField, StringField, TextAreaField
from wtforms.fields import SelectChoice
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    InputRequired,
    Length,
    Optional,
    Regexp,
    StopValidation,
    ValidationError,
)

from .constants import CATEGORIES
from .models import User
from .services.auth_service import normalize_email
from .extensions import db
from sqlalchemy import select

COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "qwerty123",
    "iloveyou1", "admin123", "welcome123", "letmein123", "abc12345", "11111111",
}
EARLIEST_EXPENSE_DATE = date(2000, 1, 1)


# ---------------------------------------------------------------------------
# Custom validators / fields
# ---------------------------------------------------------------------------
def password_strength(form, field):
    value = field.data or ""
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        raise ValidationError("Use at least one letter and one number.")
    if value.lower() in COMMON_PASSWORDS:
        raise ValidationError("That password is too common. Choose something less guessable.")


def positive_amount(form, field):
    value = field.data
    if value is None:  # parsing already failed; its message is shown
        raise StopValidation()
    maximum = Decimal(str(current_app.config["MAX_EXPENSE_AMOUNT"]))
    if value <= 0:
        raise ValidationError("Amount must be greater than zero.")
    if value > maximum:
        raise ValidationError("Amount is too large for a single expense.")
    if value != value.quantize(Decimal("0.01")):
        raise ValidationError("Use at most two decimal places.")


def sensible_date(form, field):
    if field.data is None:
        raise StopValidation()
    # +1 day tolerates the user's local date being ahead of the server clock.
    if field.data > date.today() + timedelta(days=1):
        raise ValidationError("The date cannot be in the future.")
    if field.data < EARLIEST_EXPENSE_DATE:
        raise ValidationError("The date is too far in the past.")


class MoneyField(DecimalField):
    """Decimal input that tolerates commas and rejects NaN / Infinity."""

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        raw = valuelist[0].strip().replace(",", "").replace(" ", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            self.data = None
            raise ValueError("Enter an amount using digits, for example 249.50.")
        if not value.is_finite():
            self.data = None
            raise ValueError("Enter an amount using digits, for example 249.50.")
        self.data = value


class CategoryField(RadioField):
    """Radio group that only accepts the fixed category list."""

    def pre_validate(self, form):
        if self.data is None:
            return  # InputRequired reports the missing choice
        if self.data not in CATEGORIES:
            raise ValidationError("Choose one of the available categories.")


def _email_taken(email: str, exclude_user_id: int | None = None) -> bool:
    stmt = select(User.id).where(User.email == normalize_email(email))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return db.session.execute(stmt).first() is not None


USERNAME_RULE = Regexp(
    r"^[A-Za-z0-9 ._-]+$", message="Use letters, numbers, spaces, dots, dashes or underscores."
)


# ---------------------------------------------------------------------------
# Authentication forms
# ---------------------------------------------------------------------------
class RegisterForm(FlaskForm):
    username = StringField(
        "Full name or username",
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
        validators=[
            DataRequired("Enter a name."),
            Length(min=2, max=30, message="Use between 2 and 30 characters."),
            USERNAME_RULE,
        ],
    )
    email = StringField(
        "Email address",
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
        validators=[
            DataRequired("Enter your email address."),
            Length(max=254),
            Email("Enter a valid email address."),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired("Create a password."),
            Length(min=8, max=128, message="Use between 8 and 128 characters."),
            password_strength,
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired("Repeat the password."), EqualTo("password", "Passwords do not match.")],
    )

    def validate_email(self, field):
        if _email_taken(field.data):
            raise ValidationError("An account with this email already exists.")


class LoginForm(FlaskForm):
    email = StringField(
        "Email address",
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
        validators=[DataRequired("Enter your email address."), Length(max=254)],
    )
    password = PasswordField("Password", validators=[DataRequired("Enter your password."), Length(max=128)])


# ---------------------------------------------------------------------------
# Expense forms
# ---------------------------------------------------------------------------
class ExpenseForm(FlaskForm):
    category = CategoryField(
        "Category",
        choices=[SelectChoice(c, c) for c in CATEGORIES],
        validators=[InputRequired("Choose a category.")],
    )
    amount = MoneyField(
        "Amount",
        places=2,
        validators=[InputRequired("Enter an amount."), positive_amount],
    )
    expense_date = DateField(
        "Date",
        format="%Y-%m-%d",
        validators=[InputRequired("Pick a date."), sensible_date],
    )
    description = TextAreaField(
        "Description",
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
        validators=[Optional(), Length(max=255, message="Keep the description under 255 characters.")],
    )


class DeleteForm(FlaskForm):
    """Empty form: exists only to carry and verify the CSRF token."""


# ---------------------------------------------------------------------------
# Account forms
# ---------------------------------------------------------------------------
class ProfileForm(FlaskForm):
    username = StringField(
        "Name",
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
        validators=[
            DataRequired("Enter a name."),
            Length(min=2, max=30, message="Use between 2 and 30 characters."),
            USERNAME_RULE,
        ],
    )
    email = StringField(
        "Email address",
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
        validators=[DataRequired("Enter your email address."), Length(max=254), Email("Enter a valid email address.")],
    )
    current_password = PasswordField("Current password", validators=[Optional(), Length(max=128)])

    def validate_email(self, field):
        if _email_taken(field.data, exclude_user_id=current_user.id):
            raise ValidationError("Another account already uses this email.")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current password", validators=[DataRequired("Enter your current password."), Length(max=128)]
    )
    new_password = PasswordField(
        "New password",
        validators=[
            DataRequired("Enter a new password."),
            Length(min=8, max=128, message="Use between 8 and 128 characters."),
            password_strength,
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired("Repeat the new password."), EqualTo("new_password", "Passwords do not match.")],
    )
