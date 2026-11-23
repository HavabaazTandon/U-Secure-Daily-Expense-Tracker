# Manual / browser verification record

What was actually done, where, and what was **not** done.

## Environment
Linux (Ubuntu 24), Python 3.12.3, headless Chromium driven by Playwright. Windows, Firefox, Safari and physical mobile devices were **not** available.

## 1. Clean-install check
A fresh virtual environment was created, `pip install -r requirements.txt` was run, `flask --app run init-db` created the database, and the test suite and application start-up were run from that environment (result recorded at the end of this file).

## 2. Real-browser end-to-end run (31 checks, all passed)
Script outline (see `BROWSER_CHECK_RESULTS.txt` for the raw output): anonymous redirect → registration with weak password rejected → registration → wrong password → login → empty-state dashboard → form validation messages → add three expenses through the real form (including `1,250.50`) → search, clear, category filter → edit → delete modal (summary text, cancel keeps rows, confirm removes) → dashboard and analytics canvases contain drawn pixels → analytics ranges 3/12/all → password change → logout → protected page blocked → back-button shows no private data → old password rejected, new accepted → database check (2 rows, hashed password).

Console messages were monitored throughout. The only messages ignored were the browser's own "Failed to load resource … 400/401" lines, which Chromium prints for the deliberate invalid-form and wrong-password submissions in the script; no CSP violations or JavaScript errors occurred.

## 3. Visual checks
Screenshots at 1440 px and 390 px were reviewed for every main page. Mobile pages (Overview, Transactions, Analytics, Account, Add expense) were measured with `scrollWidth == clientWidth` (no horizontal overflow). Screenshots use sample data created only for that purpose.

## 4. Issues found by this process and fixed
* The amount field rendered as `type="number"` (no comma entry, spinner arrows) → changed to a text input with a decimal keypad; a regression test was added.
* Test fixtures leaked Flask-Login / CSRF state between requests through `flask.g` → request state is cleared before each test request.
* Doughnut charts and monthly labels were reviewed in the browser and the label format was shortened to avoid rotated text.

## 5. Not verified
Windows PowerShell commands, other browsers/devices, screen-reader behaviour, load/performance, HTTPS deployment behind a real reverse proxy, Redis rate-limit storage.

## 6. To repeat the browser checks yourself
Run the app (`python run.py`), register an account, and walk through the steps in section 2 manually; every step is a normal user action.

## Clean-install result (recorded)
Fresh virtual environment, `pip install -r requirements.txt` (Flask 3.1.3, Flask-SQLAlchemy 3.1.1, Flask-Login 0.6.3, Flask-WTF 1.3.0, Flask-Limiter 4.1.1, SQLAlchemy 2.1.9, Werkzeug 3.1.9, pytest 9.2.0) → `.env` copied from `.env.example` with a generated `SECRET_KEY` → `python -m pytest -q`: **128 passed** → `flask --app run init-db`: "Database initialised." (`instance/u_expense_tracker.db` created) → `python run.py`: server started, `GET /login` returned 200 and `GET /dashboard` returned 302 (redirect to sign-in) for an anonymous visitor. Linux only.
