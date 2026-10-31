-- Read-only postflight for Migration 006.
USE `db_airlines`;
SET SESSION time_zone = '+00:00';

SELECT
    COLUMN_NAME,
    COLUMN_TYPE,
    IS_NULLABLE,
    COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME = 'queue_skill_requirements'
  AND COLUMN_NAME IN ('requirement_group_code', 'requirement_match_mode')
ORDER BY ORDINAL_POSITION;

SELECT
    q.`queue_code`,
    req.`requirement_group_code`,
    req.`requirement_match_mode`,
    COUNT(*) AS `requirement_count`,
    GROUP_CONCAT(skill.`skill_code` ORDER BY skill.`skill_code` SEPARATOR ', ') AS `skills`
FROM `queue_skill_requirements` req
JOIN `queues` q
  ON q.`tenant_id` = req.`tenant_id`
 AND q.`queue_id` = req.`queue_id`
JOIN `workforce_skills` skill
  ON skill.`tenant_id` = req.`tenant_id`
 AND skill.`skill_id` = req.`skill_id`
JOIN `tenants` t
  ON t.`tenant_id` = req.`tenant_id`
WHERE t.`tenant_code` = 'demo_airline'
  AND req.`is_active` = 1
GROUP BY q.`queue_code`, req.`requirement_group_code`, req.`requirement_match_mode`
ORDER BY q.`queue_code`, req.`requirement_group_code`;

SELECT
    SUM(skill.`skill_category` = 'language' AND req.`requirement_match_mode` = 'any_of') AS language_any_of_rows,
    SUM(skill.`skill_category` IN ('service', 'channel') AND req.`requirement_match_mode` = 'all_of') AS service_channel_all_of_rows,
    SUM(req.`requirement_match_mode` NOT IN ('all_of', 'any_of')) AS invalid_mode_rows
FROM `queue_skill_requirements` req
JOIN `workforce_skills` skill
  ON skill.`tenant_id` = req.`tenant_id`
 AND skill.`skill_id` = req.`skill_id`
JOIN `tenants` t
  ON t.`tenant_id` = req.`tenant_id`
WHERE t.`tenant_code` = 'demo_airline'
  AND req.`is_active` = 1;
