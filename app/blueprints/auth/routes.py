"""Registration, login and logout."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ...extensions import limiter
from ...forms import DeleteForm, LoginForm, RegisterForm
from ...services import auth_service
from ...utils import fingerprint, is_safe_redirect_target

bp = Blueprint("auth", __name__)

GENERIC_LOGIN_ERROR = "Incorrect email or password."


def _login_limit():
    return current_app.config["LOGIN_RATE_LIMIT"]


def _register_limit():
    return current_app.config["REGISTER_RATE_LIMIT"]


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit(_register_limit, methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        user = auth_service.create_user(form.username.data, form.email.data, form.password.data)
        current_app.logger.info("auth.registered user_id=%s", user.id)
        flash("Your account is ready. Sign in to start recording expenses.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form), (400 if form.errors else 200)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(_login_limit, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        email = auth_service.normalize_email(form.email.data)

        if auth_service.is_locked_out(email):
            current_app.logger.warning("auth.locked_out email_fp=%s ip=%s", fingerprint(email), request.remote_addr)
            minutes = current_app.config["LOGIN_LOCKOUT_MINUTES"]
            form.password.errors.append(
                f"Too many unsuccessful attempts. Wait {minutes} minutes before trying again."
            )
            return render_template("auth/login.html", form=form), 429

        user = auth_service.verify_credentials(email, form.password.data)
        if user is None:
            auth_service.record_login_attempt(email, success=False)
            current_app.logger.warning("auth.login_failed email_fp=%s ip=%s", fingerprint(email), request.remote_addr)
            form.password.errors.append(GENERIC_LOGIN_ERROR)
            return render_template("auth/login.html", form=form), 401

        auth_service.record_login_attempt(email, success=True)
        auth_service.prune_old_attempts()
        session.clear()  # drop any pre-login session data (prevents session fixation)
        login_user(user)
        session.permanent = True
        current_app.logger.info("auth.login_ok user_id=%s", user.id)
        flash(f"Welcome back, {user.username}.", "success")
        next_url = request.args.get("next")
        return redirect(next_url if is_safe_redirect_target(next_url) else url_for("main.dashboard"))
    return render_template("auth/login.html", form=form), (400 if form.errors else 200)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # DeleteForm only verifies the CSRF token; CSRFProtect also checks it globally.
    form = DeleteForm()
    if not form.validate_on_submit():
        flash("Could not sign you out. Please try again.", "error")
        return redirect(url_for("main.dashboard"))
    current_app.logger.info("auth.logout user_id=%s", current_user.id)
    logout_user()
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
