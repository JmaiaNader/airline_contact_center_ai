"""Immutable security context types.

Important: VerifiedExternalIdentity must only be created by a trusted identity-provider
adapter after cryptographic OIDC token validation. It is not a token parser/verifier.
Never construct it from Streamlit widgets, query parameters, or LLM output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.harness.exceptions import PermissionDenied

_PROVIDER_CODE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_PERMISSION_CODE = re.compile(r"^[a-z][a-z0-9_.]{0,99}$")


def _require_positive_id(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class VerifiedExternalIdentity:
    """Identity claims whose signature, issuer, audience, expiry and nonce were verified.

    The future OIDC adapter must validate the token against a configured provider before
    constructing this object. `subject_id` is the provider's stable `sub` claim; email is
    deliberately not used as the identity key.
    """

    identity_provider_code: str
    issuer_url: str
    subject_id: str

    def __post_init__(self) -> None:
        provider = self.identity_provider_code.strip()
        if not _PROVIDER_CODE.fullmatch(provider):
            raise ValueError("identity_provider_code has an invalid format.")
        if not self.issuer_url or not self.issuer_url.strip():
            raise ValueError("issuer_url is required.")
        if len(self.issuer_url) > 512:
            raise ValueError("issuer_url exceeds 512 characters.")
        if not self.subject_id or not self.subject_id.strip():
            raise ValueError("subject_id is required.")
        if len(self.subject_id) > 255:
            raise ValueError("subject_id exceeds 255 characters.")
        object.__setattr__(self, "identity_provider_code", provider)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """A local active user resolved from a verified external identity."""

    user_id: int
    email_normalized: str
    display_name: str
    identity_provider_code: str
    issuer_url: str
    subject_id: str

    def __post_init__(self) -> None:
        _require_positive_id(self.user_id, "user_id")


@dataclass(frozen=True, slots=True)
class TenantMembership:
    """A currently active tenant membership available to the authenticated user."""

    membership_id: int
    tenant_id: int
    tenant_code: str
    tenant_display_name: str
    membership_status: str
    tenant_status: str

    def __post_init__(self) -> None:
        _require_positive_id(self.membership_id, "membership_id")
        _require_positive_id(self.tenant_id, "tenant_id")


@dataclass(frozen=True, slots=True)
class AuthenticatedTenantContext:
    """Server-resolved identity, active membership, roles and permissions for one tenant.

    Do not accept or deserialize this object from a browser, Streamlit widget, URL, or LLM.
    Build it through AuthorizationService.select_tenant after resolving a verified identity.
    """

    user_id: int
    membership_id: int
    tenant_id: int
    tenant_code: str
    tenant_display_name: str
    email_normalized: str
    display_name: str
    identity_provider_code: str
    issuer_url: str
    subject_id: str
    role_codes: frozenset[str]
    permission_codes: frozenset[str]

    def __post_init__(self) -> None:
        _require_positive_id(self.user_id, "user_id")
        _require_positive_id(self.membership_id, "membership_id")
        _require_positive_id(self.tenant_id, "tenant_id")
        object.__setattr__(self, "role_codes", frozenset(self.role_codes))
        object.__setattr__(self, "permission_codes", frozenset(self.permission_codes))

    def has_permission(self, permission_code: str) -> bool:
        """Return True only for an exact permission-code grant; no wildcard behavior."""
        if not isinstance(permission_code, str) or not _PERMISSION_CODE.fullmatch(permission_code):
            return False
        return permission_code in self.permission_codes

    def require_permission(self, permission_code: str) -> int:
        """Require a permission and return the trusted tenant_id for SQL binding."""
        if not self.has_permission(permission_code):
            raise PermissionDenied(
                f"Permission is required: {permission_code!r}."
            )
        return self.tenant_id
