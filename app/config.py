"""Configuration classes.

Secrets and deployment settings come from environment variables (see
``.env.example``). Nothing sensitive is hard-coded in the repository.
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_DB_PATH = (BASE_DIR / "instance" / "u_expense_tracker.db").as_posix()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class BaseConfig:
    ENV_NAME = "base"
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Sessions / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_NAME = "u_session"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # CSRF (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Rate limiting (Flask-Limiter). Use redis:// in production so counters
    # survive restarts and are shared between workers.
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute;60 per hour")
    REGISTER_RATE_LIMIT = os.environ.get("REGISTER_RATE_LIMIT", "5 per minute;20 per hour")
    PASSWORD_RATE_LIMIT = os.environ.get("PASSWORD_RATE_LIMIT", "5 per minute")

    # Brute-force protection (per e-mail, independent of the IP rate limit)
    LOGIN_MAX_FAILED_ATTEMPTS = _env_int("LOGIN_MAX_FAILED_ATTEMPTS", 5)
    LOGIN_LOCKOUT_MINUTES = _env_int("LOGIN_LOCKOUT_MINUTES", 15)

    # Passwords
    PASSWORD_HASH_METHOD = "scrypt"

    # Business rules
    MAX_EXPENSE_AMOUNT = 9999999.99
    EXPENSES_PER_PAGE = 10
    CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "\u20b9")

    # Deployment behind a reverse proxy: number of trusted proxy hops.
    TRUSTED_PROXY_COUNT = _env_int("TRUSTED_PROXY_COUNT", 0)

    LOG_TO_FILE = True
    DEBUG = False
    TESTING = False


class DevelopmentConfig(BaseConfig):
    ENV_NAME = "development"
    DEBUG = os.environ.get("FLASK_DEBUG") == "1"


class TestingConfig(BaseConfig):
    ENV_NAME = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"  # fast hashing keeps the suite quick
    LOG_TO_FILE = False


class ProductionConfig(BaseConfig):
    ENV_NAME = "production"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = "__Host-u_session"
    PREFERRED_URL_SCHEME = "https"


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
