"""Account and security centre."""
from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user

from ...extensions import db, limiter
from ...forms import ChangePasswordForm, ProfileForm
from ...models import Expense
from ...services import auth_service
from sqlalchemy import func, select

bp = Blueprint("account", __name__, url_prefix="/account")


def _password_limit():
    return current_app.config["PASSWORD_RATE_LIMIT"]


def _render(profile_form, password_form, status=200):
    expense_count = db.session.execute(
        select(func.count(Expense.id)).where(Expense.user_id == current_user.id)
    ).scalar_one()
    return (
        render_template(
            "account/index.html",
            profile_form=profile_form,
            password_form=password_form,
            activity=auth_service.recent_activity(current_user.email),
            failed_last_day=auth_service.failed_attempts_last_day(current_user.email),
            expense_count=expense_count,
            max_failed=current_app.config["LOGIN_MAX_FAILED_ATTEMPTS"],
            lockout_minutes=current_app.config["LOGIN_LOCKOUT_MINUTES"],
        ),
        status,
    )


@bp.route("/")
@login_required
def index():
    return _render(ProfileForm(obj=current_user), ChangePasswordForm())


@bp.route("/profile", methods=["POST"])
@login_required
def update_profile():
    form = ProfileForm()
    if form.validate_on_submit():
        new_email = auth_service.normalize_email(form.email.data)
        if new_email != current_user.email:
            # Changing the sign-in address needs the current password.
            if not form.current_password.data or not current_user.check_password(form.current_password.data):
                form.current_password.errors.append("Enter your current password to change your email.")
                return _render(form, ChangePasswordForm(), 400)
            current_user.email = new_email
        current_user.username = form.username.data
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("account.index"))
    return _render(form, ChangePasswordForm(), 400)


@bp.route("/password", methods=["POST"])
@login_required
@limiter.limit(_password_limit, methods=["POST"])
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors.append("Your current password is incorrect.")
        elif form.current_password.data == form.new_password.data:
            form.new_password.errors.append("Choose a password different from the current one.")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            login_user(current_user._get_current_object())  # refresh this session; every other session is signed out
            current_app.logger.info("account.password_changed user_id=%s", current_user.id)
            flash("Password updated. Other devices have been signed out.", "success")
            return redirect(url_for("account.index"))
    return _render(ProfileForm(obj=current_user), form, 400)
