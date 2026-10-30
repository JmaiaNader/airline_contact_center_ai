# AeroInsight — Python Authorization Layer v1

## Included files

- `src/harness/__init__.py`
- `src/harness/exceptions.py`
- `src/harness/auth_models.py`
- `src/harness/authorization_repository.py`
- `src/harness/authorization_service.py`
- `tests/test_authorization_layer.py`
- `docs/authorization_layer_v1.md`

## Apply

Extract this ZIP into the root of your existing `airline_contact_center_ai` project. It adds files only and does not replace existing modules, migrations, configuration, or database tables.

## Test

```powershell
python -m pytest tests/test_authorization_layer.py -q
python -m pytest -q
```

The focused tests use an in-memory SQLite schema and do not connect to MySQL.

## Security boundary

This is the authorization core and external-identity mapping layer. It is **not** an OIDC/JWT verifier and it is not a completed login flow. Only a trusted OIDC adapter that validates signature, issuer, audience, expiry, not-before and nonce may construct `VerifiedExternalIdentity`. Do not create that object from UI input.

The layer does not create users, memberships, role grants or invitations. It resolves existing records from Migration 003 and denies access unless user, membership and tenant are all active.
