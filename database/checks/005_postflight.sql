-- AeroInsight WFM Foundation / Migration 005 Postflight
-- READ ONLY. Target: db_airlines.

USE `db_airlines`;
SET SESSION time_zone = '+00:00';

SELECT DATABASE() AS current_schema;

SELECT expected.table_name,
       CASE WHEN t.TABLE_NAME IS NULL THEN 'MISSING' ELSE 'CREATED' END AS status
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

SELECT
    (SELECT COUNT(*) FROM employees) AS employee_count,
    (SELECT COUNT(*) FROM workforce_skills) AS skill_count,
    (SELECT COUNT(*) FROM employee_skills) AS employee_skill_count,
    (SELECT COUNT(*) FROM workforce_shifts) AS shift_count,
    (SELECT COUNT(*) FROM workforce_shift_activities) AS activity_count,
    (SELECT COUNT(*) FROM queue_skill_requirements) AS queue_skill_requirement_count,
    (SELECT COUNT(*) FROM workforce_agent_state_events) AS state_event_count;

SELECT skill_category, COUNT(*) AS skill_count
FROM workforce_skills
WHERE tenant_id = (SELECT tenant_id FROM tenants WHERE tenant_code = 'demo_airline' LIMIT 1)
GROUP BY skill_category
ORDER BY skill_category;

SELECT
    TABLE_NAME,
    CONSTRAINT_NAME,
    REFERENCED_TABLE_NAME
FROM information_schema.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
      'employees', 'workforce_skills', 'employee_skills',
      'workforce_shifts', 'workforce_shift_activities',
      'queue_skill_requirements', 'workforce_agent_state_events'
  )
ORDER BY TABLE_NAME, CONSTRAINT_NAME;
