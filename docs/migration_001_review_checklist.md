# Migration 001 Review Checklist

**Status:** SQL prepared for review. It has **not** been run against `db_Airlines`.

## Files in this pack

- `database/migrations/001_create_core_schema.sql` — creates the eight core tables only.
- `database/seeds/001_core_reference_data.sql` — idempotent initial market/language/channel reference data.
- `tests/test_migration_001_sql.py` — static checks for migration shape and safeguards.
- `tests/test_core_reference_seed_sql.py` — static checks for seed scope and expected codes.

## What Migration 001 creates

1. `markets`
2. `languages`
3. `channels`
4. `services`
5. `queues`
6. `bookings`
7. `contact_interactions`
8. `sla_rules`

No WFM, forecasting, adherence, policy, or RTM action tables are created in this migration.

## Seed data scope

The seed file inserts QATAR, USA, UAE; en, ar, fr, und; and voice, webchat, whatsapp, email, social_media. It intentionally does not invent services, queue names, or SLA targets. `USA.reporting_timezone` is `NULL` because one country-wide timezone has not been agreed. The synchronous flags for channels are provisional defaults and must be reviewed against the real operating model.

## Before applying SQL in MySQL Workbench

1. Confirm this is the intended development database, not production or another project.
2. Connect using a migration/DBA account authorized to create tables. Do not grant DDL privileges to the Streamlit runtime account.
3. Run this separately and inspect the output:

   ```sql
   SELECT DATABASE() AS selected_database;

   SELECT COUNT(*) AS existing_base_tables
   FROM information_schema.tables
   WHERE table_schema = DATABASE()
     AND table_type = 'BASE TABLE';
   ```

4. Continue only if the selected database is the intended `db_Airlines` schema (Windows MySQL may report a lower-case spelling) and the empty database has zero base tables. If the table count is not zero, stop and reconcile the existing objects first.
5. Review the entire migration before execution. It uses MySQL 8.0.16+ enforced `CHECK` constraints and `USE db_Airlines`.
6. Execute `001_create_core_schema.sql`. MySQL DDL implicitly commits; if a statement fails, stop and inspect `information_schema.tables` and foreign-key metadata. Do not blindly rerun the file after partial creation.
7. Verify the eight tables exist before proceeding.
8. Execute `001_core_reference_data.sql` separately, then verify the market, language, and channel rows.
9. Record the migration version and execution date in your project notes. No automatic migration runner is enabled yet.

## Verification queries after migration and seed

```sql
SELECT DATABASE() AS selected_database;

SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_type = 'BASE TABLE'
ORDER BY table_name;

SELECT market_code, market_name, country_code, reporting_timezone
FROM markets
ORDER BY market_code;

SELECT language_code, display_name FROM languages ORDER BY language_code;
SELECT channel_code, display_name, is_synchronous FROM channels ORDER BY channel_code;

SELECT COUNT(*) AS services_count FROM services;
SELECT COUNT(*) AS queues_count FROM queues;
SELECT COUNT(*) AS sla_rules_count FROM sla_rules;
```

The last three counts should be zero after the seed because production service codes, queue mappings, and SLA thresholds have not been approved and must not be fabricated.

## Known limitations / follow-up decisions

- Overlapping effective periods for `sla_rules` cannot be rejected by a simple unique key alone. Add a tested application validation before enabling SLA lookup/reporting.
- Runtime DB connections must set the MySQL session timezone to UTC (`SET time_zone = '+00:00'`) to align timestamp defaults and the UTC storage contract; verify this in the connection factory before production use.
- Market codes are initial internal operational-market codes, not sales/POS codes.
- Before useful KPI calculation, agree valid services/queues, SLA target and response thresholds, short-abandon treatment, and the metric eligibility rules by channel.
- The current tests inspect SQL text only. They do not prove that MySQL accepted the DDL or that a live connection works. A disposable MySQL integration test remains required before applying this migration to any non-disposable database.
