# AeroInsight Authorization Layer v1

## Scope

This patch implements the Python authorization core for the tables created by Migration 003:

- `users`
- `user_identities`
- `tenant_memberships`
- `tenants` (created by Migration 002)
- `roles`
- `membership_roles`
- `permissions`
- `role_permissions`
- `audit_events`

It is additive. It does not modify migrations, database schema, Streamlit pages, or LLM providers.

## Important authentication boundary

This patch does **not** implement OIDC/JWT verification or a browser login flow. `VerifiedExternalIdentity` is an internal DTO that may be constructed only after a future trusted OIDC adapter validates at least:

- signature against the configured issuer's signing keys;
- exact issuer (`iss`);
- expected audience/client ID (`aud`);
- token expiry and not-before (`exp`, `nbf`);
- nonce for an authorization-code login;
- allowed signing algorithm and provider configuration.

Do not create `VerifiedExternalIdentity` from Streamlit form fields, URL parameters, headers supplied by an untrusted client, or LLM output. Never accept a raw `user_id` or `tenant_id` as proof of access.

The service maps the verified `(identity_provider_code, issuer_url, subject_id)` to one active local `users` record. Email is not used as the identity key. User provisioning and invitation acceptance are separate workflows and are not implemented here.

## Tenant selection

The UI may send a requested tenant ID, but the backend rechecks all of the following in MySQL:

- local user has `user_status = 'active'`;
- membership belongs to that user and requested tenant;
- membership has `membership_status = 'active'`;
- tenant has `tenant_status = 'active'`.

Only then does it load active tenant roles and the permissions granted to those roles. Disabled roles do not grant permissions. A user can have different roles in different tenants.

## Permission enforcement

Permission codes are exact strings from the global `permissions` catalog seeded by Migration 003, for example:

- `tenant.manage`
- `membership.invite`
- `data_source.manage`
- `mapping.approve`
- `kpi.view`
- `forecast.manage`
- `wfm.manage`
- `rtm.manage`
- `policy.view`

No wildcards or role-name checks are supported. Use `AuthorizationService.require_permission(context, "kpi.view")`; it returns the trusted `tenant_id` that must be bound into the SQL statement. Example:

```python
trusted_tenant_id = authorization_service.require_permission(
    tenant_context,
    "kpi.view",
)

statement = text("""
    SELECT metric_value
    FROM tenant_metric_view
    WHERE tenant_id = :tenant_id
      AND metric_date >= :start_date
""")
rows = connection.execute(
    statement,
    {"tenant_id": trusted_tenant_id, "start_date": start_date},
)
```

Every company-scoped repository method must require a server-resolved `AuthenticatedTenantContext`, call the required permission check, and filter with the returned tenant ID. Do not expose a general SQL execution function to LangGraph. Composite foreign keys from Migration 002 are a second line of defense, not a replacement for this authorization layer.

## Audit

Denied permission checks are appended to `audit_events`. The audit writer only accepts bounded scalar metadata and rejects sensitive key names (password, token, secret, API key, prompt, passenger, booking reference, email, phone, credential). Privileged workflows should call `record_security_event` after the operation completes, with an accurate outcome. Never log tokens, passwords, API keys, full prompts, passenger data, or unnecessary personal data.

If audit writing for a denied permission fails, access remains denied. The failure is logged without granting access.

## Failure behavior

- Unlinked or inactive user: `AuthenticationFailed`.
- No active membership in selected tenant, inactive user, or inactive tenant: `TenantAccessDenied`.
- Missing permission: `PermissionDenied` and a tenant-scoped denial audit event.
- Unknown permission: denied (there is no wildcard behavior).
- Database errors: propagate as infrastructure errors; callers must fail closed.

## Not implemented yet

- OIDC provider configuration, token verification, callback, login/logout and session lifecycle;
- invitation creation/delivery/acceptance and local user provisioning;
- password authentication (not planned for this phase);
- Streamlit login or tenant-switch UI;
- administrative role-management workflows;
- automatic authorization injection into every existing tool/repository (those modules must be added behind this service as they are built).

Do not onboard real users or expose a production application until OIDC verification, session security, user provisioning, repository-level tenant filters, secret handling, and security tests are completed.

## Verification

Run the focused tests:

```powershell
python -m pytest tests/test_authorization_layer.py -q
```

Then run the complete suite:

```powershell
python -m pytest -q
```

The tests use an in-memory SQLite schema matching the relevant Migration 003 columns. They do not connect to or change MySQL.
