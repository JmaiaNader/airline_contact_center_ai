-- AeroInsight / airline_contact_center_ai
-- Migration 003: tenant-scoped identity, memberships, roles and permissions
-- TARGET: db_airlines
-- Additive migration: creates new tables only; does not alter Migration 001/002 tables.
-- Authentication is expected to be delegated to an OIDC-compatible identity provider.
-- Do not store passwords, access tokens, refresh tokens, ID tokens, API keys or secrets here.
-- Run once with a developer/DBA account. MySQL DDL implicitly commits.

USE `db_airlines`;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

-- Guardrails / execution context. Expected schema is the one produced by Migration 002.
SELECT DATABASE() AS migration_003_target_schema;

-- 1. One global user identity can be a member of multiple tenants.
CREATE TABLE IF NOT EXISTS `users` (
    `user_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `email_normalized` VARCHAR(254) NOT NULL,
    `display_name` VARCHAR(128) NOT NULL,
    `user_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'pending',
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`user_id`),
    UNIQUE KEY `uq003_users_email_normalized` (`email_normalized`),
    KEY `ix003_users_status` (`user_status`),
    CONSTRAINT `chk003_users_status`
        CHECK (`user_status` IN ('pending', 'active', 'suspended', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. External login identities. The external provider remains responsible for secrets/MFA.
CREATE TABLE IF NOT EXISTS `user_identities` (
    `user_identity_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `identity_provider_code` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `issuer_url` VARCHAR(512) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `subject_id` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    `provider_email_normalized` VARCHAR(254) NULL,
    `email_verified` TINYINT(1) NOT NULL DEFAULT 0,
    `linked_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `last_authenticated_at_utc` DATETIME(6) NULL,
    PRIMARY KEY (`user_identity_id`),
    UNIQUE KEY `uq003_identity_issuer_subject` (`issuer_url`, `subject_id`),
    KEY `ix003_identity_user` (`user_id`),
    CONSTRAINT `fk003_identity_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk003_identity_email_verified`
        CHECK (`email_verified` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Membership belongs to a tenant. The same user may have memberships in many tenants.
CREATE TABLE IF NOT EXISTS `tenant_memberships` (
    `membership_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `membership_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'pending',
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `activated_at_utc` DATETIME(6) NULL,
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`membership_id`),
    UNIQUE KEY `uq003_membership_tenant_user` (`tenant_id`, `user_id`),
    UNIQUE KEY `uq003_membership_tenant_membership` (`tenant_id`, `membership_id`),
    KEY `ix003_membership_user_status` (`user_id`, `membership_status`),
    CONSTRAINT `fk003_membership_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_membership_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk003_membership_status`
        CHECK (`membership_status` IN ('pending', 'active', 'suspended', 'removed'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Permission catalog is shared; role assignments are always tenant-scoped.
CREATE TABLE IF NOT EXISTS `permissions` (
    `permission_code` VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `permission_category` VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `description` VARCHAR(255) NOT NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`permission_code`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Roles are tenant-specific. Default roles are seeded below for current tenants.
CREATE TABLE IF NOT EXISTS `roles` (
    `role_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `role_code` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `role_name` VARCHAR(100) NOT NULL,
    `role_description` VARCHAR(255) NULL,
    `is_system_role` TINYINT(1) NOT NULL DEFAULT 1,
    `role_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`role_id`),
    UNIQUE KEY `uq003_roles_tenant_code` (`tenant_id`, `role_code`),
    UNIQUE KEY `uq003_roles_tenant_role` (`tenant_id`, `role_id`),
    CONSTRAINT `fk003_roles_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk003_roles_system` CHECK (`is_system_role` IN (0, 1)),
    CONSTRAINT `chk003_roles_status` CHECK (`role_status` IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. A membership can receive only roles belonging to that same tenant.
CREATE TABLE IF NOT EXISTS `membership_roles` (
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `membership_id` BIGINT UNSIGNED NOT NULL,
    `role_id` BIGINT UNSIGNED NOT NULL,
    `assigned_by_membership_id` BIGINT UNSIGNED NULL,
    `assigned_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`tenant_id`, `membership_id`, `role_id`),
    KEY `ix003_membership_roles_role` (`tenant_id`, `role_id`),
    CONSTRAINT `fk003_membership_roles_membership`
        FOREIGN KEY (`tenant_id`, `membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_membership_roles_role`
        FOREIGN KEY (`tenant_id`, `role_id`)
        REFERENCES `roles` (`tenant_id`, `role_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_membership_roles_assigner`
        FOREIGN KEY (`tenant_id`, `assigned_by_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. Role permissions. Permissions are global definitions; role grants are tenant-scoped.
CREATE TABLE IF NOT EXISTS `role_permissions` (
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `role_id` BIGINT UNSIGNED NOT NULL,
    `permission_code` VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `granted_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`tenant_id`, `role_id`, `permission_code`),
    KEY `ix003_role_permissions_permission` (`permission_code`),
    CONSTRAINT `fk003_role_permissions_role`
        FOREIGN KEY (`tenant_id`, `role_id`)
        REFERENCES `roles` (`tenant_id`, `role_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_role_permissions_permission`
        FOREIGN KEY (`permission_code`) REFERENCES `permissions` (`permission_code`)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. Invitation token hashes only; raw invitation tokens must never be stored.
CREATE TABLE IF NOT EXISTS `tenant_invitations` (
    `invitation_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `email_normalized` VARCHAR(254) NOT NULL,
    `invitation_token_sha256` BINARY(32) NOT NULL,
    `invitation_status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'pending',
    `invited_by_membership_id` BIGINT UNSIGNED NOT NULL,
    `accepted_by_user_id` BIGINT UNSIGNED NULL,
    `created_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `expires_at_utc` DATETIME(6) NOT NULL,
    `accepted_at_utc` DATETIME(6) NULL,
    PRIMARY KEY (`invitation_id`),
    UNIQUE KEY `uq003_invitation_token_hash` (`invitation_token_sha256`),
    KEY `ix003_invitation_tenant_email_status` (`tenant_id`, `email_normalized`, `invitation_status`),
    CONSTRAINT `fk003_invitation_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_invitation_inviter_membership`
        FOREIGN KEY (`tenant_id`, `invited_by_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_invitation_accepted_user`
        FOREIGN KEY (`accepted_by_user_id`) REFERENCES `users` (`user_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk003_invitation_status`
        CHECK (`invitation_status` IN ('pending', 'accepted', 'revoked', 'expired')),
    CONSTRAINT `chk003_invitation_expiry`
        CHECK (`expires_at_utc` > `created_at_utc`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. Tenant-scoped security/audit trail. Actor must be a membership in the same tenant.
CREATE TABLE IF NOT EXISTS `audit_events` (
    `audit_event_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `actor_membership_id` BIGINT UNSIGNED NULL,
    `action_code` VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `target_type` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    `target_reference` VARCHAR(128) NULL,
    `outcome_code` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `event_details_json` JSON NULL,
    `occurred_at_utc` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`audit_event_id`),
    KEY `ix003_audit_tenant_time` (`tenant_id`, `occurred_at_utc`),
    KEY `ix003_audit_tenant_actor_time` (`tenant_id`, `actor_membership_id`, `occurred_at_utc`),
    CONSTRAINT `fk003_audit_tenant`
        FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`tenant_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk003_audit_actor_membership`
        FOREIGN KEY (`tenant_id`, `actor_membership_id`)
        REFERENCES `tenant_memberships` (`tenant_id`, `membership_id`)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `chk003_audit_outcome`
        CHECK (`outcome_code` IN ('success', 'denied', 'failure'))
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 10. Seed the shared permission catalog. INSERT IGNORE makes this section rerunnable.
INSERT IGNORE INTO `permissions`
    (`permission_code`, `permission_category`, `description`)
VALUES
    ('tenant.view', 'tenant', 'View current tenant profile'),
    ('tenant.manage', 'tenant', 'Manage tenant settings'),
    ('membership.view', 'identity', 'View tenant memberships'),
    ('membership.invite', 'identity', 'Invite users to this tenant'),
    ('membership.manage', 'identity', 'Activate, suspend or remove memberships'),
    ('role.view', 'authorization', 'View tenant roles and role grants'),
    ('role.manage', 'authorization', 'Create roles and manage permission grants'),
    ('data_source.view', 'data', 'View configured data sources'),
    ('data_source.manage', 'data', 'Register and manage data sources'),
    ('mapping.view', 'data', 'View semantic field mappings'),
    ('mapping.review', 'data', 'Review suggested semantic mappings'),
    ('mapping.approve', 'data', 'Approve or reject semantic mappings'),
    ('data.view', 'analytics', 'View authorized company data'),
    ('data.export', 'analytics', 'Export authorized company data'),
    ('kpi.view', 'analytics', 'View KPI results and definitions'),
    ('kpi.manage', 'analytics', 'Manage tenant KPI configuration'),
    ('forecast.view', 'forecasting', 'View forecasts and staffing requirements'),
    ('forecast.manage', 'forecasting', 'Manage forecasting configuration'),
    ('wfm.view', 'wfm', 'View workforce management information'),
    ('wfm.manage', 'wfm', 'Manage workforce planning and schedules'),
    ('rtm.view', 'rtm', 'View real-time management information'),
    ('rtm.manage', 'rtm', 'Manage authorized RTM decisions'),
    ('policy.view', 'knowledge', 'Search authorized company policies'),
    ('policy.manage', 'knowledge', 'Manage policy documents and versions'),
    ('audit.view', 'security', 'View tenant security audit events'),
    ('agent_workspace.use', 'contact_center', 'Use the authorized agent workspace');

-- 11. Seed tenant-scoped default roles for every tenant currently registered.
INSERT IGNORE INTO `roles`
    (`tenant_id`, `role_code`, `role_name`, `role_description`, `is_system_role`)
SELECT t.`tenant_id`, seed.`role_code`, seed.`role_name`, seed.`role_description`, 1
FROM `tenants` t
CROSS JOIN (
    SELECT 'company_admin' AS role_code, 'Company Admin' AS role_name,
           'Manage tenant members, roles, data and configuration.' AS role_description
    UNION ALL SELECT 'manager', 'Manager',
           'View and supervise contact-center operations and reports.'
    UNION ALL SELECT 'analyst', 'Data Analyst',
           'Review data sources, semantic mappings and analytics.'
    UNION ALL SELECT 'wfm_planner', 'WFM Planner',
           'View forecasts and manage workforce planning.'
    UNION ALL SELECT 'agent', 'Contact Center Agent',
           'Use the authorized agent workspace and policy knowledge.'
    UNION ALL SELECT 'viewer', 'Viewer',
           'Read-only access to explicitly granted tenant information.'
) AS seed;

-- Company Admin receives all permission codes in the catalog.
INSERT IGNORE INTO `role_permissions` (`tenant_id`, `role_id`, `permission_code`)
SELECT r.`tenant_id`, r.`role_id`, p.`permission_code`
FROM `roles` r CROSS JOIN `permissions` p
WHERE r.`role_code` = 'company_admin';

-- Manager: operations visibility, but no identity/role administration or data-source writes.
INSERT IGNORE INTO `role_permissions` (`tenant_id`, `role_id`, `permission_code`)
SELECT r.`tenant_id`, r.`role_id`, p.`permission_code`
FROM `roles` r
JOIN `permissions` p ON p.`permission_code` IN (
    'tenant.view', 'membership.view', 'role.view', 'data_source.view',
    'mapping.view', 'data.view', 'kpi.view', 'forecast.view',
    'wfm.view', 'rtm.view', 'policy.view', 'audit.view'
)
WHERE r.`role_code` = 'manager';

-- Analyst: controlled data-source and semantic-mapping work; no membership administration.
INSERT IGNORE INTO `role_permissions` (`tenant_id`, `role_id`, `permission_code`)
SELECT r.`tenant_id`, r.`role_id`, p.`permission_code`
FROM `roles` r
JOIN `permissions` p ON p.`permission_code` IN (
    'data_source.view', 'data_source.manage', 'mapping.view',
    'mapping.review', 'mapping.approve', 'data.view', 'data.export',
    'kpi.view', 'forecast.view', 'policy.view'
)
WHERE r.`role_code` = 'analyst';

-- WFM Planner: workforce planning and forecast capabilities; RTM is view-only by default.
INSERT IGNORE INTO `role_permissions` (`tenant_id`, `role_id`, `permission_code`)
SELECT r.`tenant_id`, r.`role_id`, p.`permission_code`
FROM `roles` r
JOIN `permissions` p ON p.`permission_code` IN (
    'data.view', 'kpi.view', 'forecast.view', 'forecast.manage',
    'wfm.view', 'wfm.manage', 'rtm.view', 'policy.view'
)
WHERE r.`role_code` = 'wfm_planner';

-- Agent: least privilege; no broad analytics/export permissions by default.
INSERT IGNORE INTO `role_permissions` (`tenant_id`, `role_id`, `permission_code`)
SELECT r.`tenant_id`, r.`role_id`, p.`permission_code`
FROM `roles` r
JOIN `permissions` p ON p.`permission_code` IN (
    'policy.view', 'agent_workspace.use'
)
WHERE r.`role_code` = 'agent';

-- Viewer: read-only access to the normal operational reporting areas.
INSERT IGNORE INTO `role_permissions` (`tenant_id`, `role_id`, `permission_code`)
SELECT r.`tenant_id`, r.`role_id`, p.`permission_code`
FROM `roles` r
JOIN `permissions` p ON p.`permission_code` IN (
    'tenant.view', 'data.view', 'kpi.view', 'forecast.view',
    'wfm.view', 'rtm.view', 'policy.view'
)
WHERE r.`role_code` = 'viewer';

SELECT 'Migration 003 schema and default permission catalog statements completed.'
    AS migration_003_status;
