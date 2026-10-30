-- Migration 003 postflight checks. Read-only. Target: db_airlines.
USE `db_airlines`;

-- Expected: 9 tables listed.
SELECT TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'db_airlines'
  AND TABLE_NAME IN (
      'users', 'user_identities', 'tenant_memberships', 'permissions', 'roles',
      'membership_roles', 'role_permissions', 'tenant_invitations', 'audit_events'
  )
ORDER BY TABLE_NAME;

-- Summary: expected users=0, identities=0, memberships=0, roles=6 for demo tenant,
-- permissions=26, role_permissions > 0, invitations=0, audit_events=0.
SELECT 'users' AS object_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'user_identities', COUNT(*) FROM user_identities
UNION ALL SELECT 'tenant_memberships', COUNT(*) FROM tenant_memberships
UNION ALL SELECT 'permissions', COUNT(*) FROM permissions
UNION ALL SELECT 'roles_demo_airline', COUNT(*) FROM roles r
    JOIN tenants t ON t.tenant_id = r.tenant_id WHERE t.tenant_code = 'demo_airline'
UNION ALL SELECT 'role_permissions', COUNT(*) FROM role_permissions
UNION ALL SELECT 'tenant_invitations', COUNT(*) FROM tenant_invitations
UNION ALL SELECT 'audit_events', COUNT(*) FROM audit_events;

-- Verify tenant scoping of role assignments and role-permission grants.
SELECT
    tc.TABLE_NAME,
    tc.CONSTRAINT_NAME,
    GROUP_CONCAT(kcu.COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION) AS child_columns,
    kcu.REFERENCED_TABLE_NAME,
    GROUP_CONCAT(kcu.REFERENCED_COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION) AS parent_columns,
    COUNT(*) AS column_pairs
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.KEY_COLUMN_USAGE kcu
  ON kcu.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
 AND kcu.TABLE_NAME = tc.TABLE_NAME
 AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
WHERE tc.CONSTRAINT_SCHEMA = 'db_airlines'
  AND tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
  AND tc.TABLE_NAME IN ('membership_roles', 'role_permissions', 'tenant_invitations', 'audit_events')
GROUP BY tc.TABLE_NAME, tc.CONSTRAINT_NAME, kcu.REFERENCED_TABLE_NAME
ORDER BY tc.TABLE_NAME, tc.CONSTRAINT_NAME;

-- List seeded roles and permission counts for each role in demo_airline.
SELECT
    r.role_code,
    r.role_name,
    COUNT(rp.permission_code) AS permission_count
FROM roles r
JOIN tenants t ON t.tenant_id = r.tenant_id
LEFT JOIN role_permissions rp
  ON rp.tenant_id = r.tenant_id AND rp.role_id = r.role_id
WHERE t.tenant_code = 'demo_airline'
GROUP BY r.role_id, r.role_code, r.role_name
ORDER BY r.role_code;
