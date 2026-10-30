# Google OIDC + First Company Admin + Persistent Mapping Approval

## Scope

This stage connects Google OIDC sign-in to the existing Migration 003 identity/RBAC
schema and enables a one-time first Company Admin bootstrap for `demo_airline`.
It does **not** add a database migration. It reuses the existing tables:

- `users`
- `user_identities`
- `tenant_memberships`
- `roles`
- `membership_roles`
- `role_permissions`
- `audit_events`

Semantic mapping suggestions, approvals, review evidence, mapping versions and audit
events continue to be stored in the existing Migration 004 tables in `db_airlines`.

## Authentication and authorization boundary

- Streamlit `st.login("google")` performs the OIDC login/callback flow.
- Streamlit validates the OIDC response and exposes ID-token claims through `st.user`.
- The application additionally checks the exact Google issuer, stable `sub`, verified
  email, `iat`, and `exp` before building a local identity profile.
- The local identity key is `(issuer_url, subject_id)`. Email is used only for the
  one-time allow-list bootstrap and display/account matching; it is not the identity key.
- `AuthorizationService` resolves the active local user, active tenant membership,
  roles and permissions from `db_airlines` on every page run.
- The selected tenant ID is rechecked against the database; it is never trusted from
  browser state alone.

OIDC authenticates identity; it does not grant application permissions.

## One-time first-admin bootstrap

The operator configures one exact Google email in local `.streamlit/secrets.toml`:

```toml
[aeroinsight_bootstrap]
enabled = true
tenant_code = "demo_airline"
admin_email = "your-verified-google-email@example.com"
```

The initial login is eligible only if all conditions hold:

1. Streamlit reports the user as logged in.
2. The ID-token issuer is exactly `https://accounts.google.com`.
3. `sub` is present and non-empty.
4. `email_verified` is exactly `true`.
5. The ID token has a valid `iat` and an `exp` in the future.
6. The normalized email exactly matches the local bootstrap allow-list.
7. The `demo_airline` tenant is active.
8. No `company_admin` role has already been assigned for that tenant and no
   `identity.first_admin_bootstrapped` audit event exists.

The repository locks the tenant row during the transaction, then creates/links the
local user and Google identity, activates the membership, assigns the existing
`company_admin` role, and writes the durable bootstrap audit event in one transaction.
If any operation fails, the transaction rolls back. The audit marker permanently
closes the bootstrap path even if the admin role is later removed. Subsequent users
must be provisioned through an authorized administration workflow.

No default email, password, Google account, Client ID, or Client Secret is embedded
in this patch. The operator must provide their own values locally.

## Google setup (local development)

1. In Google Cloud Console, create or select a project and configure the OAuth consent
   screen for the intended development use.
2. Create an OAuth Client ID of type **Web application**.
3. Add this exact Authorized redirect URI:
   `http://localhost:8501/oauth2callback`
4. Copy the generated Client ID and Client Secret into a local `.streamlit/secrets.toml`.
5. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
6. Generate a cookie secret locally:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`
7. Replace the cookie-secret placeholder, Google Client ID, Google Client Secret,
   and `admin_email` with the same verified Google email account you intend to use.
8. Run `scripts/ensure_oidc_secrets_ignored.ps1` and verify:
   `git check-ignore -v .streamlit/secrets.toml`
9. Start the app with `python -m streamlit run app/main.py` and sign in with Google.

For a deployed app, register its HTTPS callback URL with Google and update `redirect_uri`.
Never commit `secrets.toml`, Client Secrets, ID tokens or browser cookies.

## Persistence after testing and restarts

- OIDC provider credentials and the bootstrap allow-list remain in local
  `.streamlit/secrets.toml`; the patch never overwrites this real file.
- The user's Google issuer/subject link, active user, tenant membership, Company Admin
  role grant and bootstrap audit event persist in `db_airlines`.
- Semantic mapping suggestions, approved/rejected status, selected concept/version,
  review evidence, reviewer membership and audit events persist in the existing
  Migration 004 tables in `db_airlines`.
- Streamlit reruns and application restarts do not delete these database records.

## Tests and limits

The new tests cover claim validation, verified-email allow-list behavior, one-time
bootstrap, membership/role creation and durable bootstrap lockout using an isolated
SQLite test database. The tests do not contact Google or modify the user's MySQL DB.
A real Google OIDC callback still requires the operator's Google OAuth credentials and
registered redirect URI. The patch does not provision additional company users; that
will be handled by the future tenant user-management workflow.
