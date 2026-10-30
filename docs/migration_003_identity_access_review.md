# Migration 003 — Identity & Tenant Access Foundation

**Target schema:** `db_airlines`  
**Scope:** additive database schema for global user identities, tenant memberships, tenant-scoped roles, permission catalog, invitations and security audit events.

## Execution approach

This migration is intentionally targeted directly at the existing `db_airlines` database. It creates new tables only and does not alter the eight Migration 001 tables or the Migration 002 tables. It uses `CREATE TABLE IF NOT EXISTS` and `INSERT IGNORE` for table/seed idempotence, but the operator must still inspect any pre-existing Migration 003 objects before execution. `IF NOT EXISTS` does not repair an incompatible pre-existing table definition.

Run `database/checks/003_preflight.sql`, then execute `database/migrations/003_identity_access_control.sql` once using a developer/DBA account, then run `database/checks/003_postflight.sql`.

MySQL DDL implicitly commits. If an error occurs, stop and inspect the exact state; do not assume a rollback occurred or blindly rerun the file.

## Data model

- `users`: one global person/account record. Normalized email is unique across the platform, allowing the same user to join multiple tenants.
- `user_identities`: links a user to an external identity provider using `(issuer_url, subject_id)`. No provider secrets or tokens are stored.
- `tenant_memberships`: links users to tenants. A membership is unique per `(tenant_id, user_id)`.
- `permissions`: shared permission-code catalog.
- `roles`: tenant-scoped roles. Default roles are seeded for all tenants existing at migration time.
- `membership_roles`: composite foreign keys ensure a membership can only receive a role from the same tenant.
- `role_permissions`: maps tenant-scoped roles to shared permission codes.
- `tenant_invitations`: stores only SHA-256 token hashes, not raw invite tokens.
- `audit_events`: records tenant-scoped security/admin events; an actor membership, when supplied, must belong to that tenant.

## Default roles

- `company_admin`: all seeded permission codes.
- `manager`: operational/reporting visibility; no user/role administration.
- `analyst`: data sources, semantic mapping review/approval, analytics and export.
- `wfm_planner`: forecasting and WFM management; RTM view only by default.
- `agent`: policy view and agent workspace only.
- `viewer`: read-only operational reporting access.

These are initial permission templates, not a completed authorization implementation. Review the permissions before onboarding real users.

## Security boundaries and not-yet-implemented work

1. This migration does not implement authentication, login screens, password handling, MFA, sessions, or OIDC callback validation.
2. This migration does not implement Python repository authorization. Every tenant-owned query must later derive `tenant_id` from a verified authenticated membership context, never from an untrusted UI parameter alone.
3. The same isolation must apply to SQL tools, LangGraph tools, RAG retrieval, exports, cached results, and background jobs.
4. A role assignment is not proof of user authentication. External identity tokens must be validated by a proper OIDC implementation.
5. Do not store passwords, access tokens, refresh tokens, ID tokens, API keys, raw invitation tokens, or secrets in these tables or audit JSON.
6. Default roles are seeded for tenants existing at migration time. Tenant creation logic must create the same role templates for future tenants.
7. This migration is additive and does not grant any user membership. No user is automatically created or activated.

## Expected initial postflight

- 9 new tables exist.
- `users`, `user_identities`, `tenant_memberships`, `tenant_invitations`, and `audit_events` are empty.
- `permissions` contains 26 permission codes.
- `demo_airline` has 6 default roles.
- Role-permission links are seeded for the six roles.
