-- AeroInsight WFM Foundation - Reference Data Seed
-- Target database: db_airlines
-- Purpose: create baseline demo services and voice/WhatsApp queues for demo_airline.
-- Safe behavior: INSERT-only, idempotent, no UPDATE/DELETE, no employee or schedule records.
-- All timestamps are stored in UTC.

USE `db_airlines`;
SET SESSION time_zone = '+00:00';

START TRANSACTION;

-- 1) Seed the agreed demo airline services only when they do not already exist.
INSERT INTO `services`
    (`service_code`, `tenant_id`, `display_name`, `is_active`, `created_at_utc`, `updated_at_utc`)
SELECT
    seed.`service_code`, t.`tenant_id`, seed.`display_name`, 1, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
FROM `tenants` t
CROSS JOIN (
    SELECT 'booking' AS `service_code`, 'Booking' AS `display_name`
    UNION ALL SELECT 'change_booking', 'Change Booking'
    UNION ALL SELECT 'loyalty', 'Loyalty'
) AS seed
WHERE t.`tenant_code` = 'demo_airline'
  AND NOT EXISTS (
      SELECT 1
      FROM `services` s
      WHERE s.`tenant_id` = t.`tenant_id`
        AND s.`service_code` = seed.`service_code`
  );

-- 2) Seed one Voice and one WhatsApp queue per service.
-- Queue language is intentionally not encoded here; it is governed through workforce skills
-- and queue_skill_requirements in the next WFM step. WhatsApp proficiency will be English-only.
INSERT INTO `queues`
    (`tenant_id`, `queue_code`, `queue_name`, `service_code`, `channel_code`, `is_active`, `created_at_utc`, `updated_at_utc`)
SELECT
    t.`tenant_id`, seed.`queue_code`, seed.`queue_name`, seed.`service_code`, c.`channel_code`, 1,
    UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
FROM `tenants` t
CROSS JOIN (
    SELECT 'booking' AS `service_code`, 'booking_voice' AS `queue_code`, 'Booking - Voice' AS `queue_name`, 'voice' AS `channel_code`
    UNION ALL SELECT 'booking', 'booking_whatsapp', 'Booking - WhatsApp', 'whatsapp'
    UNION ALL SELECT 'change_booking', 'change_booking_voice', 'Change Booking - Voice', 'voice'
    UNION ALL SELECT 'change_booking', 'change_booking_whatsapp', 'Change Booking - WhatsApp', 'whatsapp'
    UNION ALL SELECT 'loyalty', 'loyalty_voice', 'Loyalty - Voice', 'voice'
    UNION ALL SELECT 'loyalty', 'loyalty_whatsapp', 'Loyalty - WhatsApp', 'whatsapp'
) AS seed
INNER JOIN `services` s
    ON s.`tenant_id` = t.`tenant_id`
   AND s.`service_code` = seed.`service_code`
INNER JOIN `channels` c
    ON c.`channel_code` = seed.`channel_code`
WHERE t.`tenant_code` = 'demo_airline'
  AND NOT EXISTS (
      SELECT 1
      FROM `queues` q
      WHERE q.`tenant_id` = t.`tenant_id`
        AND q.`queue_code` = seed.`queue_code`
  );

COMMIT;

-- 3) Post-insert summary. Expected: 3 services and 6 queues for demo_airline.
SELECT
    t.`tenant_code`,
    (SELECT COUNT(*) FROM `services` s WHERE s.`tenant_id` = t.`tenant_id` AND s.`service_code` IN ('booking','change_booking','loyalty')) AS `seeded_services`,
    (SELECT COUNT(*) FROM `queues` q WHERE q.`tenant_id` = t.`tenant_id` AND q.`queue_code` IN (
        'booking_voice','booking_whatsapp',
        'change_booking_voice','change_booking_whatsapp',
        'loyalty_voice','loyalty_whatsapp'
    )) AS `seeded_queues`
FROM `tenants` t
WHERE t.`tenant_code` = 'demo_airline';

SELECT
    q.`queue_code`, q.`queue_name`, q.`service_code`, q.`channel_code`, q.`is_active`
FROM `queues` q
INNER JOIN `tenants` t ON t.`tenant_id` = q.`tenant_id`
WHERE t.`tenant_code` = 'demo_airline'
  AND q.`queue_code` IN (
      'booking_voice','booking_whatsapp',
      'change_booking_voice','change_booking_whatsapp',
      'loyalty_voice','loyalty_whatsapp'
  )
ORDER BY q.`service_code`, q.`channel_code`;
