-- READ-ONLY preflight for Migration 002. Run before the migration.
-- This does not change data or create objects.

SELECT
    VERSION() AS server_version,
    @@version_comment AS server_product,
    @@lower_case_table_names AS lower_case_table_names,
    DATABASE() AS currently_selected_schema;

SELECT SCHEMA_NAME
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME = 'db_airlines';

SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;

-- These tables should not exist before first execution of this draft.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN (
      'tenants', 'source_systems', 'ingestion_batches', 'historical_interval_metrics'
  )
ORDER BY TABLE_NAME;

-- Expected core-table row counts, rechecked immediately before migrating.
SELECT 'services' AS table_name, COUNT(*) AS row_count FROM db_airlines.services
UNION ALL SELECT 'queues', COUNT(*) FROM db_airlines.queues
UNION ALL SELECT 'bookings', COUNT(*) FROM db_airlines.bookings
UNION ALL SELECT 'contact_interactions', COUNT(*) FROM db_airlines.contact_interactions
UNION ALL SELECT 'sla_rules', COUNT(*) FROM db_airlines.sla_rules
UNION ALL SELECT 'markets', COUNT(*) FROM db_airlines.markets
UNION ALL SELECT 'languages', COUNT(*) FROM db_airlines.languages
UNION ALL SELECT 'channels', COUNT(*) FROM db_airlines.channels;

-- Stop unless:
-- 1) db_airlines exists and is the intended development database.
-- 2) the 8 Migration 001 tables are present.
-- 3) tenants/source_systems/ingestion_batches/historical_interval_metrics are absent.
-- 4) if any of services/queues/bookings/contact_interactions/sla_rules is non-empty,
--    explicitly confirm which tenant each row belongs to before using this migration.
-- 5) a restorable backup exists and docs/migration_002_review.md has been read.
