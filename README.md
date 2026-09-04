# Entertainment Control System — MVP

A simple multi-account web application for entertainment request submission and manager approval.

## Features
- Login with role-based accounts: Member, Manager, Admin
- Member entertainment request form
- Multiple entertained persons (name + level)
- Receipt upload (JPG/JPEG/PNG/PDF)
- Manager waiting-approval list
- Approve / reject with reason
- Member request history and status
- Download approved/reviewed request as PDF
- Admin dashboard with users, status totals, and all requests
- SQLite database (single-file)

## Demo accounts
- Member: `member` / `member123`
- Manager: `manager` / `manager123`
- Admin: `admin` / `admin123`

Change these passwords before real use.

## Run on Windows / macOS / Linux
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. `python -m venv .venv`
4. Activate it:
   - Windows PowerShell: `.venv\\Scripts\\Activate.ps1`
   - macOS/Linux: `source .venv/bin/activate`
5. `pip install -r requirements.txt`
6. `python app.py`
7. Open `http://127.0.0.1:5000`

The database is created automatically as `entertainment.db` and receipts are stored in `uploads/`.
