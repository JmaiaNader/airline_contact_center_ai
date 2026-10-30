# AeroInsight Migration 003 — Direct db_airlines package

This package targets the existing `db_airlines` database directly. It avoids a separate test-database cycle as requested, while keeping a read-only preflight and postflight verification.

## Files

- `database/migrations/003_identity_access_control.sql` — additive identity and tenant access schema.
- `database/checks/003_preflight.sql` — read-only prerequisites check.
- `database/checks/003_postflight.sql` — read-only result checks.
- `docs/migration_003_identity_access_review.md` — scope and security boundaries.

## Apply

1. Ensure MySQL Workbench is connected to your local MySQL 26.7.0 server.
2. Open `database/checks/003_preflight.sql` and execute it. Confirm Migration 002 prerequisites exist and none of the nine Migration 003 tables already exist. If any Migration 003 table is already present, stop and inspect before continuing.
3. Open `database/migrations/003_identity_access_control.sql`. Confirm its first `USE` statement is `USE `db_airlines`;`.
4. Execute the entire script once using a developer/DBA account.
5. If any SQL error occurs, stop. Do not rerun blindly; inspect the partial state first.
6. If successful, run `database/checks/003_postflight.sql`.

The migration creates new tables only; it does not alter Migration 001 or Migration 002 tables. MySQL DDL implicitly commits, so a failure may leave some new tables created.

## Important

This provides the database foundation only. It does not create a working login flow or enforce authorization in Python. Do not onboard real users until OIDC authentication, membership checks, tenant-context enforcement, and authorization tests are implemented.
