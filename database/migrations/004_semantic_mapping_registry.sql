-- AeroInsight Migration 004: governed semantic catalog and tenant-scoped mapping history
-- Target: db_airlines
-- Adds persistent business concepts and reviewed source-field mappings.
-- Does not read or modify customer/contact data. Does not auto-approve mappings.
-- Run once after Migration 002 and Migration 003 have completed successfully.
-- MySQL DDL implicitly commits. If execution fails part-way, inspect state; do not rerun blindly.

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

-- 1. Shared, versioned semantic concept catalog.
CREATE TABLE `semantic_concepts` (
    `concept_key` VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `concept_version` SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    `display_name` VARCHAR(128) NOT NULL,
    `description` VARCHAR(1000) NOT NULL,
    `aliases_json` JSON NOT NULL,
    `expected_types_json` JSON NOT NULL,
    `required_approval_fields_json` JSON NOT NULL,
    `concept_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`concept_key`, `concept_version`),
    KEY `ix004_semantic_concepts_status` (`concept_status`, `concept_key`),
    CONSTRAINT `chk004_semantic_concept_version` CHECK (`concept_version` > 0),
    CONSTRAINT `chk004_semantic_concept_status` CHECK (`concept_status` IN ('active', 'deprecated'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Version 1 of the platform catalog. These definitions mirror src/discovery/catalog.py.
INSERT INTO `semantic_concepts`
    (`concept_key`, `concept_version`, `display_name`, `description`, `aliases_json`, `expected_types_json`, `required_approval_fields_json`)
VALUES
('customer_satisfaction_score', 1, 'Customer satisfaction score',
 'A customer survey measure of satisfaction. Confirm scale, population, survey timing and calculation method per source.',
 JSON_ARRAY('csat','csat_score','customer_score','customer_satisfaction','satisfaction_score','survey_rating','survey_score'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','measurement_scale','population','time_window','exclusions')),
('net_promoter_score', 1, 'Net Promoter Score',
 'A recommendation measure. Verify survey question and NPS calculation; do not infer them from the column name.',
 JSON_ARRAY('nps','nps_score','promoter_score','recommendation_score'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','measurement_scale','population','time_window','formula','exclusions')),
('agent_quality_score', 1, 'Agent quality score',
 'A quality-assurance score. Confirm rubric, scale and evaluated population.',
 JSON_ARRAY('qa_score','quality_score','agent_rating'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','measurement_scale','population','time_window','formula','exclusions')),
('average_handle_time_seconds', 1, 'Average handle time (seconds)',
 'Average handling duration. Confirm included components and unit before using it as AHT.',
 JSON_ARRAY('aht','aht_seconds','aht_secs','avg_handle_time','average_handle_time','handle_time_seconds'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','unit','grain','time_window','population','exclusions')),
('service_level_pct', 1, 'Service level (%)',
 'Share of eligible contacts answered within a defined threshold. Confirm formula and denominator.',
 JSON_ARRAY('service_level','service_level_pct','sla_pct','answered_within_target_pct'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','unit','formula','denominator','threshold','population','time_window','exclusions')),
('offered_contacts', 1, 'Offered contacts',
 'Count of contacts offered. Confirm event definition and aggregation grain.',
 JSON_ARRAY('offered','offered_count','contacts_offered'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','grain','time_window','population','exclusions')),
('handled_contacts', 1, 'Handled contacts',
 'Count of handled contacts according to a source-specific handling definition.',
 JSON_ARRAY('handled','handled_count','contacts_handled'),
 JSON_ARRAY('integer','number'),
 JSON_ARRAY('business_definition','grain','time_window','population','exclusions')),
('customer_feedback_text', 1, 'Customer feedback text',
 'Free-text customer feedback. Review language, access permissions and privacy controls before use.',
 JSON_ARRAY('customer_feedback','feedback_text','customer_comment','survey_comment','comment'),
 JSON_ARRAY('text'),
 JSON_ARRAY('business_definition','population','time_window','privacy_review')),
('contact_reference', 1, 'Contact reference',
 'A source-local identifier for a contact or interaction. Confirm uniqueness scope and privacy handling.',
 JSON_ARRAY('contact_id','interaction_id','case_id','contact_ref'),
 JSON_ARRAY('identifier','text','integer'),
 JSON_ARRAY('business_definition','uniqueness_scope','privacy_review'));

-- 2. Tenant-scoped, versioned mappings. Suggestions are never approvals.
CREATE TABLE `tenant_source_field_mappings` (
    `mapping_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `source_system_id` BIGINT UNSIGNED NOT NULL,
    `source_schema_name` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `source_table_name` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    `source_column_name` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    `mapping_version` INT UNSIGNED NOT NULL,
    `mapping_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `suggested_concept_key` VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `suggested_concept_version` SMALLINT UNSIGNED NULL,
    `selected_concept_key` VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `selected_concept_version` SMALLINT UNSIGNED NULL,
    `fit_score` DECIMAL(5,3) NULL,
    `type_compatible` TINYINT(1) NULL,
    `candidate_details_json` JSON NOT NULL,
    `review_evidence_json` JSON NULL,
    `rejection_reason` VARCHAR(1000) NULL,
    `created_by_membership_id` BIGINT UNSIGNED NOT NULL,
    `reviewed_by_membership_id` BIGINT UNSIGNED NULL,
    `is_current` TINYINT(1) NOT NULL DEFAULT 1,
    `current_slot` TINYINT GENERATED ALWAYS AS (CASE WHEN `is_current` = 1 THEN 1 ELSE NULL END) STORED,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `reviewed_at_utc` DATETIME(6) NULL,
    PRIMARY KEY (`mapping_id`),
    UNIQUE KEY `uq004_mapping_source_field_version`
        (`tenant_id`, `source_system_id`, `source_schema_name`, `source_table_name`, `source_column_name`, `mapping_version`),
    UNIQUE KEY `uq004_mapping_current_field`
        (`tenant_id`, `source_system_id`, `source_schema_name`, `source_table_name`, `source_column_name`, `current_slot`),
    KEY `ix004_mapping_tenant_status` (`tenant_id`, `mapping_status`, `is_current`),
    KEY `ix004_mapping_source` (`tenant_id`, `source_system_id`, `is_current`),
    KEY `ix004_mapping_concept` (`suggested_concept_key`, `suggested_concept_version`),
    CONSTRAINT `fk004_mapping_source`
        FOREIGN KEY (`tenant_id`, `source_system_id`)
        REFERENCES `source_systems` (`tenant_id`, `source_system_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk004_mapping_creator_membership`
        FOREIGN KEY (`tenant_id`, `created_by_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk004_mapping_reviewer_membership`
        FOREIGN KEY (`tenant_id`, `reviewed_by_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk004_mapping_suggested_concept`
        FOREIGN KEY (`suggested_concept_key`, `suggested_concept_version`)
        REFERENCES `semantic_concepts` (`concept_key`, `concept_version`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk004_mapping_selected_concept`
        FOREIGN KEY (`selected_concept_key`, `selected_concept_version`)
        REFERENCES `semantic_concepts` (`concept_key`, `concept_version`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk004_mapping_version` CHECK (`mapping_version` > 0),
    CONSTRAINT `chk004_mapping_status` CHECK (`mapping_status` IN ('suggested','ambiguous','unmapped','type_mismatch','approved','rejected','superseded')),
    CONSTRAINT `chk004_mapping_score` CHECK (`fit_score` IS NULL OR (`fit_score` >= 0 AND `fit_score` <= 1)),
    CONSTRAINT `chk004_mapping_boolean` CHECK (`type_compatible` IS NULL OR `type_compatible` IN (0,1)),
    CONSTRAINT `chk004_mapping_current` CHECK (`is_current` IN (0,1)),
    CONSTRAINT `chk004_mapping_approved` CHECK (`mapping_status` <> 'approved' OR (`selected_concept_key` IS NOT NULL AND `reviewed_by_membership_id` IS NOT NULL AND `reviewed_at_utc` IS NOT NULL)),
    CONSTRAINT `chk004_mapping_rejected` CHECK (`mapping_status` <> 'rejected' OR (`rejection_reason` IS NOT NULL AND `reviewed_by_membership_id` IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Register the current development database as a source for demo_airline.
-- This stores only registry metadata; no credentials or connection strings are stored.
INSERT INTO `source_systems`
    (`tenant_id`, `source_code`, `display_name`, `source_type`, `source_status`)
SELECT t.`tenant_id`, 'db_airlines_metadata', 'Development database metadata (db_airlines)', 'mysql', 'active'
FROM `tenants` AS t
WHERE t.`tenant_code` = 'demo_airline'
  AND NOT EXISTS (
      SELECT 1 FROM `source_systems` AS s
      WHERE s.`tenant_id` = t.`tenant_id`
        AND s.`source_code` = 'db_airlines_metadata'
  );

SELECT 'Migration 004 semantic mapping registry created. Suggestions remain unapproved.' AS migration_004_status;
