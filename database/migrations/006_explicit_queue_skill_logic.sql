-- AeroInsight Migration 006: Explicit AND/OR logic for queue skill requirements.
-- Target: existing db_airlines. Additive schema change; no employee records created.
-- Reason: language rows for Voice represent Arabic OR English, not Arabic AND English.
-- Run once after successful 006_preflight.sql. MySQL DDL auto-commits.

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

SELECT DATABASE() AS migration_006_target_schema;

ALTER TABLE `queue_skill_requirements`
    ADD COLUMN `requirement_group_code` VARCHAR(32)
        CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'default'
        AFTER `requirement_type`,
    ADD COLUMN `requirement_match_mode` VARCHAR(16)
        CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'all_of'
        AFTER `requirement_group_code`,
    ADD CONSTRAINT `chk006_queue_skill_match_mode`
        CHECK (`requirement_match_mode` IN ('all_of', 'any_of')),
    ADD CONSTRAINT `chk006_queue_skill_group_code`
        CHECK (CHAR_LENGTH(`requirement_group_code`) > 0),
    ADD KEY `ix006_queue_skill_group`
        (`tenant_id`, `queue_id`, `requirement_group_code`, `is_active`);

-- Backfill explicit grouping from the existing tenant-scoped skill catalog.
-- Service and channel groups are ALL-OF. All language alternatives for a queue
-- belong to one ANY-OF group (e.g. Arabic OR English for Voice).
UPDATE `queue_skill_requirements` AS req
JOIN `workforce_skills` AS skill
  ON skill.`tenant_id` = req.`tenant_id`
 AND skill.`skill_id` = req.`skill_id`
SET
    req.`requirement_group_code` = CASE skill.`skill_category`
        WHEN 'language' THEN 'language'
        WHEN 'service' THEN 'service'
        WHEN 'channel' THEN 'channel'
        ELSE 'other'
    END,
    req.`requirement_match_mode` = CASE
        WHEN skill.`skill_category` = 'language' THEN 'any_of'
        ELSE 'all_of'
    END;

-- Post-migration summary: the three Voice queues should have an ANY-OF language group.
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
