# AeroInsight Migration 002 Review Pack

This archive is for the `airline_contact_center_ai` project only.

**Status: review draft. Do not run the SQL until the preflight checks, backup, and documented tenant-assignment decision are complete.** It has not been executed against the user's MySQL server.

Contents:
- `database/migrations/002_tenant_source_lineage_historical_metrics.sql` — migration draft
- `database/checks/002_preflight.sql` — read-only checks to run first
- `database/checks/002_postflight.sql` — read-only checks to run after successful execution
- `docs/migration_002_review.md` — scope, assumptions, risks, and manual run procedure
- `tests/test_migration_002_sql.py` — static contract tests; these do not execute SQL against MySQL

## Run the static review tests in the project root

After copying these additive files into your project, with the virtual environment activated:

```powershell
python -m pytest tests/test_migration_002_sql.py -q
```

These tests check the intended SQL contract only. They are not a replacement for testing the migration on a restorable local database copy.
