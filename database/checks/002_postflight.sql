-- READ-ONLY postflight checks for Migration 002. Run after successful execution.
USE `db_airlines`;

SELECT DATABASE() AS selected_schema;

SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN (
      'tenants', 'source_systems', 'ingestion_batches', 'historical_interval_metrics',
      'markets', 'languages', 'channels', 'services', 'queues', 'bookings',
      'contact_interactions', 'sla_rules'
  )
ORDER BY TABLE_NAME;

SELECT tenant_id, tenant_code, display_name, tenant_status
FROM db_airlines.tenants
ORDER BY tenant_id;

SELECT 'services' AS table_name, COUNT(*) AS row_count,
       COUNT(DISTINCT tenant_id) AS tenant_count FROM db_airlines.services
UNION ALL SELECT 'queues', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.queues
UNION ALL SELECT 'bookings', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.bookings
UNION ALL SELECT 'contact_interactions', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.contact_interactions
UNION ALL SELECT 'sla_rules', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.sla_rules
UNION ALL SELECT 'source_systems', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.source_systems
UNION ALL SELECT 'ingestion_batches', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.ingestion_batches
UNION ALL SELECT 'historical_interval_metrics', COUNT(*), COUNT(DISTINCT tenant_id) FROM db_airlines.historical_interval_metrics;

-- Confirm tenant_id exists on every tenant-owned core table.
SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'db_airlines'
  AND COLUMN_NAME = 'tenant_id'
ORDER BY TABLE_NAME;

-- Check foreign keys to confirm tenant-scoped relationships exist.
SELECT TABLE_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = 'db_airlines'
  AND REFERENCED_TABLE_NAME IS NOT NULL
  AND (TABLE_NAME IN ('services','queues','bookings','contact_interactions','sla_rules',
                      'source_systems','ingestion_batches','historical_interval_metrics'))
ORDER BY TABLE_NAME, CONSTRAINT_NAME;
