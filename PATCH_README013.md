# AeroInsight WFM Foundation v1

This package adds Migration 005 for the existing `db_airlines` database.

## Included
- `database/migrations/005_wfm_workforce_foundation.sql`
- `database/checks/005_preflight.sql`
- `database/checks/005_postflight.sql`
- `docs/wfm_foundation_v1.md`
- `tests/test_migration_005_wfm_sql.py`

## Apply in order
1. Extract this ZIP into the project root.
2. Run `python -m pytest tests/test_migration_005_wfm_sql.py -q`.
3. Run `database/checks/005_preflight.sql` in MySQL Workbench.
4. Confirm the target schema is `db_airlines`, required parent tables exist, all seven target tables are absent, and WFM permissions are present.
5. Run `database/migrations/005_wfm_workforce_foundation.sql` once.
6. Run `database/checks/005_postflight.sql`.

This package does not create employees or schedules and does not modify prior migrations. It seeds only language/channel skill catalog entries from existing tenant and reference data. It adds no demo operational metrics.
