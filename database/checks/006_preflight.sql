-- Read-only preflight for Migration 006.
USE `db_airlines`;
SET SESSION time_zone = '+00:00';

SELECT DATABASE() AS target_schema;

SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME = 'queue_skill_requirements';

SELECT COLUMN_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME = 'queue_skill_requirements'
  AND COLUMN_NAME IN ('requirement_group_code', 'requirement_match_mode');

SELECT
    t.tenant_code,
    COUNT(*) AS active_requirement_rows,
    COUNT(DISTINCT q.queue_id) AS queues_with_requirements
FROM queue_skill_requirements req
JOIN queues q
  ON q.tenant_id = req.tenant_id
 AND q.queue_id = req.queue_id
JOIN tenants t
  ON t.tenant_id = req.tenant_id
WHERE t.tenant_code = 'demo_airline'
  AND req.is_active = 1
GROUP BY t.tenant_code;
