-- AeroInsight / airline_contact_center_ai
-- Migration 005: Workforce Management foundation
-- TARGET: db_airlines
-- Additive only. Creates seven WFM tables; does not alter existing tables.
-- No employee/person records are fabricated. Only tenant-scoped skill catalog
-- entries are seeded from existing language and channel reference catalogs.
-- All persisted timestamps are UTC. Local schedule timezone is retained per shift.
-- MySQL DDL implicitly commits. Run once after successful 005_preflight.sql.

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

SELECT DATABASE() AS migration_005_target_schema;

-- 1. Employee master. Keep personal data minimal; OIDC user identity is separate.
CREATE TABLE `employees` (
    `employee_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `employee_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `display_name` VARCHAR(128) NOT NULL,
    `employment_type` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'permanent',
    `employee_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    `primary_language_code` VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `work_timezone` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'UTC',
    `hire_date` DATE NULL,
    `end_date` DATE NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`employee_id`),
    UNIQUE KEY `uq005_employees_tenant_code` (`tenant_id`, `employee_code`),
    UNIQUE KEY `uq005_employees_tenant_employee` (`tenant_id`, `employee_id`),
    KEY `ix005_employees_tenant_status` (`tenant_id`, `employee_status`),
    KEY `ix005_employees_tenant_type` (`tenant_id`, `employment_type`),
    CONSTRAINT `fk005_employees_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_employees_primary_language`
        FOREIGN KEY (`primary_language_code`) REFERENCES `languages` (`language_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_employees_type`
        CHECK (`employment_type` IN ('permanent', 'part_time', 'contractor', 'trainee')),
    CONSTRAINT `chk005_employees_status`
        CHECK (`employee_status` IN ('active', 'inactive', 'on_leave', 'terminated')),
    CONSTRAINT `chk005_employees_dates`
        CHECK (`end_date` IS NULL OR `hire_date` IS NULL OR `end_date` >= `hire_date`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Tenant-scoped skill catalog. A skill may represent a language, service,
-- channel, or an explicitly named other capability.
CREATE TABLE `workforce_skills` (
    `skill_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `skill_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `skill_name` VARCHAR(100) NOT NULL,
    `skill_category` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `language_code` VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `service_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `channel_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`skill_id`),
    UNIQUE KEY `uq005_skills_tenant_code` (`tenant_id`, `skill_code`),
    UNIQUE KEY `uq005_skills_tenant_skill` (`tenant_id`, `skill_id`),
    KEY `ix005_skills_tenant_category` (`tenant_id`, `skill_category`, `is_active`),
    CONSTRAINT `fk005_skills_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_skills_language`
        FOREIGN KEY (`language_code`) REFERENCES `languages` (`language_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_skills_channel`
        FOREIGN KEY (`channel_code`) REFERENCES `channels` (`channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_skills_service`
        FOREIGN KEY (`tenant_id`, `service_code`) REFERENCES `services` (`tenant_id`, `service_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_skills_category`
        CHECK (`skill_category` IN ('language', 'service', 'channel', 'other')),
    CONSTRAINT `chk005_skills_category_reference`
        CHECK (
            (`skill_category` = 'language' AND `language_code` IS NOT NULL AND `service_code` IS NULL AND `channel_code` IS NULL)
            OR (`skill_category` = 'service' AND `service_code` IS NOT NULL AND `language_code` IS NULL AND `channel_code` IS NULL)
            OR (`skill_category` = 'channel' AND `channel_code` IS NOT NULL AND `language_code` IS NULL AND `service_code` IS NULL)
            OR (`skill_category` = 'other' AND `language_code` IS NULL AND `service_code` IS NULL AND `channel_code` IS NULL)
        ),
    CONSTRAINT `chk005_skills_active` CHECK (`is_active` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Employee-to-skill proficiency. Level 1-5 is explicit and tenant-scoped.
CREATE TABLE `employee_skills` (
    `employee_skill_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `employee_id` BIGINT UNSIGNED NOT NULL,
    `skill_id` BIGINT UNSIGNED NOT NULL,
    `proficiency_level` TINYINT UNSIGNED NOT NULL,
    `is_verified` TINYINT(1) NOT NULL DEFAULT 0,
    `skill_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    `assessed_at_utc` DATETIME(6) NULL,
    `valid_until_utc` DATETIME(6) NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`employee_skill_id`),
    UNIQUE KEY `uq005_employee_skill` (`tenant_id`, `employee_id`, `skill_id`),
    UNIQUE KEY `uq005_employee_skill_tenant_id` (`tenant_id`, `employee_skill_id`),
    KEY `ix005_employee_skills_lookup` (`tenant_id`, `skill_id`, `skill_status`, `proficiency_level`),
    CONSTRAINT `fk005_employee_skills_employee`
        FOREIGN KEY (`tenant_id`, `employee_id`) REFERENCES `employees` (`tenant_id`, `employee_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_employee_skills_skill`
        FOREIGN KEY (`tenant_id`, `skill_id`) REFERENCES `workforce_skills` (`tenant_id`, `skill_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_employee_skill_level` CHECK (`proficiency_level` BETWEEN 1 AND 5),
    CONSTRAINT `chk005_employee_skill_verified` CHECK (`is_verified` IN (0, 1)),
    CONSTRAINT `chk005_employee_skill_status` CHECK (`skill_status` IN ('active', 'expired', 'revoked')),
    CONSTRAINT `chk005_employee_skill_validity`
        CHECK (`valid_until_utc` IS NULL OR `assessed_at_utc` IS NULL OR `valid_until_utc` >= `assessed_at_utc`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Planned/published shifts. Store UTC instants and retain the IANA timezone
-- used when the local schedule was created (for DST-safe display/reconstruction).
CREATE TABLE `workforce_shifts` (
    `shift_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `employee_id` BIGINT UNSIGNED NOT NULL,
    `shift_start_utc` DATETIME(6) NOT NULL,
    `shift_end_utc` DATETIME(6) NOT NULL,
    `shift_timezone` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `shift_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'draft',
    `shift_label` VARCHAR(100) NULL,
    `created_by_membership_id` BIGINT UNSIGNED NULL,
    `updated_by_membership_id` BIGINT UNSIGNED NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`shift_id`),
    UNIQUE KEY `uq005_shifts_tenant_shift` (`tenant_id`, `shift_id`),
    UNIQUE KEY `uq005_shifts_employee_start` (`tenant_id`, `employee_id`, `shift_start_utc`),
    KEY `ix005_shifts_tenant_window` (`tenant_id`, `shift_start_utc`, `shift_end_utc`),
    KEY `ix005_shifts_employee_window` (`tenant_id`, `employee_id`, `shift_start_utc`),
    CONSTRAINT `fk005_shifts_employee`
        FOREIGN KEY (`tenant_id`, `employee_id`) REFERENCES `employees` (`tenant_id`, `employee_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_shifts_created_by`
        FOREIGN KEY (`tenant_id`, `created_by_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_shifts_updated_by`
        FOREIGN KEY (`tenant_id`, `updated_by_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_shifts_window` CHECK (`shift_end_utc` > `shift_start_utc`),
    CONSTRAINT `chk005_shifts_status`
        CHECK (`shift_status` IN ('draft', 'published', 'started', 'completed', 'cancelled', 'missed'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Planned or recorded activities inside a shift. Overlap and containment
-- are validated by the Python scheduling service (MySQL has no exclusion constraint).
CREATE TABLE `workforce_shift_activities` (
    `shift_activity_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `shift_id` BIGINT UNSIGNED NOT NULL,
    `activity_code` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `activity_start_utc` DATETIME(6) NOT NULL,
    `activity_end_utc` DATETIME(6) NOT NULL,
    `activity_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'planned',
    `is_paid_activity` TINYINT(1) NOT NULL DEFAULT 1,
    `counts_toward_contact_capacity` TINYINT(1) NOT NULL DEFAULT 0,
    `activity_notes` VARCHAR(255) NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`shift_activity_id`),
    UNIQUE KEY `uq005_shift_activities_tenant_id` (`tenant_id`, `shift_activity_id`),
    KEY `ix005_shift_activities_shift_window` (`tenant_id`, `shift_id`, `activity_start_utc`),
    KEY `ix005_shift_activities_tenant_window` (`tenant_id`, `activity_start_utc`, `activity_end_utc`),
    CONSTRAINT `fk005_shift_activities_shift`
        FOREIGN KEY (`tenant_id`, `shift_id`) REFERENCES `workforce_shifts` (`tenant_id`, `shift_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_shift_activity_code`
        CHECK (`activity_code` IN ('break', 'lunch', 'training', 'meeting', 'coaching', 'occupied', 'idle', 'other')),
    CONSTRAINT `chk005_shift_activity_status`
        CHECK (`activity_status` IN ('planned', 'actual', 'cancelled')),
    CONSTRAINT `chk005_shift_activity_window` CHECK (`activity_end_utc` > `activity_start_utc`),
    CONSTRAINT `chk005_shift_activity_paid` CHECK (`is_paid_activity` IN (0, 1)),
    CONSTRAINT `chk005_shift_activity_capacity` CHECK (`counts_toward_contact_capacity` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Queue requirements: a queue can require one or more skills and minimum proficiency.
CREATE TABLE `queue_skill_requirements` (
    `queue_skill_requirement_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `queue_id` BIGINT UNSIGNED NOT NULL,
    `skill_id` BIGINT UNSIGNED NOT NULL,
    `minimum_proficiency_level` TINYINT UNSIGNED NOT NULL DEFAULT 1,
    `requirement_type` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'required',
    `priority_weight` DECIMAL(6,3) NOT NULL DEFAULT 1.000,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`queue_skill_requirement_id`),
    UNIQUE KEY `uq005_queue_skill` (`tenant_id`, `queue_id`, `skill_id`),
    KEY `ix005_queue_skill_requirements_skill` (`tenant_id`, `skill_id`, `is_active`),
    CONSTRAINT `fk005_queue_skill_queue`
        FOREIGN KEY (`tenant_id`, `queue_id`) REFERENCES `queues` (`tenant_id`, `queue_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_queue_skill_skill`
        FOREIGN KEY (`tenant_id`, `skill_id`) REFERENCES `workforce_skills` (`tenant_id`, `skill_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_queue_skill_level` CHECK (`minimum_proficiency_level` BETWEEN 1 AND 5),
    CONSTRAINT `chk005_queue_skill_type` CHECK (`requirement_type` IN ('required', 'preferred')),
    CONSTRAINT `chk005_queue_skill_weight` CHECK (`priority_weight` >= 0),
    CONSTRAINT `chk005_queue_skill_active` CHECK (`is_active` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. Append-only actual state transitions. Current state is derived from the
-- latest event; event history allows adherence and occupancy reconstruction.
CREATE TABLE `workforce_agent_state_events` (
    `agent_state_event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `employee_id` BIGINT UNSIGNED NOT NULL,
    `queue_id` BIGINT UNSIGNED NULL,
    `channel_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `state_code` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `event_at_utc` DATETIME(6) NOT NULL,
    `event_source_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'manual',
    `external_event_id` VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `event_details_json` JSON NULL,
    `recorded_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`agent_state_event_id`),
    UNIQUE KEY `uq005_state_event_tenant_id` (`tenant_id`, `agent_state_event_id`),
    UNIQUE KEY `uq005_state_event_external` (`tenant_id`, `event_source_code`, `external_event_id`),
    KEY `ix005_state_event_employee_time` (`tenant_id`, `employee_id`, `event_at_utc`),
    KEY `ix005_state_event_queue_time` (`tenant_id`, `queue_id`, `event_at_utc`),
    CONSTRAINT `fk005_state_event_employee`
        FOREIGN KEY (`tenant_id`, `employee_id`) REFERENCES `employees` (`tenant_id`, `employee_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_state_event_queue`
        FOREIGN KEY (`tenant_id`, `queue_id`) REFERENCES `queues` (`tenant_id`, `queue_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk005_state_event_channel`
        FOREIGN KEY (`channel_code`) REFERENCES `channels` (`channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk005_state_event_code`
        CHECK (`state_code` IN ('available', 'offered', 'ringing', 'occupied', 'after_contact_work', 'break', 'lunch', 'training', 'meeting', 'offline', 'not_ready', 'idle', 'other'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seed only tenant-scoped language and channel skills from existing reference data.
-- No employees, queues, schedules, or operational state events are fabricated.
INSERT INTO `workforce_skills`
    (`tenant_id`, `skill_code`, `skill_name`, `skill_category`, `language_code`)
SELECT t.`tenant_id`, CONCAT('language_', l.`language_code`),
       CONCAT('Language ', l.`language_code`), 'language', l.`language_code`
FROM `tenants` AS t
CROSS JOIN `languages` AS l
WHERE t.`tenant_status` = 'active'
  AND l.`is_active` = 1
  AND NOT EXISTS (
      SELECT 1 FROM `workforce_skills` AS ws
      WHERE ws.`tenant_id` = t.`tenant_id`
        AND ws.`skill_code` = CONCAT('language_', l.`language_code`)
  );

INSERT INTO `workforce_skills`
    (`tenant_id`, `skill_code`, `skill_name`, `skill_category`, `channel_code`)
SELECT t.`tenant_id`, CONCAT('channel_', c.`channel_code`),
       CONCAT('Channel ', c.`channel_code`), 'channel', c.`channel_code`
FROM `tenants` AS t
CROSS JOIN `channels` AS c
WHERE t.`tenant_status` = 'active'
  AND c.`is_active` = 1
  AND NOT EXISTS (
      SELECT 1 FROM `workforce_skills` AS ws
      WHERE ws.`tenant_id` = t.`tenant_id`
        AND ws.`skill_code` = CONCAT('channel_', c.`channel_code`)
  );

SELECT
    'Migration 005 WFM workforce foundation created.' AS migration_005_status,
    (SELECT COUNT(*) FROM `employees`) AS employees_created,
    (SELECT COUNT(*) FROM `workforce_skills`) AS tenant_skills_seeded,
    (SELECT COUNT(*) FROM `workforce_shifts`) AS shifts_created;
