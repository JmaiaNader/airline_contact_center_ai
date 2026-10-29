-- Migration 001: Core operational schema for Airline Contact Center AI Platform
-- Target database: db_airlines
-- Requirements: MySQL 8.0.16+ (CHECK constraints are enforced in this version and later).
--
-- MANUAL PRE-FLIGHT (run separately and inspect the result before this file):
--   SELECT DATABASE();
--   SELECT COUNT(*) AS existing_base_tables
--   FROM information_schema.tables
--   WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
--
-- Continue only when the selected schema is the intended db_airlines database and
-- the expected empty database has zero base tables. Back up first if it is not empty.
-- Use a developer/DBA migration account; the runtime application account must not have DDL rights.
-- MySQL DDL implicitly commits. If a statement fails part-way through, STOP and inspect
-- information_schema before deciding how to recover. Do not blindly rerun the file.
-- This migration creates no service, queue, booking, interaction, or SLA seed records.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';
USE `db_airlines`;

CREATE TABLE `markets` (
    `market_code` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `market_name` VARCHAR(100) NOT NULL,
    `country_code` CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `reporting_timezone` VARCHAR(64) NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`market_code`),
    CONSTRAINT `chk_markets_active` CHECK (`is_active` IN (0, 1)),
    CONSTRAINT `chk_markets_country_code` CHECK (
        `country_code` IS NULL OR `country_code` REGEXP '^[A-Z]{2}$'
    )
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `languages` (
    `language_code` VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `display_name` VARCHAR(80) NOT NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`language_code`),
    CONSTRAINT `chk_languages_active` CHECK (`is_active` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `channels` (
    `channel_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `display_name` VARCHAR(80) NOT NULL,
    `is_synchronous` TINYINT(1) NOT NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`channel_code`),
    CONSTRAINT `chk_channels_synchronous` CHECK (`is_synchronous` IN (0, 1)),
    CONSTRAINT `chk_channels_active` CHECK (`is_active` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `services` (
    `service_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `display_name` VARCHAR(100) NOT NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`service_code`),
    CONSTRAINT `chk_services_active` CHECK (`is_active` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `queues` (
    `queue_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `queue_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `queue_name` VARCHAR(128) NOT NULL,
    `service_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `channel_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`queue_id`),
    UNIQUE KEY `uq_queues_queue_code` (`queue_code`),
    UNIQUE KEY `uq_queues_id_channel` (`queue_id`, `channel_code`),
    KEY `ix_queues_service` (`service_code`),
    KEY `ix_queues_channel` (`channel_code`),
    CONSTRAINT `fk_queues_service`
        FOREIGN KEY (`service_code`) REFERENCES `services` (`service_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_queues_channel`
        FOREIGN KEY (`channel_code`) REFERENCES `channels` (`channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk_queues_active` CHECK (`is_active` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `bookings` (
    `booking_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `booking_reference` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `booking_status` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'unknown',
    `scheduled_departure_utc` DATETIME(6) NULL,
    `origin_airport_code` CHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `destination_airport_code` CHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`booking_id`),
    UNIQUE KEY `uq_bookings_reference` (`booking_reference`),
    KEY `ix_bookings_departure` (`scheduled_departure_utc`),
    CONSTRAINT `chk_bookings_status` CHECK (
        `booking_status` IN ('confirmed', 'cancelled', 'ticketed', 'unknown')
    ),
    CONSTRAINT `chk_bookings_reference_uppercase` CHECK (
        `booking_reference` = UPPER(`booking_reference`)
    )
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `contact_interactions` (
    `interaction_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `conversation_reference` VARCHAR(100) NULL,
    `queue_leg_number` SMALLINT UNSIGNED NULL,
    `market_code` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `channel_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `queue_id` BIGINT UNSIGNED NOT NULL,
    `service_language_code` VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `booking_id` BIGINT UNSIGNED NULL,
    `offered_at_utc` DATETIME(6) NOT NULL,
    `answered_at_utc` DATETIME(6) NULL,
    `ended_at_utc` DATETIME(6) NULL,
    `abandoned_at_utc` DATETIME(6) NULL,
    `talk_seconds` INT UNSIGNED NULL,
    `hold_seconds` INT UNSIGNED NULL,
    `after_contact_work_seconds` INT UNSIGNED NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`interaction_id`),
    UNIQUE KEY `uq_interactions_conversation_leg` (`conversation_reference`, `queue_leg_number`),
    KEY `ix_interactions_offered_at` (`offered_at_utc`),
    KEY `ix_interactions_market_offered` (`market_code`, `offered_at_utc`),
    KEY `ix_interactions_queue_offered` (`queue_id`, `offered_at_utc`),
    KEY `ix_interactions_channel_offered` (`channel_code`, `offered_at_utc`),
    KEY `ix_interactions_language_offered` (`service_language_code`, `offered_at_utc`),
    KEY `ix_interactions_booking` (`booking_id`),
    CONSTRAINT `fk_interactions_market`
        FOREIGN KEY (`market_code`) REFERENCES `markets` (`market_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_interactions_channel`
        FOREIGN KEY (`channel_code`) REFERENCES `channels` (`channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_interactions_queue_channel`
        FOREIGN KEY (`queue_id`, `channel_code`)
        REFERENCES `queues` (`queue_id`, `channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_interactions_language`
        FOREIGN KEY (`service_language_code`) REFERENCES `languages` (`language_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_interactions_booking`
        FOREIGN KEY (`booking_id`) REFERENCES `bookings` (`booking_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk_interactions_conversation_leg` CHECK (
        (`conversation_reference` IS NULL AND `queue_leg_number` IS NULL)
        OR (`conversation_reference` IS NOT NULL AND `queue_leg_number` IS NOT NULL
            AND `queue_leg_number` >= 1)
    ),
    CONSTRAINT `chk_interactions_answered_after_offered` CHECK (
        `answered_at_utc` IS NULL OR `answered_at_utc` >= `offered_at_utc`
    ),
    CONSTRAINT `chk_interactions_ended_after_offered` CHECK (
        `ended_at_utc` IS NULL OR `ended_at_utc` >= `offered_at_utc`
    ),
    CONSTRAINT `chk_interactions_abandoned_after_offered` CHECK (
        `abandoned_at_utc` IS NULL OR `abandoned_at_utc` >= `offered_at_utc`
    ),
    CONSTRAINT `chk_interactions_answered_before_ended` CHECK (
        `answered_at_utc` IS NULL OR `ended_at_utc` IS NULL OR `ended_at_utc` >= `answered_at_utc`
    )
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sla_rules` (
    `sla_rule_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `queue_id` BIGINT UNSIGNED NOT NULL,
    `market_code` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `measurement_mode` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `response_target_seconds` INT UNSIGNED NOT NULL,
    `target_service_level_pct` DECIMAL(5, 2) NOT NULL,
    `short_abandon_seconds` INT UNSIGNED NULL,
    `exclude_short_abandons` TINYINT(1) NOT NULL DEFAULT 0,
    `effective_from_utc` DATETIME(6) NOT NULL,
    `effective_to_utc` DATETIME(6) NULL,
    `definition_version` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`sla_rule_id`),
    UNIQUE KEY `uq_sla_rule_queue_market_start` (`queue_id`, `market_code`, `effective_from_utc`),
    KEY `ix_sla_rule_lookup` (`queue_id`, `market_code`, `effective_from_utc`, `effective_to_utc`),
    CONSTRAINT `fk_sla_rules_queue`
        FOREIGN KEY (`queue_id`) REFERENCES `queues` (`queue_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_sla_rules_market`
        FOREIGN KEY (`market_code`) REFERENCES `markets` (`market_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk_sla_measurement_mode` CHECK (
        `measurement_mode` IN ('answer_within_target', 'first_response_within_target')
    ),
    CONSTRAINT `chk_sla_response_target_positive` CHECK (`response_target_seconds` > 0),
    CONSTRAINT `chk_sla_target_percentage` CHECK (
        `target_service_level_pct` >= 0 AND `target_service_level_pct` <= 100
    ),
    CONSTRAINT `chk_sla_short_abandon_rule` CHECK (
        `exclude_short_abandons` IN (0, 1)
        AND (`exclude_short_abandons` = 0 OR `short_abandon_seconds` IS NOT NULL)
    ),
    CONSTRAINT `chk_sla_effective_period` CHECK (
        `effective_to_utc` IS NULL OR `effective_to_utc` > `effective_from_utc`
    )
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Expected table count from this migration: 8.
-- Intentionally not created here: workforce, historical interval facts, forecasts,
-- schedule/adherence, RTM alerts/actions, policy metadata, audit/evaluation tables.
