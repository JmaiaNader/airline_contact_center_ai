-- Migration 004 postflight. READ ONLY. Target: db_airlines.
USE `db_airlines`;

-- Expected: 2 new tables.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN ('semantic_concepts','tenant_source_field_mappings')
ORDER BY TABLE_NAME;

-- Expected: 9 version-1 canonical concepts.
SELECT COUNT(*) AS active_concept_versions
FROM semantic_concepts
WHERE concept_status = 'active' AND concept_version = 1;

-- Expected: one development source for demo_airline (unless it already existed).
SELECT t.tenant_code, s.source_code, s.display_name, s.source_type, s.source_status
FROM source_systems s
JOIN tenants t ON t.tenant_id = s.tenant_id
WHERE t.tenant_code = 'demo_airline'
  AND s.source_code = 'db_airlines_metadata';

-- Expected: zero field mappings before the first authenticated review session.
SELECT COUNT(*) AS persisted_field_mappings
FROM tenant_source_field_mappings;

-- Verify tenant/source and membership foreign-key boundaries.
SELECT
    kcu.TABLE_NAME,
    kcu.CONSTRAINT_NAME,
    GROUP_CONCAT(kcu.COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION) AS child_columns,
    kcu.REFERENCED_TABLE_NAME,
    GROUP_CONCAT(kcu.REFERENCED_COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION) AS parent_columns,
    COUNT(*) AS column_pairs
FROM information_schema.KEY_COLUMN_USAGE kcu
WHERE kcu.CONSTRAINT_SCHEMA = 'db_airlines'
  AND kcu.TABLE_NAME = 'tenant_source_field_mappings'
  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
GROUP BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.REFERENCED_TABLE_NAME
ORDER BY kcu.CONSTRAINT_NAME;

-- Verify audit and mapping permissions exist.
SELECT permission_code
FROM permissions
WHERE permission_code IN ('mapping.view','mapping.review','mapping.approve')
ORDER BY permission_code;
