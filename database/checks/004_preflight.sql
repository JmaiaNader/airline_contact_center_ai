-- Migration 004 preflight. READ ONLY. Target: db_airlines.
USE `db_airlines`;
SELECT DATABASE() AS target_schema;

-- Required prior migrations and tables.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN (
    'tenants','source_systems','tenant_memberships','permissions','audit_events'
  )
ORDER BY TABLE_NAME;

-- New Migration 004 tables should not already exist on first application.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN ('semantic_concepts','tenant_source_field_mappings')
ORDER BY TABLE_NAME;

-- Current tenant and source registry.
SELECT t.tenant_id, t.tenant_code, t.tenant_status,
       COUNT(s.source_system_id) AS source_system_count
FROM tenants t
LEFT JOIN source_systems s ON s.tenant_id = t.tenant_id
GROUP BY t.tenant_id, t.tenant_code, t.tenant_status
ORDER BY t.tenant_id;

-- Mapping permissions should be in the shared permission catalog.
SELECT permission_code
FROM permissions
WHERE permission_code IN ('mapping.view','mapping.review','mapping.approve')
ORDER BY permission_code;
