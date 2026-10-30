# AeroInsight Migration 002 — Foreign-Key Naming Fix

This ZIP contains updated project files for `airline_contact_center_ai`. It is a replacement patch, not a standalone project.

## Files included

- `database/migrations/002_tenant_source_lineage_historical_metrics.sql` — corrected replacement foreign-key names.
- `tests/test_migration_002_sql.py` — adds a regression test for the duplicate-name defect.
- `docs/migration_002_review.md` — documents the correction and clean-schema test requirement.

## Apply the patch

Extract this ZIP into the project root:

`C:\Users\nader\Desktop\airline_contact_center_ai`

The archive keeps the original directory structure and replaces only the three files listed above. Then inspect the changes with:

```powershell
git diff -- database/migrations/002_tenant_source_lineage_historical_metrics.sql tests/test_migration_002_sql.py docs/migration_002_review.md
```

Run the static migration tests:

```powershell
python -m pytest tests/test_migration_002_sql.py -q
```

Expected: `12 passed`. Then run the full project test suite:

```powershell
python -m pytest -q
```

## Critical execution warning

The corrected migration is intended for a **clean schema restored from the pre-Migration-002 backup**. Do not run it against the current `db_airlines_migration_test` schema: that schema already contains a partial execution of the original migration and a repair script. Do not run it against `db_airlines` yet. First create a fresh test schema from the backup, verify the restore, and run the corrected migration once on that fresh test schema. MySQL DDL can partially commit; do not rerun the migration blindly after any error.

This migration establishes tenant-scoped schema relationships; it does not by itself implement user authentication, authorization, repository-level tenant filtering, or complete tenant isolation.
