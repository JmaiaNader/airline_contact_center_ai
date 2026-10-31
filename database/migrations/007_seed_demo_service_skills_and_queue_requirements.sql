-- AeroInsight WFM Step 3: Service Skills + Queue Skill Requirements
-- Target: existing db_airlines / tenant demo_airline
-- Additive, DML-only, idempotent. No employees or schedules are fabricated.
-- Timestamps are stored in UTC.
--
-- Skill model:
--   Every queue requires its service skill AND channel skill.
--   Voice queues accept Arabic OR English (language options are alternatives).
--   WhatsApp queues accept English only.
--   Minimum proficiency level 3 = Proficient.
--
-- IMPORTANT ENGINE CONTRACT:
--   The current queue_skill_requirements schema has no explicit any-of group column.
--   The WFM skill matcher MUST interpret multiple active required skills in the
--   'language' category as an ANY-OF set for a queue, while service and channel
--   requirements are ALL-OF. Do not implement a naive AND across every row.

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

-- Resolve the existing demo tenant. If it is absent, INSERTs below add no rows.
SET @aero_tenant_id := (
    SELECT `tenant_id`
    FROM `tenants`
    WHERE `tenant_code` = 'demo_airline'
    LIMIT 1
);

SELECT
    DATABASE() AS target_schema,
    @aero_tenant_id AS demo_airline_tenant_id,
    CASE WHEN @aero_tenant_id IS NULL THEN 'STOP: demo_airline tenant not found'
         ELSE 'OK: tenant resolved' END AS precondition_status;

START TRANSACTION;

-- 1. Create the three tenant-scoped service skills, if absent.
INSERT INTO `workforce_skills`
    (`tenant_id`, `skill_code`, `skill_name`, `skill_category`, `service_code`, `is_active`)
SELECT
    s.`tenant_id`,
    CONCAT('service_', s.`service_code`),
    CONCAT('Service: ', s.`display_name`),
    'service',
    s.`service_code`,
    1
FROM `services` s
WHERE s.`tenant_id` = @aero_tenant_id
  AND s.`is_active` = 1
  AND s.`service_code` IN ('booking', 'change_booking', 'loyalty')
  AND NOT EXISTS (
      SELECT 1
      FROM `workforce_skills` ws
      WHERE ws.`tenant_id` = s.`tenant_id`
        AND ws.`skill_code` = CONCAT('service_', s.`service_code`)
  );

-- 2. Every queue requires its matching service skill (ALL-OF condition).
INSERT INTO `queue_skill_requirements`
    (`tenant_id`, `queue_id`, `skill_id`, `minimum_proficiency_level`,
     `requirement_type`, `priority_weight`, `is_active`)
SELECT
    q.`tenant_id`, q.`queue_id`, ws.`skill_id`, 3,
    'required', 1.000, 1
FROM `queues` q
INNER JOIN `workforce_skills` ws
    ON ws.`tenant_id` = q.`tenant_id`
   AND ws.`skill_code` = CONCAT('service_', q.`service_code`)
   AND ws.`skill_category` = 'service'
   AND ws.`is_active` = 1
WHERE q.`tenant_id` = @aero_tenant_id
  AND q.`is_active` = 1
  AND q.`queue_code` IN (
      'booking_voice', 'booking_whatsapp',
      'change_booking_voice', 'change_booking_whatsapp',
      'loyalty_voice', 'loyalty_whatsapp'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM `queue_skill_requirements` req
      WHERE req.`tenant_id` = q.`tenant_id`
        AND req.`queue_id` = q.`queue_id`
        AND req.`skill_id` = ws.`skill_id`
  );

-- 3. Every queue requires its matching channel skill (ALL-OF condition).
INSERT INTO `queue_skill_requirements`
    (`tenant_id`, `queue_id`, `skill_id`, `minimum_proficiency_level`,
     `requirement_type`, `priority_weight`, `is_active`)
SELECT
    q.`tenant_id`, q.`queue_id`, ws.`skill_id`, 3,
    'required', 1.000, 1
FROM `queues` q
INNER JOIN `workforce_skills` ws
    ON ws.`tenant_id` = q.`tenant_id`
   AND ws.`skill_code` = CONCAT('channel_', q.`channel_code`)
   AND ws.`skill_category` = 'channel'
   AND ws.`is_active` = 1
WHERE q.`tenant_id` = @aero_tenant_id
  AND q.`is_active` = 1
  AND q.`queue_code` IN (
      'booking_voice', 'booking_whatsapp',
      'change_booking_voice', 'change_booking_whatsapp',
      'loyalty_voice', 'loyalty_whatsapp'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM `queue_skill_requirements` req
      WHERE req.`tenant_id` = q.`tenant_id`
        AND req.`queue_id` = q.`queue_id`
        AND req.`skill_id` = ws.`skill_id`
  );

-- 4. Language requirements:
--    Voice: Arabic OR English (two alternatives in the same skill category).
--    WhatsApp: English only.
INSERT INTO `queue_skill_requirements`
    (`tenant_id`, `queue_id`, `skill_id`, `minimum_proficiency_level`,
     `requirement_type`, `priority_weight`, `is_active`)
SELECT
    q.`tenant_id`, q.`queue_id`, ws.`skill_id`, 3,
    'required', 1.000, 1
FROM `queues` q
INNER JOIN `workforce_skills` ws
    ON ws.`tenant_id` = q.`tenant_id`
   AND ws.`skill_category` = 'language'
   AND ws.`is_active` = 1
   AND (
        (q.`channel_code` = 'voice' AND ws.`language_code` IN ('ar', 'en'))
        OR
        (q.`channel_code` = 'whatsapp' AND ws.`language_code` = 'en')
   )
WHERE q.`tenant_id` = @aero_tenant_id
  AND q.`is_active` = 1
  AND q.`queue_code` IN (
      'booking_voice', 'booking_whatsapp',
      'change_booking_voice', 'change_booking_whatsapp',
      'loyalty_voice', 'loyalty_whatsapp'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM `queue_skill_requirements` req
      WHERE req.`tenant_id` = q.`tenant_id`
        AND req.`queue_id` = q.`queue_id`
        AND req.`skill_id` = ws.`skill_id`
  );

COMMIT;

-- 5. Summary: expected for demo_airline = 3 service skills and 21 queue requirements.
SELECT
    t.`tenant_code`,
    (SELECT COUNT(*)
     FROM `workforce_skills` ws
     WHERE ws.`tenant_id` = t.`tenant_id`
       AND ws.`skill_category` = 'service'
       AND ws.`skill_code` IN ('service_booking', 'service_change_booking', 'service_loyalty')
       AND ws.`is_active` = 1) AS `service_skills`,
    (SELECT COUNT(*)
     FROM `queue_skill_requirements` req
     INNER JOIN `queues` q
        ON q.`tenant_id` = req.`tenant_id`
       AND q.`queue_id` = req.`queue_id`
     WHERE req.`tenant_id` = t.`tenant_id`
       AND q.`queue_code` IN (
          'booking_voice', 'booking_whatsapp',
          'change_booking_voice', 'change_booking_whatsapp',
          'loyalty_voice', 'loyalty_whatsapp'
       )
       AND req.`is_active` = 1) AS `active_queue_skill_requirements`
FROM `tenants` t
WHERE t.`tenant_id` = @aero_tenant_id;

-- 6. Per-queue review: service, channel and language requirements.
SELECT
    q.`queue_code`,
    q.`queue_name`,
    q.`channel_code`,
    COUNT(*) AS `active_requirement_rows`,
    GROUP_CONCAT(
        CONCAT(ws.`skill_category`, ':', ws.`skill_code`,
               ' (min proficiency ', req.`minimum_proficiency_level`, ')')
        ORDER BY ws.`skill_category`, ws.`skill_code`
        SEPARATOR ' | '
    ) AS `required_skills`
FROM `queues` q
INNER JOIN `queue_skill_requirements` req
    ON req.`tenant_id` = q.`tenant_id`
   AND req.`queue_id` = q.`queue_id`
   AND req.`is_active` = 1
INNER JOIN `workforce_skills` ws
    ON ws.`tenant_id` = req.`tenant_id`
   AND ws.`skill_id` = req.`skill_id`
WHERE q.`tenant_id` = @aero_tenant_id
  AND q.`queue_code` IN (
      'booking_voice', 'booking_whatsapp',
      'change_booking_voice', 'change_booking_whatsapp',
      'loyalty_voice', 'loyalty_whatsapp'
  )
GROUP BY q.`queue_id`, q.`queue_code`, q.`queue_name`, q.`channel_code`
ORDER BY q.`queue_code`;
