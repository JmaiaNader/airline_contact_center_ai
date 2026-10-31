-- ============================================================================
-- AeroInsight - Synthetic Historical Interval Dataset (DEMO ONLY)
-- Target database: db_airlines
-- Date range: 2026-01-01 00:00 UTC through 2026-10-31 23:45 UTC
-- Grain: 15-minute intervals, 24x7
-- Segments: QATAR/UAE/USA x (voice and WhatsApp) x supported languages
-- Expected rows: 233,472
--
-- IMPORTANT:
--   * These are GENERATED SYNTHETIC DEMO VALUES, NOT REAL AIRLINE OPERATIONS.
--   * Rows are explicitly marked quality_status='warning' and carry
--     production_eligible=false in quality_notes_json.
--   * Synthetic SLA denominator for this demo is offered_contacts.
--     This does NOT redefine AeroInsight's canonical SLA calculation.
--   * services and queues are currently empty, so service_code and queue_id
--     are intentionally NULL.
--   * No customer/passenger/agent-level personal data is generated.
--   * UTC is used for all interval_start_utc values.
--   * The script is re-runnable: it reuses the same source and batch, and
--     inserts only source_row_number values not already present for that batch.
--
-- Run once from MySQL Workbench against your existing db_airlines database.
-- ============================================================================

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

-- 1. Resolve the existing development tenant. No tenant is created here.
SET @tenant_id := (
    SELECT `tenant_id`
    FROM `tenants`
    WHERE `tenant_code` = 'demo_airline'
      AND `tenant_status` = 'active'
    LIMIT 1
);

SELECT
    'db_airlines' AS target_schema,
    @tenant_id AS demo_airline_tenant_id,
    'SYNTHETIC DEMO DATA - NOT REAL OPERATIONS' AS dataset_notice;

-- 2. Create/reuse a clearly labelled synthetic source registry entry.
INSERT INTO `source_systems`
    (`tenant_id`, `source_code`, `display_name`, `source_type`, `source_status`)
SELECT
    @tenant_id,
    'synthetic_historical_2026',
    'Synthetic historical interval demo dataset 2026 (NOT REAL OPERATIONS)',
    'manual',
    'active'
FROM DUAL
WHERE @tenant_id IS NOT NULL
ON DUPLICATE KEY UPDATE
    `display_name` = VALUES(`display_name`),
    `source_status` = 'active';

SET @source_system_id := (
    SELECT `source_system_id`
    FROM `source_systems`
    WHERE `tenant_id` = @tenant_id
      AND `source_code` = 'synthetic_historical_2026'
    LIMIT 1
);

-- 3. Build the deterministic 15-minute interval rows in a TEMPORARY table.
--    304 days * 96 intervals/day * 8 market/channel/language segments.
DROP TEMPORARY TABLE IF EXISTS `tmp_aeroinsight_synthetic_2026`;

CREATE TEMPORARY TABLE `tmp_aeroinsight_synthetic_2026`
ENGINE=InnoDB
AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY `counts`.`interval_start_utc`,
                 `counts`.`market_code`,
                 `counts`.`channel_code`,
                 `counts`.`service_language_code`
    ) AS `source_row_number`,
    `counts`.`interval_start_utc`,
    900 AS `interval_seconds`,
    `counts`.`market_code`,
    `counts`.`channel_code`,
    NULL AS `service_code`,
    NULL AS `queue_id`,
    `counts`.`service_language_code`,
    `counts`.`offered_contacts`,
    `counts`.`answered_contacts`,
    `counts`.`handled_contacts`,
    `counts`.`abandoned_contacts`,
    `counts`.`offered_contacts` AS `sla_eligible_contacts`,
    LEAST(
        `counts`.`answered_contacts`,
        FLOOR(`counts`.`offered_contacts` * `counts`.`sla_target`)
    ) AS `answered_within_threshold_contacts`,
    `counts`.`handled_contacts` * `counts`.`aht_seconds` AS `total_handle_seconds`,
    `counts`.`answered_contacts` * `counts`.`asa_seconds` AS `total_answer_wait_seconds`,
    ROUND(`counts`.`aht_seconds`, 3) AS `source_reported_aht_seconds`,
    ROUND(`counts`.`asa_seconds`, 3) AS `source_reported_asa_seconds`,
    ROUND(
        100.0 * LEAST(
            `counts`.`answered_contacts`,
            FLOOR(`counts`.`offered_contacts` * `counts`.`sla_target`)
        ) / NULLIF(`counts`.`offered_contacts`, 0),
        2
    ) AS `source_reported_sla_percent`
FROM (
    SELECT
        `demand`.`interval_start_utc`,
        `demand`.`market_code`,
        `demand`.`channel_code`,
        `demand`.`service_language_code`,
        `demand`.`sla_target`,
        `demand`.`aht_seconds`,
        `demand`.`asa_seconds`,
        `demand`.`offered_contacts`,
        FLOOR(`demand`.`offered_contacts` * `demand`.`abandon_rate`) AS `abandoned_contacts`,
        `demand`.`offered_contacts`
            - FLOOR(`demand`.`offered_contacts` * `demand`.`abandon_rate`) AS `answered_contacts`,
        `demand`.`offered_contacts`
            - FLOOR(`demand`.`offered_contacts` * `demand`.`abandon_rate`) AS `handled_contacts`
    FROM (
        SELECT
            `base`.`interval_start_utc`,
            `base`.`market_code`,
            `base`.`channel_code`,
            `base`.`service_language_code`,
            `base`.`sla_target`,
            `base`.`aht_seconds`,
            `base`.`asa_seconds`,
            `base`.`abandon_rate`,
            GREATEST(
                1,
                CAST(ROUND(
                    `base`.`base_offered`
                    * `base`.`hour_factor`
                    * `base`.`day_factor`
                    * `base`.`month_factor`
                    * `base`.`jitter_factor`
                ) AS UNSIGNED)
            ) AS `offered_contacts`
        FROM (
            SELECT
                TIMESTAMPADD(
                    MINUTE,
                    `slots`.`slot_number` * 15,
                    TIMESTAMPADD(
                        DAY,
                        `days`.`day_offset`,
                        CAST('2026-01-01 00:00:00' AS DATETIME)
                    )
                ) AS `interval_start_utc`,
                `segments`.`market_code`,
                `segments`.`channel_code`,
                `segments`.`service_language_code`,
                `segments`.`base_offered`,
                CASE
                    WHEN HOUR(TIMESTAMPADD(
                        MINUTE, `slots`.`slot_number` * 15,
                        TIMESTAMPADD(DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME))
                    )) BETWEEN 0 AND 5 THEN 0.45
                    WHEN HOUR(TIMESTAMPADD(
                        MINUTE, `slots`.`slot_number` * 15,
                        TIMESTAMPADD(DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME))
                    )) BETWEEN 6 AND 7 THEN 0.65
                    WHEN HOUR(TIMESTAMPADD(
                        MINUTE, `slots`.`slot_number` * 15,
                        TIMESTAMPADD(DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME))
                    )) BETWEEN 8 AND 11 THEN 1.15
                    WHEN HOUR(TIMESTAMPADD(
                        MINUTE, `slots`.`slot_number` * 15,
                        TIMESTAMPADD(DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME))
                    )) BETWEEN 12 AND 16 THEN 1.25
                    WHEN HOUR(TIMESTAMPADD(
                        MINUTE, `slots`.`slot_number` * 15,
                        TIMESTAMPADD(DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME))
                    )) BETWEEN 17 AND 21 THEN 1.05
                    ELSE 0.70
                END AS `hour_factor`,
                CASE
                    WHEN DAYOFWEEK(TIMESTAMPADD(
                        DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME)
                    )) IN (6, 7) THEN 0.88
                    ELSE 1.00
                END AS `day_factor`,
                1.00 + (MONTH(TIMESTAMPADD(
                    DAY, `days`.`day_offset`, CAST('2026-01-01 00:00:00' AS DATETIME)
                )) - 1) * 0.003 AS `month_factor`,
                0.90 + MOD(
                    `days`.`day_offset` * 7
                    + `slots`.`slot_number` * 3
                    + `segments`.`market_sort` * 5
                    + `segments`.`channel_sort` * 7
                    + `segments`.`language_sort` * 11,
                    21
                ) / 100.0 AS `jitter_factor`,
                CASE
                    WHEN `segments`.`channel_code` = 'voice'
                        THEN 0.035 + MOD(
                            `days`.`day_offset` * 11 + `slots`.`slot_number` * 5
                            + `segments`.`market_sort` * 3 + `segments`.`language_sort`,
                            50
                        ) / 1000.0
                    ELSE 0.010 + MOD(
                        `days`.`day_offset` * 13 + `slots`.`slot_number` * 7
                        + `segments`.`market_sort` * 5,
                        30
                    ) / 1000.0
                END AS `abandon_rate`,
                CASE
                    WHEN `segments`.`channel_code` = 'voice'
                        THEN 0.78 + MOD(
                            `days`.`day_offset` * 3 + `slots`.`slot_number`
                            + `segments`.`market_sort` * 2 + `segments`.`language_sort`,
                            13
                        ) / 100.0
                    ELSE 0.88 + MOD(
                        `days`.`day_offset` * 5 + `slots`.`slot_number`
                        + `segments`.`market_sort`,
                        8
                    ) / 100.0
                END AS `sla_target`,
                CASE
                    WHEN `segments`.`channel_code` = 'voice'
                        THEN 390 + MOD(
                            `days`.`day_offset` * 2 + `slots`.`slot_number`
                            + `segments`.`market_sort` * 9 + `segments`.`language_sort` * 4,
                            91
                        )
                    ELSE 720 + MOD(
                        `days`.`day_offset` * 3 + `slots`.`slot_number`
                        + `segments`.`market_sort` * 13,
                        181
                    )
                END AS `aht_seconds`,
                CASE
                    WHEN `segments`.`channel_code` = 'voice'
                        THEN 20 + MOD(
                            `days`.`day_offset` + `slots`.`slot_number` * 2
                            + `segments`.`market_sort` * 3,
                            36
                        )
                    ELSE 45 + MOD(
                        `days`.`day_offset` * 2 + `slots`.`slot_number`
                        + `segments`.`market_sort` * 5,
                        76
                    )
                END AS `asa_seconds`
            FROM (
                SELECT
                    `ones`.`n` + `tens`.`n` * 10 + `hundreds`.`n` * 100 AS `day_offset`
                FROM
                    (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) AS `ones`
                CROSS JOIN
                    (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) AS `tens`
                CROSS JOIN
                    (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3) AS `hundreds`
                WHERE (`ones`.`n` + `tens`.`n` * 10 + `hundreds`.`n` * 100) < 304
            ) AS `days`
            CROSS JOIN (
                SELECT `ones`.`n` + `tens`.`n` * 10 AS `slot_number`
                FROM
                    (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) AS `ones`
                CROSS JOIN
                    (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) AS `tens`
                WHERE (`ones`.`n` + `tens`.`n` * 10) < 96
            ) AS `slots`
            CROSS JOIN (
                SELECT 1 AS `market_sort`, 'QATAR' AS `market_code`, 'voice' AS `channel_code`, 'ar' AS `service_language_code`, 8 AS `base_offered`, 1 AS `channel_sort`, 1 AS `language_sort`
                UNION ALL SELECT 1, 'QATAR', 'voice', 'en', 12, 1, 2
                UNION ALL SELECT 1, 'QATAR', 'whatsapp', 'en', 5, 2, 2
                UNION ALL SELECT 2, 'UAE', 'voice', 'ar', 6, 1, 1
                UNION ALL SELECT 2, 'UAE', 'voice', 'en', 9, 1, 2
                UNION ALL SELECT 2, 'UAE', 'whatsapp', 'en', 4, 2, 2
                UNION ALL SELECT 3, 'USA', 'voice', 'en', 10, 1, 2
                UNION ALL SELECT 3, 'USA', 'whatsapp', 'en', 5, 2, 2
            ) AS `segments`
        ) AS `base`
    ) AS `demand`
) AS `counts`;

SELECT COUNT(*) INTO @expected_rows FROM `tmp_aeroinsight_synthetic_2026`;

-- 4. Confirm the required shared reference data exists before loading.
SELECT
    @expected_rows AS generated_rows,
    (SELECT COUNT(*) FROM `markets` WHERE `market_code` IN ('QATAR', 'UAE', 'USA')) AS required_markets_found,
    (SELECT COUNT(*) FROM `channels` WHERE `channel_code` IN ('voice', 'whatsapp')) AS required_channels_found,
    (SELECT COUNT(*) FROM `languages` WHERE `language_code` IN ('ar', 'en')) AS required_languages_found;

-- Required counts should be: 204288, 3, 2, 2.
-- If an expected reference is missing, the FK on insert will reject the load.

-- 5. Create/reuse one deterministic ingestion batch for this exact demo dataset.
INSERT INTO `ingestion_batches`
    (`tenant_id`, `source_system_id`, `batch_type`, `source_file_name`,
     `source_content_sha256`, `batch_status`, `records_received`,
     `records_accepted`, `records_rejected`, `validation_summary_json`)
VALUES
    (@tenant_id, @source_system_id, 'historical_interval_metrics',
     'synthetic_historical_intervals_2026-01-01_to_2026-10-31.sql',
     SHA2('AeroInsight|synthetic-demo|v1|2026-01-01|2026-10-31|15m|8-segments', 256),
     'received', @expected_rows, 0, 0,
     JSON_OBJECT(
        'dataset_type', 'synthetic_demo',
        'production_eligible', FALSE,
        'date_start_utc', '2026-01-01 00:00:00',
        'date_end_utc', '2026-10-31 23:45:00',
        'interval_seconds', 900,
        'expected_rows', @expected_rows,
        'note', 'Generated synthetic aggregates. Not actual airline operational data.'
     ))
ON DUPLICATE KEY UPDATE
    `ingestion_batch_id` = LAST_INSERT_ID(`ingestion_batch_id`);

SET @ingestion_batch_id := (
    SELECT `ingestion_batch_id`
    FROM `ingestion_batches`
    WHERE `tenant_id` = @tenant_id
      AND `source_system_id` = @source_system_id
      AND `source_content_sha256` = SHA2(
          'AeroInsight|synthetic-demo|v1|2026-01-01|2026-10-31|15m|8-segments', 256
      )
    LIMIT 1
);

-- 6. Insert all generated rows atomically. Existing row numbers for this batch
--    are skipped on rerun; other FK/check errors are not hidden by INSERT IGNORE.
START TRANSACTION;

INSERT INTO `historical_interval_metrics` (
    `tenant_id`, `source_system_id`, `ingestion_batch_id`, `source_row_number`,
    `interval_start_utc`, `interval_seconds`, `market_code`, `channel_code`,
    `service_code`, `queue_id`, `service_language_code`,
    `offered_contacts`, `answered_contacts`, `handled_contacts`, `abandoned_contacts`,
    `sla_eligible_contacts`, `answered_within_threshold_contacts`,
    `total_handle_seconds`, `total_answer_wait_seconds`,
    `source_reported_aht_seconds`, `source_reported_asa_seconds`,
    `source_reported_sla_percent`, `quality_status`, `quality_notes_json`
)
SELECT
    @tenant_id,
    @source_system_id,
    @ingestion_batch_id,
    `generated`.`source_row_number`,
    `generated`.`interval_start_utc`,
    `generated`.`interval_seconds`,
    `generated`.`market_code`,
    `generated`.`channel_code`,
    `generated`.`service_code`,
    `generated`.`queue_id`,
    `generated`.`service_language_code`,
    `generated`.`offered_contacts`,
    `generated`.`answered_contacts`,
    `generated`.`handled_contacts`,
    `generated`.`abandoned_contacts`,
    `generated`.`sla_eligible_contacts`,
    `generated`.`answered_within_threshold_contacts`,
    `generated`.`total_handle_seconds`,
    `generated`.`total_answer_wait_seconds`,
    `generated`.`source_reported_aht_seconds`,
    `generated`.`source_reported_asa_seconds`,
    `generated`.`source_reported_sla_percent`,
    'warning',
    JSON_OBJECT(
        'dataset_type', 'synthetic_demo',
        'production_eligible', FALSE,
        'generator_version', 'aeroinsight-synthetic-2026-v1',
        'date_range_utc', '2026-01-01 to 2026-10-31',
        'interval_seconds', 900,
        'synthetic_sla_denominator', 'offered_contacts',
        'time_pattern', 'illustrative UTC-based 24x7 demand pattern; not actual market staffing or demand',
        'service_and_queue', 'NULL because tenant services and queues were not configured at generation time',
        'warning', 'Synthetic demo aggregates only. Do not report as actual airline performance.'
    )
FROM `tmp_aeroinsight_synthetic_2026` AS `generated`
LEFT JOIN `historical_interval_metrics` AS `existing`
    ON `existing`.`tenant_id` = @tenant_id
   AND `existing`.`ingestion_batch_id` = @ingestion_batch_id
   AND `existing`.`source_row_number` = `generated`.`source_row_number`
WHERE `existing`.`historical_interval_metric_id` IS NULL;

-- 7. Mark the batch loaded only after all metric rows have been inserted.
UPDATE `ingestion_batches`
SET
    `batch_status` = 'loaded',
    `records_received` = @expected_rows,
    `records_accepted` = (
        SELECT COUNT(*)
        FROM `historical_interval_metrics`
        WHERE `tenant_id` = @tenant_id
          AND `ingestion_batch_id` = @ingestion_batch_id
    ),
    `records_rejected` = 0,
    `validation_summary_json` = JSON_OBJECT(
        'dataset_type', 'synthetic_demo',
        'production_eligible', FALSE,
        'date_start_utc', '2026-01-01 00:00:00',
        'date_end_utc', '2026-10-31 23:45:00',
        'interval_seconds', 900,
        'generated_rows', @expected_rows,
        'accepted_rows_for_batch', (
            SELECT COUNT(*)
            FROM `historical_interval_metrics`
            WHERE `tenant_id` = @tenant_id
              AND `ingestion_batch_id` = @ingestion_batch_id
        ),
        'note', 'Synthetic demo data; not actual airline operational data.'
    ),
    `completed_at_utc` = COALESCE(`completed_at_utc`, UTC_TIMESTAMP(6))
WHERE `tenant_id` = @tenant_id
  AND `source_system_id` = @source_system_id
  AND `ingestion_batch_id` = @ingestion_batch_id;

-- Record one audit event for this batch; do not duplicate it on rerun.
INSERT INTO `audit_events`
    (`tenant_id`, `actor_membership_id`, `action_code`, `target_type`,
     `target_reference`, `outcome_code`, `event_details_json`)
SELECT
    @tenant_id,
    NULL,
    'historical_metrics.synthetic_demo_loaded',
    'ingestion_batch',
    CAST(@ingestion_batch_id AS CHAR),
    'success',
    JSON_OBJECT(
        'dataset_type', 'synthetic_demo',
        'production_eligible', FALSE,
        'records_expected', @expected_rows,
        'records_loaded', (
            SELECT COUNT(*)
            FROM `historical_interval_metrics`
            WHERE `tenant_id` = @tenant_id
              AND `ingestion_batch_id` = @ingestion_batch_id
        )
    )
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1
    FROM `audit_events`
    WHERE `tenant_id` = @tenant_id
      AND `action_code` = 'historical_metrics.synthetic_demo_loaded'
      AND `target_type` = 'ingestion_batch'
      AND `target_reference` = CAST(@ingestion_batch_id AS CHAR)
);

COMMIT;

-- 8. Final verification output.
SELECT
    b.`ingestion_batch_id`,
    s.`source_code`,
    b.`batch_status`,
    b.`records_received`,
    b.`records_accepted`,
    b.`records_rejected`,
    b.`received_at_utc`,
    b.`completed_at_utc`
FROM `ingestion_batches` AS b
JOIN `source_systems` AS s
  ON s.`tenant_id` = b.`tenant_id`
 AND s.`source_system_id` = b.`source_system_id`
WHERE b.`tenant_id` = @tenant_id
  AND b.`ingestion_batch_id` = @ingestion_batch_id;

SELECT
    COUNT(*) AS total_rows,
    MIN(`interval_start_utc`) AS first_interval_utc,
    MAX(`interval_start_utc`) AS last_interval_utc,
    COUNT(DISTINCT `market_code`) AS markets,
    COUNT(DISTINCT `channel_code`) AS channels,
    COUNT(DISTINCT `service_language_code`) AS languages,
    SUM(`offered_contacts`) AS offered_contacts,
    SUM(`answered_contacts`) AS answered_contacts,
    SUM(`handled_contacts`) AS handled_contacts,
    SUM(`abandoned_contacts`) AS abandoned_contacts,
    COUNT(DISTINCT `quality_status`) AS quality_status_count
FROM `historical_interval_metrics`
WHERE `tenant_id` = @tenant_id
  AND `ingestion_batch_id` = @ingestion_batch_id;

SELECT
    `market_code`,
    `channel_code`,
    `service_language_code`,
    COUNT(*) AS interval_rows,
    SUM(`offered_contacts`) AS offered_contacts,
    SUM(`answered_contacts`) AS answered_contacts,
    SUM(`abandoned_contacts`) AS abandoned_contacts,
    ROUND(
        100.0 * SUM(`answered_within_threshold_contacts`)
        / NULLIF(SUM(`sla_eligible_contacts`), 0),
        2
    ) AS synthetic_sla_percent,
    ROUND(
        SUM(`total_handle_seconds`) / NULLIF(SUM(`handled_contacts`), 0),
        2
    ) AS synthetic_aht_seconds,
    ROUND(
        SUM(`total_answer_wait_seconds`) / NULLIF(SUM(`answered_contacts`), 0),
        2
    ) AS synthetic_asa_seconds,
    'SYNTHETIC DEMO - NOT REAL OPERATIONS' AS data_notice
FROM `historical_interval_metrics`
WHERE `tenant_id` = @tenant_id
  AND `ingestion_batch_id` = @ingestion_batch_id
GROUP BY `market_code`, `channel_code`, `service_language_code`
ORDER BY `market_code`, `channel_code`, `service_language_code`;

DROP TEMPORARY TABLE IF EXISTS `tmp_aeroinsight_synthetic_2026`;

-- End. Expected 233,472 rows. All imported rows have quality_status='warning'.
