-- AeroInsight WFM Foundation / Migration 005 Preflight
-- READ ONLY. Target: db_airlines. Run before Migration 005.

USE `db_airlines`;
SET SESSION time_zone = '+00:00';

-- 1. Confirm the selected schema.
SELECT DATABASE() AS current_schema;

-- 2. Required parent tables must exist.
SELECT required.table_name,
       CASE WHEN t.TABLE_NAME IS NULL THEN 'MISSING' ELSE 'OK' END AS status
FROM (
    SELECT 'tenants' AS table_name
    UNION ALL SELECT 'languages'
    UNION ALL SELECT 'channels'
    UNION ALL SELECT 'services'
    UNION ALL SELECT 'queues'
    UNION ALL SELECT 'tenant_memberships'
    UNION ALL SELECT 'audit_events'
) AS required
LEFT JOIN information_schema.TABLES AS t
  ON t.TABLE_SCHEMA = DATABASE()
 AND t.TABLE_NAME = required.table_name
ORDER BY required.table_name;

-- 3. Migration 005 target tables must not already exist.
SELECT expected.table_name,
       CASE WHEN t.TABLE_NAME IS NULL THEN 'NOT_CREATED_YET' ELSE 'ALREADY_EXISTS' END AS status
FROM (
    SELECT 'employees' AS table_name
    UNION ALL SELECT 'workforce_skills'
    UNION ALL SELECT 'employee_skills'
    UNION ALL SELECT 'workforce_shifts'
    UNION ALL SELECT 'workforce_shift_activities'
    UNION ALL SELECT 'queue_skill_requirements'
    UNION ALL SELECT 'workforce_agent_state_events'
) AS expected
LEFT JOIN information_schema.TABLES AS t
  ON t.TABLE_SCHEMA = DATABASE()
 AND t.TABLE_NAME = expected.table_name
ORDER BY expected.table_name;

-- 4. WFM permissions from Migration 003 must exist.
SELECT permission_code
FROM permissions
WHERE permission_code IN ('wfm.view', 'wfm.manage')
ORDER BY permission_code;

-- 5. Confirm tenant records and current reference-data readiness.
SELECT tenant_id, tenant_code, display_name, tenant_status
FROM tenants
ORDER BY tenant_id;

SELECT
    (SELECT COUNT(*) FROM services) AS services_count,
    (SELECT COUNT(*) FROM queues) AS queues_count,
    (SELECT COUNT(*) FROM languages) AS languages_count,
    (SELECT COUNT(*) FROM channels) AS channels_count;
