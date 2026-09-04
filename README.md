# Entertainment Control System — MVP v3

Flask web application for entertainment request submission, manager approval, admin budget control, and one-page Entertainment Form PDF output.

## V3 updates
- Added **Sugity Member** input (up to 7 names) and integrated it into the lower Entertainment Form section.
- Customer names and levels are automatically formatted in the PDF as **Name (Level)**.
- Rebuilt the PDF lower section to follow the supplied format: **Sugity Members / Proposed Division (MGR, GM, DIR; PLAN, ACTUAL) / Accounting**.
- Replaced the single-month budget comparison with a **6-month monthly chart** showing approved entertainment as bars and Accounting budget as a red line.
- Existing v2 data is migrated automatically; the new `sugity_members` table is created on startup.

## Demo accounts
- Member: `member` / `member123`
- Manager: `manager` / `manager123`
- Admin: `admin` / `admin123`

## Run
```bash
pip install -r requirements.txt
gunicorn app:app
```

For production company use, migrate SQLite to persistent PostgreSQL/object storage and change all demo credentials.
