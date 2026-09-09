# Entertainment Control System V6

V6 keeps the V5 workflow/UI but moves application data from local SQLite to PostgreSQL.
Receipt files are stored as PostgreSQL BYTEA records so they do not depend on Render's ephemeral filesystem.

## Required Render environment variable
- `DATABASE_URL` = PostgreSQL connection URL (prefer Render's Internal Database URL when the database is in the same Render region/workspace)
- `SECRET_KEY` = a long random secret

## Important
Render Free Postgres is limited to 1 GB and expires after 30 days. For continuous business use, upgrade the database before expiry or use another persistent PostgreSQL provider.
