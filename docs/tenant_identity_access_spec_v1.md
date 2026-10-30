# Tenant Identity & Access Control Specification v1

**Project:** `airline_contact_center_ai`  
**Product direction:** AeroInsight — Evidence & Decision Engine  
**Stage:** 003-A — Design specification only  
**Status:** Proposed for review; **not executable SQL**  
**Database:** `db_airlines` (MySQL, InnoDB, `utf8mb4`)

> This document defines the identity, membership, and authorization design that must be agreed before preparing Migration 003. It does not create tables, users, passwords, sessions, or permissions. Do not execute SQL based on this document.

## 1. Purpose

AeroInsight is one shared application that can serve multiple companies and many users. A person may belong to more than one company and may have a different role in each company. The application must enforce company boundaries consistently across the UI, Python services, database repositories, LangGraph tools, and retrieval systems.

Migration 002 established a tenant registry and tenant-scoped relationships for company-owned operational data. It did not create authentication or authorization. This specification defines the next layer.

## 2. Design principles

1. **One global user identity, many tenant memberships.** A user account is not duplicated for every company.
2. **Membership is the boundary.** A user receives access to a tenant only through an active membership in that tenant.
3. **Roles are tenant-scoped.** The same person can be a Company Admin in Tenant A and a Viewer in Tenant B.
4. **Permissions are explicit and default-deny.** No permission is granted merely because a user is authenticated or because an LLM selected a tool.
5. **Tenant context is server-derived.** The browser, Streamlit widget, URL, prompt, or LLM must not be trusted to assert a tenant ID or permissions.
6. **Authorization occurs at the service/repository boundary.** UI hiding is not a security control.
7. **Provider portability.** Authentication is behind an application interface. The final identity provider is not selected by this document.
8. **Auditable administration.** Membership, role, invitation, and security-sensitive changes produce audit events.
9. **Migrations remain manual.** Only a developer/DBA applies reviewed DDL. No agent or runtime tool may execute DDL.

## 3. Terminology

- **User:** A global person/account in the AeroInsight identity directory.
- **Tenant:** A company/customer represented by `tenants` from Migration 002.
- **Membership:** The relationship between one user and one tenant, including its status.
- **Role:** A tenant-specific named bundle of permissions.
- **Permission:** A stable application capability code, enforced by Python services.
- **Active tenant context:** A server-validated selection of one tenant for the current request.
- **Platform operator:** An internal service operator, distinct from a tenant administrator. Platform operator access is outside ordinary tenant roles and must not be granted by tenant admins.

## 4. Proposed data model for Migration 003

Migration 003 should create the following tables. Exact column types, indexes, constraints, FK names, and DDL order must be finalized in the migration review and tests before execution.

### 4.1 `users` — global user directory

Purpose: one account per person across the platform.

Proposed attributes:
- `user_id` — `BIGINT UNSIGNED` primary key.
- `email_normalized` — normalized email used for account matching and invitations; unique according to the selected identity policy.
- `email_display` — optional display-preserving email value.
- `display_name` — user-facing name.
- `user_status` — controlled status such as `active` or `disabled`.
- `created_at_utc`, `updated_at_utc` — UTC audit timestamps.

Rules:
- Email is an identity/contact attribute, not proof of authentication by itself.
- Do not merge two accounts solely because an unverified identity provider claims the same email.
- Do not store plaintext passwords, API keys, access tokens, or refresh tokens in this table.
- Account disablement must block new authenticated requests and invalidate/reject active application sessions on the next authorization check.

### 4.2 `user_identities` — authentication-provider identities

Purpose: map one AeroInsight user to one or more verified external authentication identities without tying the application to one vendor.

Proposed attributes:
- `user_identity_id` — primary key.
- `user_id` — FK to `users`.
- `provider_code` — controlled provider identifier, e.g. `oidc`.
- `issuer` — validated identity-provider issuer.
- `subject` — immutable subject identifier from the provider.
- `created_at_utc`, `last_authenticated_at_utc`.

Constraints and rules:
- Enforce uniqueness on `(issuer, subject)`; a provider subject must map to only one platform user.
- Validate issuer, signature, audience, expiry, nonce/state, and relevant token claims in the authentication adapter. Database rows do not make an unverified token trustworthy.
- Email-based account linking requires a verified identity and an explicit safe linking flow.
- The first production authentication mechanism should be an OIDC-compatible provider; vendor selection and deployment configuration remain a separate decision.
- A local development/test identity adapter may be used only with synthetic accounts and must be disabled in production.

### 4.3 `tenant_memberships` — user access to companies

Purpose: represent whether a global user belongs to a specific tenant.

Proposed attributes:
- `membership_id` — primary key.
- `tenant_id` — FK to `tenants`.
- `user_id` — FK to `users`.
- `membership_status` — `invited`, `active`, `suspended`, or `revoked`.
- `joined_at_utc`, `created_at_utc`, `updated_at_utc`.

Constraints and rules:
- Unique `(tenant_id, user_id)` so a user has one membership per tenant.
- Provide a candidate unique key `(tenant_id, membership_id)` for tenant-safe composite references from role assignments and invitations.
- A user may have multiple active memberships across different tenants.
- A suspended/revoked membership grants no tenant access, even if a session still contains that tenant ID.

### 4.4 `roles` — tenant-specific role definitions

Purpose: define reusable job/administrative roles independently for each company.

Proposed attributes:
- `role_id` — primary key.
- `tenant_id` — FK to `tenants`.
- `role_code` — stable code, unique within a tenant.
- `display_name`, `description`.
- `is_system_role` — identifies a platform-provided role template instantiated for the tenant.
- `is_active`, timestamps.

Rules:
- Enforce unique `(tenant_id, role_code)` and a composite candidate key `(tenant_id, role_id)`.
- Roles are tenant-scoped so each company can customize role names and grants without affecting another company.
- A tenant administrator may manage tenant roles only when granted the relevant permission; they cannot create platform-operator roles or grant platform-level privileges.
- System role templates are instantiated for each new tenant by a controlled tenant-provisioning service. Migration 003 seeds them for existing tenants.

### 4.5 `permissions` — platform permission catalog

Purpose: define the capabilities that application code understands.

Proposed attributes:
- `permission_id` — primary key.
- `permission_code` — globally unique stable string.
- `area`, `description`, `risk_level`, `is_active`.

Rules:
- Permission codes are controlled by application releases/migrations, not arbitrary free-text values created by tenant admins.
- Application services must check permission codes, not role names or UI labels.
- Unknown or inactive permission codes fail closed.

### 4.6 `membership_roles` — roles assigned to a membership

Purpose: assign one or more roles to a user within one tenant.

Proposed attributes:
- `tenant_id`, `membership_id`, `role_id`, `assigned_at_utc`, `assigned_by_membership_id` (nullable for controlled provisioning/system operations).

Constraints and rules:
- Unique `(tenant_id, membership_id, role_id)`.
- Composite FK `(tenant_id, membership_id)` to `tenant_memberships`.
- Composite FK `(tenant_id, role_id)` to `roles`.
- The composite FKs prevent accidentally assigning a role from Tenant B to a membership in Tenant A.
- Role assignment is rejected unless the membership and role are active.

### 4.7 `role_permissions` — permissions granted by roles

Purpose: map tenant-specific roles to capabilities from the global permission catalog.

Proposed attributes:
- `tenant_id`, `role_id`, `permission_id`, `granted_at_utc`, `granted_by_membership_id`.

Constraints and rules:
- Unique `(tenant_id, role_id, permission_id)`.
- Composite FK `(tenant_id, role_id)` to `roles`.
- FK `permission_id` to `permissions`.
- Tenant administrators may grant only permissions that policy allows them to delegate; they cannot grant permissions outside their own administrative ceiling.

### 4.8 `tenant_invitations` — controlled onboarding

Purpose: let an authorized tenant administrator invite a person to one tenant.

Proposed attributes:
- `invitation_id` — primary key.
- `tenant_id`, `invited_email_normalized`, `role_id`.
- `token_hash` — hash of a high-entropy, single-use invitation token; never store the raw token.
- `invitation_status` — `pending`, `accepted`, `expired`, or `revoked`.
- `expires_at_utc`, `accepted_at_utc`, `created_at_utc`.
- `invited_by_membership_id` — tenant-safe FK to the inviter's membership.

Rules:
- A token is single-use, expires, and is stored only as a cryptographic hash.
- The invitation is bound to one tenant and one normalized email; acceptance must verify both.
- Invitation acceptance creates or resolves a global user, creates/activates the tenant membership, and assigns only the invited tenant role.
- Resending, revoking, and accepting invitations must be auditable.
- Email delivery is an adapter/integration concern; no email provider is selected here.

### 4.9 `audit_events` — security and administration trail

Purpose: record security-sensitive actions and administrative changes.

Proposed attributes:
- `audit_event_id` — primary key.
- `tenant_id` — nullable only for platform-level events; tenant events must include it.
- `actor_user_id` — nullable for controlled system events.
- `action_code`, `resource_type`, `resource_id`, `outcome`.
- `request_id`, `occurred_at_utc`, `metadata_json` (redacted, bounded metadata only).

Rules:
- Record sign-in outcomes, invitation lifecycle, membership status changes, role grants/revocations, permission changes, tenant-context denials, and privileged operations.
- Do not log passwords, tokens, API keys, complete prompts, full passenger data, or unnecessary personal data.
- Application access should be append-only: runtime code may insert and authorized auditors may read; normal application paths must not update/delete events.
- Define a retention policy before production rollout.

## 5. Initial role templates

The following are templates, not hard-coded authorization checks. Their permissions are stored in `role_permissions`, and every tenant gets its own role rows.

| Role code | Intended use | Initial access boundary |
|---|---|---|
| `tenant_admin` | Company administrator | Manage users, invitations, tenant roles, tenant settings, and approved company sources; no platform-operator access |
| `contact_center_manager` | Contact-center leadership | Read operational KPIs, CSAT, quality, forecasts, WFM/RTM views; approve only explicitly delegated actions |
| `wfm_planner` | Workforce planning | Read demand/staffing forecasts and manage approved schedules/planning data |
| `data_analyst` | Data and reporting analyst | Inspect approved sources/mappings and read authorized analytics; mapping approval can be separately granted |
| `agent` | Contact-center agent | Only explicitly assigned agent-facing functions and permitted own/team data |
| `viewer` | Read-only stakeholder | Read explicitly permitted dashboards/reports; no data-source, role, or operational writes |

No role should receive all permissions by default. `tenant_admin` is not equivalent to an internal platform administrator.

## 6. Initial permission catalog proposal

Use stable permission codes. Exact additions should be reviewed alongside each feature implementation.

| Permission code | Capability |
|---|---|
| `tenant.profile.read` | Read own tenant profile |
| `tenant.profile.manage` | Update permitted tenant settings |
| `tenant.members.read` | View tenant memberships |
| `tenant.members.invite` | Invite users to own tenant |
| `tenant.members.manage` | Suspend/revoke memberships within own tenant |
| `tenant.roles.read` | View tenant roles |
| `tenant.roles.manage` | Create/update tenant roles and assignments within delegation limits |
| `sources.read` | View approved data-source registrations |
| `sources.manage` | Register/disable tenant data sources |
| `mappings.read` | View semantic mappings |
| `mappings.review` | Review suggested mappings |
| `mappings.approve` | Approve/reject mappings when authorized |
| `analytics.kpi.read` | Read approved KPI results |
| `forecast.read` | Read forecast and staffing results |
| `forecast.manage` | Manage approved forecast configuration/jobs |
| `wfm.schedule.read` | Read schedules and staffing plans |
| `wfm.schedule.manage` | Manage permitted schedules/planning inputs |
| `rtm.recommendation.read` | Read RTM alerts/recommendations |
| `rtm.recommendation.approve` | Approve governed RTM recommendations |
| `rtm.action.execute` | Execute a separately approved, allow-listed operational action |
| `policies.read` | Read approved tenant policy content |
| `policies.manage` | Manage tenant policy documents/versions |
| `audit.read` | Read tenant audit events where permitted |

High-risk capabilities such as `rtm.action.execute`, source configuration, role delegation, and mapping approval should require specific grants and may require additional approval/step-up controls. Permission to view a recommendation is not permission to execute it.

## 7. Authenticated tenant context

The backend must construct a typed context after successful authentication and membership validation. A conceptual context contains:

- `user_id`
- `tenant_id`
- `membership_id`
- active role IDs / permission codes (loaded or safely cached with invalidation rules)
- authentication/session identifier
- request/correlation ID

Rules:
1. The context is created by trusted authentication and authorization code, never from an LLM response or raw UI input.
2. Tenant selection in the UI is only a request to switch context. The server must verify an active membership for that user and tenant on every context switch.
3. Missing, disabled, suspended, expired, or revoked identity/membership/tenant states fail closed.
4. Every company-scoped repository method requires a validated context or an explicit internal system context. There is no implicit default tenant.
5. Every query filters by the context's `tenant_id`; every write sets it from context rather than accepting it from user-controlled payloads.
6. Updates/deletes must include tenant scope in the predicate and verify affected-row counts.
7. Composite foreign keys from Migration 002 remain a second line of defense against cross-tenant relationships; they do not replace authorization.

## 8. Enforcement across the application

### Streamlit UI

- Authentication state may be displayed in `st.session_state`, but session state is not the source of truth for permissions.
- Revalidate the active user and membership before protected page actions and service calls.
- Hide unavailable actions for usability, but enforce every permission again in the backend.
- Tenant switcher lists only tenants with active memberships.

### Python services and repositories

- Add a central authorization service (proposed module: `src/security/authorization.py`) and typed principal/context model (proposed module: `src/security/context.py`). Confirm existing project conventions before creating these paths.
- Repository APIs take a validated tenant context; do not expose unscoped company-data query helpers to normal application code.
- Use parameterized SQL and tenant predicates. Never concatenate tenant IDs or filters into SQL strings.
- Fail closed if context is absent or permission is missing.

### LangGraph and tools

- LangGraph may route a request to an allow-listed tool, but the tool wrapper independently checks the authenticated context and required permission.
- LLM prompts and graph state are not authorization sources. The LLM cannot assign `user_id`, `tenant_id`, roles, or permission codes.
- No LLM-exposed tool may change schema, run arbitrary SQL, grant permissions, or perform unapproved operational writes.

### RAG and vector retrieval

- Every tenant document/chunk must carry tenant ownership and source/document permission metadata.
- Retrieval filters by the authenticated tenant before ranking/returning chunks; post-filtering after retrieving cross-tenant content is insufficient.
- Shared platform documents must be explicitly marked as shared and separately governed; never treat missing tenant metadata as public.
- Citations must preserve document ID, version, approval status, language, and page/section metadata.

### Audit

- Record the actor, tenant, action, target resource, outcome, timestamp, and request ID for security-sensitive changes.
- Redact secrets and minimize customer/passenger data in logs.

## 9. Tenant lifecycle and provisioning

A controlled tenant-provisioning service should:
1. Create the tenant record.
2. Create tenant-specific system role rows from approved templates.
3. Apply the approved default permission matrix.
4. Create the initial administrator invitation or membership through a controlled process.
5. Write an audit event for provisioning.

Provisioning must be transactional where possible and safely resumable. It must not create a tenant with no authorized owner. Migration 003 should seed role templates for tenants already present (currently the development tenant `demo_airline`); future tenants must use the provisioning service, not manual ad-hoc SQL.

## 10. Migration 003 scope and dependency order

Migration 003 should be designed to create the identity/access tables and seed the permission catalog plus tenant-specific role templates for existing tenants. Suggested dependency order:

1. `users`
2. `user_identities`
3. `permissions`
4. `tenant_memberships`
5. `roles`
6. `role_permissions`
7. `membership_roles`
8. `tenant_invitations`
9. `audit_events`

The exact order may change to satisfy foreign-key dependencies (for example, invitation inviter references and membership role references). Every tenant-scoped relationship should use composite keys that include `tenant_id` where that relationship crosses tenant-owned entities.

Before SQL is generated, decide:
- Which authentication provider/adapter is used for the first deployable version (OIDC provider vs. a deliberately limited local-development adapter).
- Email normalization and account-linking policy.
- Whether invitation acceptance initially assigns exactly one role or supports multiple roles.
- The initial permission-to-role matrix and which permissions are delegable by a tenant admin.
- Audit-event retention and access policy.

Do not add password storage casually. If local passwords are explicitly selected, use a dedicated credential design and a vetted password-hashing library; never store plaintext or reversible passwords. Keep that decision separate from the global user/membership model.

## 11. Required security and correctness tests

Migration 003 and its application services are not done until tests cover:

1. One user can belong to two tenants with different roles.
2. A user with no membership cannot select or query a tenant.
3. A suspended/revoked membership is denied even if a stale UI session contains the tenant ID.
4. A suspended/closed tenant is denied according to tenant status policy.
5. A role from Tenant B cannot be assigned to a membership in Tenant A (composite FK negative test).
6. A tenant admin cannot read or manage another tenant's users, roles, sources, mappings, policies, or audit events.
7. A user cannot grant a permission they are not allowed to delegate.
8. A viewer cannot execute a write or RTM action.
9. LLM/tool input attempting to override `tenant_id`, user identity, or permissions is ignored/rejected.
10. Repository reads, updates, and deletes are tenant-scoped; cross-tenant IDs return no data and do not mutate another tenant's rows.
11. RAG retrieval never returns another tenant's chunks, including when metadata is missing or malformed.
12. Invitation tokens are single-use, expire, are stored hashed, and are bound to tenant and invited email.
13. Audit records contain required provenance while excluding tokens, passwords, and unnecessary PII.
14. Disabled global users cannot access any tenant.

## 12. Definition of done for Stage 003-A

- This specification is reviewed and approved.
- The first authentication approach and account-linking policy are decided.
- The permission catalog and default role matrix are approved.
- Tenant context and enforcement boundaries are accepted.
- Migration 003 SQL has not yet been generated or executed.

Only after Stage 003-A is approved should Stage 003-B produce the SQL migration, preflight/postflight checks, static tests, and a clean-test-database execution plan.

## 13. Explicit non-goals for this stage

- No executable SQL or database changes.
- No UI login implementation.
- No password reset/email delivery integration.
- No SSO vendor selection or production credentials.
- No platform-operator console.
- No tenant-specific custom permissions (permission codes remain platform-controlled).
- No changes to Migration 001 or Migration 002.
- No LLM-based authorization.
