"""Application service for identity resolution, tenant selection and RBAC checks."""

from __future__ import annotations

import logging

from sqlalchemy import Engine

from src.harness.auth_models import (
    AuthenticatedTenantContext,
    AuthenticatedUser,
    TenantMembership,
    VerifiedExternalIdentity,
)
from src.harness.authorization_repository import AuthorizationRepository
from src.harness.exceptions import PermissionDenied

logger = logging.getLogger(__name__)


class AuthorizationService:
    """Coordinates verified identity lookup and tenant-scoped authorization.

    The caller must provide VerifiedExternalIdentity only after an OIDC adapter has
    validated signature, issuer, audience, expiry, nonce and the configured provider.
    This service does not validate JWTs or implement a login/session flow.
    """

    def __init__(
        self,
        engine: Engine,
        repository: AuthorizationRepository | None = None,
    ) -> None:
        self._repository = repository or AuthorizationRepository(engine)

    def authenticate_verified_identity(
        self, identity: VerifiedExternalIdentity
    ) -> AuthenticatedUser:
        """Map a verified external identity to an active local user."""
        if not isinstance(identity, VerifiedExternalIdentity):
            raise TypeError("A VerifiedExternalIdentity is required.")
        return self._repository.resolve_active_user(identity)

    def list_available_tenants(
        self, user: AuthenticatedUser
    ) -> tuple[TenantMembership, ...]:
        """Return active tenant memberships for a resolved active user."""
        if not isinstance(user, AuthenticatedUser):
            raise TypeError("An AuthenticatedUser resolved by this service is required.")
        return self._repository.list_active_memberships(user)

    def select_tenant(
        self, user: AuthenticatedUser, requested_tenant_id: int
    ) -> AuthenticatedTenantContext:
        """Verify membership and load roles/permissions for the selected tenant.

        `requested_tenant_id` is untrusted UI input. The repository rechecks it against
        the user's active membership, user status and tenant status on every selection.
        """
        if not isinstance(user, AuthenticatedUser):
            raise TypeError("An AuthenticatedUser resolved by this service is required.")
        return self._repository.load_tenant_context(user, requested_tenant_id)

    def require_permission(
        self,
        context: AuthenticatedTenantContext,
        permission_code: str,
    ) -> int:
        """Require a permission; return the tenant_id to bind into SQL statements.

        A denied check is recorded in `audit_events`. If audit writing fails, access
        remains denied; the audit failure is logged without recording secrets.
        """
        if not isinstance(context, AuthenticatedTenantContext):
            raise TypeError("A server-resolved AuthenticatedTenantContext is required.")
        try:
            return context.require_permission(permission_code)
        except PermissionDenied:
            try:
                self._repository.insert_audit_event(
                    context,
                    action_code="authorization.permission_denied",
                    outcome_code="denied",
                    target_type="permission",
                    target_reference=permission_code[:128],
                    event_details={"reason": "missing_permission"},
                )
            except Exception:  # audit failure must never turn a denial into a grant
                logger.exception("Failed to persist authorization-denial audit event.")
            raise

    def record_security_event(
        self,
        context: AuthenticatedTenantContext,
        *,
        action_code: str,
        outcome_code: str,
        target_type: str | None = None,
        target_reference: str | None = None,
        event_details: dict[str, object] | None = None,
    ) -> int:
        """Record the outcome of a security-sensitive operation after it completes.

        Call this for completed privileged operations (for example, role assignment or
        membership suspension). Do not record passwords, tokens, prompts or passenger data.
        """
        if not isinstance(context, AuthenticatedTenantContext):
            raise TypeError("A server-resolved AuthenticatedTenantContext is required.")
        return self._repository.insert_audit_event(
            context,
            action_code=action_code,
            outcome_code=outcome_code,
            target_type=target_type,
            target_reference=target_reference,
            event_details=event_details,
        )
