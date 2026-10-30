"""Safe, domain-specific authentication and authorization exceptions."""


class AuthorizationError(Exception):
    """Base class for expected authorization failures."""


class AuthenticationFailed(AuthorizationError):
    """The verified external identity is not linked to an active local user."""


class TenantAccessDenied(AuthorizationError):
    """The user has no active membership in the requested active tenant."""


class PermissionDenied(AuthorizationError):
    """The active tenant membership does not grant the required permission."""
