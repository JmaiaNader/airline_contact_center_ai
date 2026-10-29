-- Seed 001: Initial reference data only (safe to rerun; existing rows are preserved).
-- Run only after 001_create_core_schema.sql succeeds.
-- Target database: db_airlines. No production SLA values, services, or queue names are invented.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';
USE `db_airlines`;

-- Markets are operational/reporting markets, not passenger nationality or sales/POS market.
INSERT INTO `markets` (`market_code`, `market_name`, `country_code`, `reporting_timezone`)
SELECT 'QATAR', 'Qatar', 'QA', 'Asia/Qatar'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `markets` WHERE `market_code` = 'QATAR');

-- USA intentionally has NULL reporting_timezone because the country spans multiple time zones.
-- Agree on the operation's reporting timezone or use site/queue-specific time zones before using it.
INSERT INTO `markets` (`market_code`, `market_name`, `country_code`, `reporting_timezone`)
SELECT 'USA', 'United States', 'US', NULL
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `markets` WHERE `market_code` = 'USA');

INSERT INTO `markets` (`market_code`, `market_name`, `country_code`, `reporting_timezone`)
SELECT 'UAE', 'United Arab Emirates', 'AE', 'Asia/Dubai'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `markets` WHERE `market_code` = 'UAE');

INSERT INTO `languages` (`language_code`, `display_name`)
SELECT 'en', 'English' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `languages` WHERE `language_code` = 'en');

INSERT INTO `languages` (`language_code`, `display_name`)
SELECT 'ar', 'Arabic' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `languages` WHERE `language_code` = 'ar');

INSERT INTO `languages` (`language_code`, `display_name`)
SELECT 'fr', 'French' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `languages` WHERE `language_code` = 'fr');

INSERT INTO `languages` (`language_code`, `display_name`)
SELECT 'und', 'Undetermined' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `languages` WHERE `language_code` = 'und');

-- These synchronous/asynchronous markers are initial operating assumptions only.
-- Confirm them for your actual channel implementation. SLA measurement is governed by sla_rules.
INSERT INTO `channels` (`channel_code`, `display_name`, `is_synchronous`)
SELECT 'voice', 'Voice', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `channels` WHERE `channel_code` = 'voice');

INSERT INTO `channels` (`channel_code`, `display_name`, `is_synchronous`)
SELECT 'webchat', 'Webchat', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `channels` WHERE `channel_code` = 'webchat');

INSERT INTO `channels` (`channel_code`, `display_name`, `is_synchronous`)
SELECT 'whatsapp', 'WhatsApp', 0 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `channels` WHERE `channel_code` = 'whatsapp');

INSERT INTO `channels` (`channel_code`, `display_name`, `is_synchronous`)
SELECT 'email', 'Email', 0 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `channels` WHERE `channel_code` = 'email');

INSERT INTO `channels` (`channel_code`, `display_name`, `is_synchronous`)
SELECT 'social_media', 'Social Media', 0 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM `channels` WHERE `channel_code` = 'social_media');

-- Deliberately not seeded:
-- * services: agree canonical service codes with the real operation first.
-- * queues: need approved queue codes/names, channel, and service mappings.
-- * sla_rules: do not invent service-level targets, response thresholds, or short-abandon policy.
