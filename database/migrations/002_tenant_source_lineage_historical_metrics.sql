-- AeroInsight / airline_contact_center_ai
-- Migration 002 DRAFT: tenant foundation, source lineage, historical interval facts
-- Target schema: db_airlines
-- Status: REVIEW DRAFT. Do not execute until database/checks/002_preflight.sql passes
-- and the operator has reviewed docs/migration_002_review.md.
--
-- IMPORTANT:
-- 1) Take a restorable backup first.
-- 2) This migration is intentionally NOT idempotent. Do not rerun blindly.
-- 3) MySQL DDL implicitly commits; a partial failure requires inspection/recovery.
-- 4) Use a developer/DBA account. Do not grant DDL privileges to the runtime app.
-- 5) This migration assigns any pre-existing tenant-owned records to the explicit
--    development tenant 'demo_airline'. Preflight must stop if that is not desired.
-- 6) markets, languages, and channels remain platform-level shared catalogs in v1.
--    services, queues, bookings, contact_interactions, and sla_rules become tenant-scoped.
-- 7) Schema tenant keys do NOT replace authorization checks in Python repositories.

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

-- 1. Tenant registry. No user accounts or memberships are created in this migration.
CREATE TABLE `tenants` (
    `tenant_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `display_name` VARCHAR(128) NOT NULL,
    `tenant_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`tenant_id`),
    UNIQUE KEY `uq_tenants_tenant_code` (`tenant_code`),
    CONSTRAINT `chk_tenants_status`
        CHECK (`tenant_status` IN ('active', 'suspended', 'closed'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Explicit development tenant. Replace neither this row nor its ID by assumption;
-- the ID is captured through LAST_INSERT_ID() for safe backfilling in this session.
INSERT INTO `tenants` (`tenant_code`, `display_name`, `tenant_status`)
VALUES ('demo_airline', 'Demo Airline (development only)', 'active');
SET @demo_tenant_id := LAST_INSERT_ID();

-- 2. Drop the old service FK before changing the services primary key to be tenant-scoped.
ALTER TABLE `queues`
    DROP FOREIGN KEY `fk_queues_service`;

-- The existing interaction FK depends on queues.uq_queues_id_channel, so drop it
-- before replacing that index with a tenant-scoped unique key.
ALTER TABLE `contact_interactions`
    DROP FOREIGN KEY `fk_interactions_queue_channel`;

ALTER TABLE `services`
    ADD COLUMN `tenant_id` BIGINT UNSIGNED NULL AFTER `service_code`;
UPDATE `services`
    SET `tenant_id` = @demo_tenant_id
    WHERE `tenant_id` IS NULL;
ALTER TABLE `services`
    MODIFY COLUMN `tenant_id` BIGINT UNSIGNED NOT NULL,
    DROP PRIMARY KEY,
    ADD PRIMARY KEY (`tenant_id`, `service_code`),
    ADD CONSTRAINT `fk_services_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

-- 3. Scope queues to a tenant and make service/channel relationships tenant-safe.
ALTER TABLE `queues`
    ADD COLUMN `tenant_id` BIGINT UNSIGNED NULL AFTER `queue_id`;
UPDATE `queues`
    SET `tenant_id` = @demo_tenant_id
    WHERE `tenant_id` IS NULL;
ALTER TABLE `queues`
    MODIFY COLUMN `tenant_id` BIGINT UNSIGNED NOT NULL,
    DROP INDEX `uq_queues_queue_code`,
    DROP INDEX `uq_queues_id_channel`,
    DROP INDEX `ix_queues_service`,
    ADD UNIQUE KEY `uq_queues_tenant_queue_code` (`tenant_id`, `queue_code`),
    ADD UNIQUE KEY `uq_queues_tenant_queue_id` (`tenant_id`, `queue_id`),
    ADD UNIQUE KEY `uq_queues_tenant_queue_channel` (`tenant_id`, `queue_id`, `channel_code`),
    ADD KEY `ix_queues_tenant_service` (`tenant_id`, `service_code`),
    ADD CONSTRAINT `fk_queues_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT `fk_queues_service`
        FOREIGN KEY (`tenant_id`, `service_code`)
        REFERENCES `services` (`tenant_id`, `service_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

-- 4. Scope bookings. Booking references may repeat across tenants, not within one tenant.
ALTER TABLE `bookings`
    ADD COLUMN `tenant_id` BIGINT UNSIGNED NULL AFTER `booking_id`;
UPDATE `bookings`
    SET `tenant_id` = @demo_tenant_id
    WHERE `tenant_id` IS NULL;
ALTER TABLE `bookings`
    MODIFY COLUMN `tenant_id` BIGINT UNSIGNED NOT NULL,
    DROP INDEX `uq_bookings_reference`,
    ADD UNIQUE KEY `uq_bookings_tenant_reference` (`tenant_id`, `booking_reference`),
    ADD UNIQUE KEY `uq_bookings_tenant_booking_id` (`tenant_id`, `booking_id`),
    ADD KEY `ix_bookings_tenant_departure` (`tenant_id`, `scheduled_departure_utc`),
    ADD CONSTRAINT `fk_bookings_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

-- 5. Scope contact interactions and make booking/queue references tenant-safe.
ALTER TABLE `contact_interactions`
    ADD COLUMN `tenant_id` BIGINT UNSIGNED NULL AFTER `interaction_id`;
UPDATE `contact_interactions`
    SET `tenant_id` = @demo_tenant_id
    WHERE `tenant_id` IS NULL;
ALTER TABLE `contact_interactions`
    MODIFY COLUMN `tenant_id` BIGINT UNSIGNED NOT NULL,
    DROP INDEX `uq_interactions_conversation_leg`,
    DROP FOREIGN KEY `fk_interactions_booking`,
    ADD UNIQUE KEY `uq_interactions_tenant_conversation_leg`
        (`tenant_id`, `conversation_reference`, `queue_leg_number`),
    ADD KEY `ix_interactions_tenant_queue_channel`
        (`tenant_id`, `queue_id`, `channel_code`),
    ADD KEY `ix_interactions_tenant_booking` (`tenant_id`, `booking_id`),
    ADD CONSTRAINT `fk_interactions_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT `fk_interactions_queue_channel`
        FOREIGN KEY (`tenant_id`, `queue_id`, `channel_code`)
        REFERENCES `queues` (`tenant_id`, `queue_id`, `channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT `fk_interactions_booking`
        FOREIGN KEY (`tenant_id`, `booking_id`)
        REFERENCES `bookings` (`tenant_id`, `booking_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

-- 6. Scope SLA rules to the same tenant as their queue.
ALTER TABLE `sla_rules`
    ADD COLUMN `tenant_id` BIGINT UNSIGNED NULL AFTER `sla_rule_id`;
UPDATE `sla_rules`
    SET `tenant_id` = @demo_tenant_id
    WHERE `tenant_id` IS NULL;
ALTER TABLE `sla_rules`
    MODIFY COLUMN `tenant_id` BIGINT UNSIGNED NOT NULL,
    DROP INDEX `uq_sla_rule_queue_market_start`,
    DROP INDEX `ix_sla_rule_lookup`,
    DROP FOREIGN KEY `fk_sla_rules_queue`,
    ADD UNIQUE KEY `uq_sla_rule_tenant_queue_market_start`
        (`tenant_id`, `queue_id`, `market_code`, `effective_from_utc`),
    ADD KEY `ix_sla_rule_tenant_lookup`
        (`tenant_id`, `queue_id`, `market_code`, `effective_from_utc`, `effective_to_utc`),
    ADD CONSTRAINT `fk_sla_rules_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT `fk_sla_rules_queue`
        FOREIGN KEY (`tenant_id`, `queue_id`)
        REFERENCES `queues` (`tenant_id`, `queue_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

-- 7. Register source systems. Store connection metadata only, never passwords/API keys.
CREATE TABLE `source_systems` (
    `source_system_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `source_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `display_name` VARCHAR(128) NOT NULL,
    `source_type` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `source_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`source_system_id`),
    UNIQUE KEY `uq_source_systems_tenant_code` (`tenant_id`, `source_code`),
    UNIQUE KEY `uq_source_systems_tenant_id` (`tenant_id`, `source_system_id`),
    CONSTRAINT `fk_source_systems_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk_source_systems_type`
        CHECK (`source_type` IN ('csv', 'excel', 'mysql', 'api', 'manual', 'other')),
    CONSTRAINT `chk_source_systems_status`
        CHECK (`source_status` IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. Track every import attempt and make identical file imports idempotently detectable.
CREATE TABLE `ingestion_batches` (
    `ingestion_batch_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `source_system_id` BIGINT UNSIGNED NOT NULL,
    `batch_type` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'historical_interval_metrics',
    `source_file_name` VARCHAR(255) NULL,
    `source_content_sha256` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `batch_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'received',
    `records_received` BIGINT UNSIGNED NULL,
    `records_accepted` BIGINT UNSIGNED NOT NULL DEFAULT 0,
    `records_rejected` BIGINT UNSIGNED NOT NULL DEFAULT 0,
    `validation_summary_json` JSON NULL,
    `received_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `completed_at_utc` DATETIME(6) NULL,
    PRIMARY KEY (`ingestion_batch_id`),
    UNIQUE KEY `uq_ingestion_batches_tenant_source_batch`
        (`tenant_id`, `source_system_id`, `ingestion_batch_id`),
    UNIQUE KEY `uq_ingestion_batches_content_hash`
        (`tenant_id`, `source_system_id`, `source_content_sha256`),
    KEY `ix_ingestion_batches_tenant_status_time`
        (`tenant_id`, `batch_status`, `received_at_utc`),
    CONSTRAINT `fk_ingestion_batches_source`
        FOREIGN KEY (`tenant_id`, `source_system_id`)
        REFERENCES `source_systems` (`tenant_id`, `source_system_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk_ingestion_batches_type`
        CHECK (`batch_type` = 'historical_interval_metrics'),
    CONSTRAINT `chk_ingestion_batches_status`
        CHECK (`batch_status` IN ('received', 'validating', 'validated', 'loaded', 'failed', 'rejected')),
    CONSTRAINT `chk_ingestion_batches_counts`
        CHECK (`records_received` IS NULL OR
               `records_accepted` + `records_rejected` <= `records_received`),
    CONSTRAINT `chk_ingestion_batches_completed`
        CHECK (`completed_at_utc` IS NULL OR `completed_at_utc` >= `received_at_utc`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. Store historical interval aggregates for forecasting and source reconciliation.
-- Keep counts/numerators/denominators separately. Source-reported averages/percentages
-- are retained only for reconciliation; canonical KPI outputs remain calculated in Python/SQL.
CREATE TABLE `historical_interval_metrics` (
    `historical_interval_metric_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `source_system_id` BIGINT UNSIGNED NOT NULL,
    `ingestion_batch_id` BIGINT UNSIGNED NOT NULL,
    `source_row_number` BIGINT UNSIGNED NOT NULL,
    `interval_start_utc` DATETIME(6) NOT NULL,
    `interval_seconds` INT UNSIGNED NOT NULL,
    `market_code` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `channel_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `service_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `queue_id` BIGINT UNSIGNED NULL,
    `service_language_code` VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `offered_contacts` BIGINT UNSIGNED NULL,
    `answered_contacts` BIGINT UNSIGNED NULL,
    `handled_contacts` BIGINT UNSIGNED NULL,
    `abandoned_contacts` BIGINT UNSIGNED NULL,
    `sla_eligible_contacts` BIGINT UNSIGNED NULL,
    `answered_within_threshold_contacts` BIGINT UNSIGNED NULL,
    `total_handle_seconds` BIGINT UNSIGNED NULL,
    `total_answer_wait_seconds` BIGINT UNSIGNED NULL,
    `source_reported_aht_seconds` DECIMAL(12,3) NULL,
    `source_reported_asa_seconds` DECIMAL(12,3) NULL,
    `source_reported_sla_percent` DECIMAL(5,2) NULL,
    `quality_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'unreviewed',
    `quality_notes_json` JSON NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`historical_interval_metric_id`),
    UNIQUE KEY `uq_historical_metric_batch_row`
        (`tenant_id`, `ingestion_batch_id`, `source_row_number`),
    KEY `ix_historical_metrics_tenant_interval`
        (`tenant_id`, `interval_start_utc`),
    KEY `ix_historical_metrics_tenant_channel_interval`
        (`tenant_id`, `channel_code`, `interval_start_utc`),
    KEY `ix_historical_metrics_tenant_queue_interval`
        (`tenant_id`, `queue_id`, `interval_start_utc`),
    CONSTRAINT `fk_historical_metrics_source`
        FOREIGN KEY (`tenant_id`, `source_system_id`)
        REFERENCES `source_systems` (`tenant_id`, `source_system_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_historical_metrics_batch_source`
        FOREIGN KEY (`tenant_id`, `source_system_id`, `ingestion_batch_id`)
        REFERENCES `ingestion_batches` (`tenant_id`, `source_system_id`, `ingestion_batch_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_historical_metrics_market`
        FOREIGN KEY (`market_code`) REFERENCES `markets` (`market_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_historical_metrics_channel`
        FOREIGN KEY (`channel_code`) REFERENCES `channels` (`channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_historical_metrics_service`
        FOREIGN KEY (`tenant_id`, `service_code`)
        REFERENCES `services` (`tenant_id`, `service_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_historical_metrics_queue_channel`
        FOREIGN KEY (`tenant_id`, `queue_id`, `channel_code`)
        REFERENCES `queues` (`tenant_id`, `queue_id`, `channel_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_historical_metrics_language`
        FOREIGN KEY (`service_language_code`) REFERENCES `languages` (`language_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk_historical_interval_positive`
        CHECK (`interval_seconds` > 0),
    CONSTRAINT `chk_historical_sla_counts`
        CHECK (`sla_eligible_contacts` IS NULL OR `answered_within_threshold_contacts` IS NULL OR
               `answered_within_threshold_contacts` <= `sla_eligible_contacts`),
    CONSTRAINT `chk_historical_reported_sla`
        CHECK (`source_reported_sla_percent` IS NULL OR
               (`source_reported_sla_percent` >= 0 AND `source_reported_sla_percent` <= 100)),
    CONSTRAINT `chk_historical_quality_status`
        CHECK (`quality_status` IN ('unreviewed', 'valid', 'warning', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- End of Migration 002 draft.
-- Before considering this migration complete, run database/checks/002_postflight.sql
-- and update the Python repositories to require an authorized tenant context for all
-- tenant-owned table reads/writes. A tenant_id column alone is not a complete auth system.
