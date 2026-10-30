-- Migration 003 preflight. Read-only. Target: db_airlines.
USE `db_airlines`;
SELECT DATABASE() AS target_schema;

-- Migration 002 prerequisites must exist.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN (
      'tenants', 'source_systems', 'ingestion_batches', 'historical_interval_metrics'
  )
ORDER BY TABLE_NAME;

-- Migration 003 objects should not already exist for a first application.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN (
      'users', 'user_identities', 'tenant_memberships', 'permissions', 'roles',
      'membership_roles', 'role_permissions', 'tenant_invitations', 'audit_events'
  )
ORDER BY TABLE_NAME;

-- At least one tenant must exist. The current development tenant should be present.
SELECT tenant_id, tenant_code, display_name, tenant_status
FROM tenants
ORDER BY tenant_id;
