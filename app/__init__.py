"""Application factory for U - Secure Daily Expense Tracker."""
from __future__ import annotations

import logging
import os
import secrets
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import BASE_DIR, config_by_name
from .constants import CATEGORIES, CATEGORY_COLORS
from .extensions import csrf, db, limiter, login_manager
from .utils import format_money, money_parts

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


def create_app(config_name: str | None = None, overrides: dict | None = None) -> Flask:
    config_name = config_name or os.environ.get("APP_ENV", "development")
    if config_name not in config_by_name:
        raise ValueError(f"Unknown APP_ENV '{config_name}'. Use one of: {', '.join(config_by_name)}")

    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.from_object(config_by_name[config_name])
    if overrides:
        app.config.update(overrides)

    _ensure_secret_key(app)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    if app.config["TRUSTED_PROXY_COUNT"] > 0:
        n = app.config["TRUSTED_PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    _configure_logging(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_template_helpers(app)
    _register_security_headers(app)
    _register_error_handlers(app)
    _register_cli(app)
    return app


# ---------------------------------------------------------------------------
def _ensure_secret_key(app: Flask) -> None:
    if app.config.get("SECRET_KEY"):
        return
    if app.config["ENV_NAME"] == "production":
        raise RuntimeError("SECRET_KEY is not set. Create a .env file (see .env.example) before running in production.")
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    logging.getLogger(__name__).warning(
        "SECRET_KEY not set - using a temporary key. Sessions will reset on restart."
    )


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "strong"

    from . import models  # noqa: F401  (registers the user loader and tables)


def _register_blueprints(app: Flask) -> None:
    from .blueprints.account.routes import bp as account_bp
    from .blueprints.analytics.routes import bp as analytics_bp
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.expenses.routes import bp as expenses_bp
    from .blueprints.main.routes import bp as main_bp

    for blueprint in (auth_bp, main_bp, expenses_bp, analytics_bp, account_bp):
        app.register_blueprint(blueprint)


def _register_template_helpers(app: Flask) -> None:
    app.add_template_filter(lambda v: format_money(v, app.config["CURRENCY_SYMBOL"]), "money")
    app.add_template_filter(lambda v: money_parts(v, app.config["CURRENCY_SYMBOL"]), "money_parts")
    app.add_template_filter(lambda d: d.strftime("%d %b %Y").lstrip("0") if d else "", "fmt_date")
    app.add_template_filter(lambda d: d.strftime("%d %b").lstrip("0") if d else "", "fmt_day")
    app.add_template_filter(lambda d: d.strftime("%d %b %Y, %H:%M UTC").lstrip("0") if d else "", "fmt_datetime")

    @app.context_processor
    def inject_globals():
        return {
            "CATEGORIES": CATEGORIES,
            "CATEGORY_COLORS": CATEGORY_COLORS,
            "currency_symbol": app.config["CURRENCY_SYMBOL"],
            "today_iso": date.today().isoformat(),
        }


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def add_security_headers(response):
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.endpoint != "static":
            # Pages hold financial data: never let the browser or a proxy cache them.
            headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def _register_error_handlers(app: Flask) -> None:
    def render_error(code: int, title: str, message: str):
        return render_template("errors/error.html", code=code, title=title, message=message), code

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        app.logger.warning("security.csrf_rejected endpoint=%s", request.endpoint)
        return render_error(
            400,
            "Security check failed",
            "Your form could not be verified, usually because the page was open for too long. "
            "Go back, reload the page and try again.",
        )

    @app.errorhandler(400)
    def bad_request(error):
        return render_error(400, "Request not understood", "The request could not be processed. Please go back and try again.")

    @app.errorhandler(403)
    def forbidden(error):
        return render_error(403, "Access denied", "You do not have permission to view this page.")

    @app.errorhandler(404)
    def not_found(error):
        return render_error(404, "Page not found", "That page does not exist, or it is not part of your account.")

    @app.errorhandler(405)
    def method_not_allowed(error):
        return render_error(405, "Action not allowed", "This address does not accept that kind of request.")

    @app.errorhandler(429)
    def too_many_requests(error):
        app.logger.warning("security.rate_limited endpoint=%s", request.endpoint)
        return render_error(
            429, "Too many requests", "You have made too many requests in a short time. Wait a minute, then try again."
        )

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        app.logger.error("server.error endpoint=%s", request.endpoint, exc_info=error)
        return render_error(500, "Something went wrong", "An unexpected error occurred. Your data was not changed.")


def _configure_logging(app: Flask) -> None:
    if app.config.get("LOG_TO_FILE") and not app.debug:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = RotatingFileHandler(log_dir / "u_app.log", maxBytes=512_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _register_cli(app: Flask) -> None:
    import click

    @app.cli.command("init-db")
    @click.option("--reset", is_flag=True, help="Drop all tables first (destroys data).")
    def init_db_command(reset: bool):
        """Create the database tables."""
        if reset:
            if not click.confirm("This deletes ALL data. Continue?"):
                raise click.Abort()
            db.drop_all()
        db.create_all()
        click.echo("Database initialised.")
