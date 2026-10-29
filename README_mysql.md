# Migration 001 Review Pack

This pack is meant to be copied into the existing `airline_contact_center_ai` project root. It adds the first reviewed SQL migration, reference seed, static tests, and a manual review checklist. It does **not** execute SQL or change any database.

## Copy into the existing project

Preserve the relative paths:

- `database/migrations/001_create_core_schema.sql`
- `database/seeds/001_core_reference_data.sql`
- `docs/migration_001_review_checklist.md`
- `tests/test_migration_001_sql.py`
- `tests/test_core_reference_seed_sql.py`

Do not overwrite your `.env`, connection code, or existing tests.

## Run the static tests first

From the project's root with `.venv` active:

```powershell
python -m pytest tests/test_migration_001_sql.py tests/test_core_reference_seed_sql.py -q
```

These are static file checks, not a live MySQL integration test. Read `docs/migration_001_review_checklist.md` before executing SQL manually.
