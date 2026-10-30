# Migration 002 Review — Tenant Foundation, Source Lineage, Historical Interval Metrics

**Project:** `airline_contact_center_ai`  
**Target schema:** `db_airlines`  
**Status:** Review draft only. This document and SQL are not evidence that the migration has been run.

## Why the scope expands beyond the original migration note

The existing `docs/pre_migration_design_reconciliation_v1.md` assigns Migration 002 to source lineage and historical interval facts. The product requirement now explicitly includes many companies and users in one application. The first migration contains no tenant registry and no tenant keys on operational tables. To avoid creating a historical-data model that is tenant-aware while bookings/queues/interactions remain globally scoped, this draft adds a minimal tenant foundation and tenant-scopes the existing company-owned operational tables at the same time.

This change should be recorded as a deliberate architecture decision and reconciled back into `docs/pre_migration_design_reconciliation_v1.md` and `docs/database_schema.md` before production use.

## What the draft does

1. Creates `tenants` and adds one explicitly named development tenant: `demo_airline`.
2. Adds `tenant_id` to `services`, `queues`, `bookings`, `contact_interactions`, and `sla_rules`; existing rows are assigned to that development tenant during migration.
3. Replaces global uniqueness where company-specific duplicates should be allowed (service code, queue code, booking reference, conversation/queue-leg reference) with tenant-scoped uniqueness.
4. Replaces key foreign keys with composite tenant-scoped foreign keys so a contact interaction or SLA rule cannot reference another tenant's queue/booking through those relationships.
5. Creates `source_systems` and `ingestion_batches` with tenant/source lineage, status, row counts, optional content SHA-256, and validation summaries.
6. Creates `historical_interval_metrics` at source-row/interval grain. Numerators and denominators are stored separately. Source-reported averages/percentages are retained under `source_reported_*` names for reconciliation and must not silently replace canonical KPI calculations.
7. Keeps `markets`, `languages`, and `channels` as platform-wide catalog dimensions in v1. If a company has a different definition of market, it needs explicit approved mapping to the platform catalog; this migration does not store company-specific market vocabularies.

## Important assumptions and limits

- The previous read-only checks showed `markets=3`, `languages=4`, `channels=5`, and zero rows in `services`, `queues`, `bookings`, `contact_interactions`, and `sla_rules`. Run preflight again immediately before execution; do not rely only on the earlier output.
- `DATABASE() = NULL` only means no default schema was selected in that SQL session. The script explicitly selects `db_airlines`; preflight must still confirm that the schema exists.
- The current configuration uses `db_airlines`; this is the canonical spelling. `lower_case_table_names=1` means schema/table name lookups are case-insensitive in this MySQL configuration, but keep lowercase names for portability.
- The migration seeds a development tenant, not a real customer. Any previously existing rows in tenant-owned tables are backfilled into that development tenant. If that assignment is not correct, stop and amend the plan first.
- Tenant IDs do not implement authentication or authorization by themselves. Future repository queries and writes must use the authenticated tenant context, and a later access-control migration must define users, memberships, roles, and permissions.
- Do not place API keys, passwords, or tokens in source-system rows or JSON summaries.
- Import deduplication at this stage detects identical file checksums for a given tenant/source and duplicate row numbers within a batch. Cross-file overlapping intervals still require validation logic in the ingestion layer.
- MySQL DDL implicitly commits. This migration is intentionally not idempotent; do not rerun it after partial execution without inspecting `information_schema` and repairing deliberately.

## Preflight requirements

Run `database/checks/002_preflight.sql` and verify:

- `VERSION()`, `@@version_comment`, `@@lower_case_table_names`, and schema existence are as expected.
- The eight Migration 001 base tables exist.
- `tenants`, `source_systems`, `ingestion_batches`, and `historical_interval_metrics` do not already exist.
- Current row counts are reviewed. If any tenant-owned business table is non-empty, confirm the ownership of each row before applying this draft.
- A restorable database backup exists.
- The full migration is read, and a local test database or restorable copy is used for first execution when available.

## Execution procedure (manual only)

1. Save/commit this migration draft and its checks to Git.
2. Back up `db_airlines` and verify the backup can be restored.
3. Run preflight again immediately before applying the migration.
4. Execute `database/migrations/002_tenant_source_lineage_historical_metrics.sql` once using a developer/DBA account.
5. If any statement fails, stop. Do not rerun the entire file. Inspect present tables, columns, indexes, and foreign keys in `information_schema` and reconcile the partial DDL.
6. On success, run `database/checks/002_postflight.sql` and compare the output to the expected state.
7. Run application tests and update all data-access methods to require an authorized tenant context before allowing tenant-owned data access.

## Not included

- User login, tenant memberships, roles, or per-feature permissions.
- Persisted semantic field mappings and mapping approval history.
- Loading real historical data or generating synthetic interval data.
- Forecast, Erlang C, WFM, schedule, adherence, RTM, simulation, or LLM provider tables.
- Production authentication, authorization, row-level security policy, or audit integration.

These should be designed and tested in later stages. Do not represent Migration 002 as a complete multi-tenant security solution.
