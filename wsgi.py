"""Production entry point, e.g.  waitress-serve --listen=127.0.0.1:8000 wsgi:app"""
import os

os.environ.setdefault("APP_ENV", "production")

from app import create_app  # noqa: E402

app = create_app()
