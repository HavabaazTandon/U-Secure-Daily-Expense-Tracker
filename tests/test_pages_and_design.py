"""Every page renders, static assets are served, and the colour system is respected."""
import colorsys
import re
from pathlib import Path

import pytest

from .conftest import add_expense

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def test_all_pages_render_for_signed_in_user(auth_client):
    add_expense(auth_client)
    for url in ["/dashboard", "/expenses/", "/expenses/new", "/analytics/", "/account/"]:
        r = auth_client.get(url)
        assert r.status_code == 200, url
        assert b"U Personal Finance" in r.data


def test_public_pages_render(client):
    for url in ["/login", "/register"]:
        assert client.get(url).status_code == 200


def test_signed_in_user_is_redirected_away_from_auth_pages(auth_client):
    assert auth_client.get("/login").status_code == 302
    assert auth_client.get("/register").status_code == 302


def test_static_assets_are_served(client):
    for path in [
        "css/u.css", "css/fonts.css", "js/u.js", "js/charts.js", "img/favicon.svg",
        "vendor/bootstrap/bootstrap.min.css", "vendor/bootstrap/bootstrap.bundle.min.js", "vendor/chartjs/chart.umd.js",
        "fonts/manrope-latin-wght-normal.woff2", "fonts/dm-sans-latin-wght-normal.woff2",
    ]:
        r = client.get(f"/static/{path}")
        assert r.status_code == 200, path
        assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_edit_page_has_delete_confirmation_modal(auth_client):
    add_expense(auth_client)
    html = auth_client.get("/expenses/1/edit").get_data(as_text=True)
    assert 'id="deleteModal"' in html and "Delete this expense?" in html


def test_sidebar_navigation_matches_spec(auth_client):
    html = auth_client.get("/dashboard").get_data(as_text=True)
    for label in ["Overview", "Transactions", "Add expense", "Analytics", "Account and security", "Log out"]:
        assert label in html
    assert 'aria-current="page"' in html


# --- design system guard -------------------------------------------------------------------------
HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
RGB = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
OWN_FILES = (
    [APP / "static/css/u.css", APP / "static/js/charts.js", APP / "static/js/u.js", APP / "static/img/favicon.svg", APP / "constants.py"]
    + list((APP / "templates").rglob("*.html"))
)


def _colours(text):
    for m in HEX.finditer(text):
        h = m.group(1)
        yield "#" + h.upper(), tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    for m in RGB.finditer(text):
        rgb = tuple(int(x) for x in m.groups())
        yield "rgb" + str(rgb), rgb


def _is_warm_or_neutral(rgb):
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    hue = h * 360
    return s < 0.12 or l > 0.93 or l < 0.08 or hue <= 45 or hue >= 320


def test_every_colour_in_our_own_code_is_warm_or_neutral():
    offenders = []
    for path in OWN_FILES:
        for name, rgb in _colours(path.read_text(encoding="utf-8")):
            if not _is_warm_or_neutral(rgb):
                offenders.append((path.name, name))
    assert not offenders, f"cool/off-palette colours found: {offenders}"


def test_spec_palette_is_present_in_the_stylesheet():
    css = (APP / "static/css/u.css").read_text(encoding="utf-8").upper()
    for colour in ["#F6F4F0", "#FFFFFF", "#F0EDE8", "#292725", "#858079", "#B77983", "#F3E5E7", "#E9E5DF", "#A69B91", "#94636D"]:
        assert colour in css, colour


def test_no_banned_colour_words_or_bootstrap_colour_classes():
    banned_words = re.compile(r"\b(green|blue|purple|cyan|teal|indigo|violet|magenta|lime|emerald|sky)\b", re.I)
    banned_classes = re.compile(r"\b(btn-primary|btn-success|btn-danger|btn-info|text-primary|text-success|text-danger|text-info|bg-primary|bg-success|bg-danger|bg-info|alert-(primary|success|danger|info|warning)|badge bg-)\b")
    for path in OWN_FILES:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)  # ignore comments (they state the rule)
        assert not banned_words.search(text), f"{path.name}: banned colour word"
        assert not banned_classes.search(text), f"{path.name}: default Bootstrap colour class"


def test_typography_uses_manrope_and_dm_sans():
    css = (APP / "static/css/u.css").read_text(encoding="utf-8")
    assert '"Manrope"' in css and '"DM Sans"' in css


def test_chart_colours_come_from_the_palette():
    from app.constants import CATEGORY_COLORS, COMPARISON_COLORS

    for colour in list(CATEGORY_COLORS.values()) + list(COMPARISON_COLORS.values()):
        h = colour.lstrip("#")
        assert _is_warm_or_neutral(tuple(int(h[i : i + 2], 16) for i in (0, 2, 4)))


def test_amount_input_is_text_with_decimal_keypad(auth_client):
    html = auth_client.get("/expenses/new").get_data(as_text=True)
    field = re.search(r'<input[^>]*id="amount"[^>]*>', html).group(0)
    assert 'type="text"' in field and 'inputmode="decimal"' in field
