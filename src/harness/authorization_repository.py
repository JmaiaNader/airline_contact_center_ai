"""SQLAlchemy repository for Migration 003 identity and tenant authorization tables.

All SQL is parameterized. This repository does not create users, memberships, roles,
or permissions. Those are provisioned by separately authorized workflows.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, text

from src.harness.auth_models import (
    AuthenticatedTenantContext,
    AuthenticatedUser,
    TenantMembership,
    VerifiedExternalIdentity,
)
from src.harness.exceptions import AuthenticationFailed, TenantAccessDenied

_ACTION_CODE = re.compile(r"^[a-z][a-z0-9_.]{0,99}$")
_SAFE_METADATA_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_FORBIDDEN_METADATA_FRAGMENTS = (
    "password", "token", "secret", "api_key", "authorization", "prompt",
    "passenger", "booking_reference", "email", "phone", "credential",
)
_ALLOWED_METADATA_TYPES = (str, int, float, bool, type(None))


class AuthorizationRepository:
    """Read identity/membership grants and append security audit events."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def resolve_active_user(
        self, identity: VerifiedExternalIdentity
    ) -> AuthenticatedUser:
        """Resolve the provider's stable issuer+subject pair to an active local user."""
        statement = text(
            """
            SELECT
                u.user_id,
                u.email_normalized,
                u.display_name,
                ui.user_identity_id
            FROM user_identities AS ui
            INNER JOIN users AS u ON u.user_id = ui.user_id
            WHERE ui.identity_provider_code = :provider_code
              AND ui.issuer_url = :issuer_url
              AND ui.subject_id = :subject_id
              AND u.user_status = 'active'
            """
        )
        with self._engine.begin() as connection:
            row = connection.execute(
                statement,
                {
                    "provider_code": identity.identity_provider_code,
                    "issuer_url": identity.issuer_url,
                    "subject_id": identity.subject_id,
                },
            ).mappings().one_or_none()
            if row is None:
                # Generic error avoids revealing whether an email/user exists.
                raise AuthenticationFailed("Authentication could not be completed.")

            connection.execute(
                text(
                    """
                    UPDATE user_identities
                    SET last_authenticated_at_utc = CURRENT_TIMESTAMP
                    WHERE user_identity_id = :identity_id
                    """
                ),
                {"identity_id": row["user_identity_id"]},
            )

        return AuthenticatedUser(
            user_id=int(row["user_id"]),
            email_normalized=str(row["email_normalized"]),
            display_name=str(row["display_name"]),
            identity_provider_code=identity.identity_provider_code,
            issuer_url=identity.issuer_url,
            subject_id=identity.subject_id,
        )

    def list_active_memberships(
        self, user: AuthenticatedUser
    ) -> tuple[TenantMembership, ...]:
        """List only active memberships under active users and active tenants."""
        statement = text(
            """
            SELECT
                tm.membership_id,
                tm.tenant_id,
                t.tenant_code,
                t.display_name AS tenant_display_name,
                tm.membership_status,
                t.tenant_status
            FROM tenant_memberships AS tm
            INNER JOIN users AS u ON u.user_id = tm.user_id
            INNER JOIN tenants AS t ON t.tenant_id = tm.tenant_id
            WHERE tm.user_id = :user_id
              AND u.user_status = 'active'
              AND tm.membership_status = 'active'
              AND t.tenant_status = 'active'
            ORDER BY t.display_name, t.tenant_id
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement, {"user_id": user.user_id}
            ).mappings().all()

        return tuple(
            TenantMembership(
                membership_id=int(row["membership_id"]),
                tenant_id=int(row["tenant_id"]),
                tenant_code=str(row["tenant_code"]),
                tenant_display_name=str(row["tenant_display_name"]),
                membership_status=str(row["membership_status"]),
                tenant_status=str(row["tenant_status"]),
            )
            for row in rows
        )

    def load_tenant_context(
        self, user: AuthenticatedUser, tenant_id: int
    ) -> AuthenticatedTenantContext:
        """Resolve the requested tenant from DB membership; never trust UI tenant_id alone."""
        if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
            raise ValueError("tenant_id must be a positive integer.")

        statement = text(
            """
            SELECT
                tm.membership_id,
                tm.tenant_id,
                t.tenant_code,
                t.display_name AS tenant_display_name,
                u.user_id,
                u.email_normalized,
                u.display_name,
                r.role_code,
                rp.permission_code
            FROM tenant_memberships AS tm
            INNER JOIN users AS u ON u.user_id = tm.user_id
            INNER JOIN tenants AS t ON t.tenant_id = tm.tenant_id
            LEFT JOIN membership_roles AS mr
              ON mr.tenant_id = tm.tenant_id
             AND mr.membership_id = tm.membership_id
            LEFT JOIN roles AS r
              ON r.tenant_id = mr.tenant_id
             AND r.role_id = mr.role_id
             AND r.role_status = 'active'
            LEFT JOIN role_permissions AS rp
              ON rp.tenant_id = r.tenant_id
             AND rp.role_id = r.role_id
            LEFT JOIN permissions AS p
              ON p.permission_code = rp.permission_code
            WHERE tm.user_id = :user_id
              AND tm.tenant_id = :tenant_id
              AND tm.membership_status = 'active'
              AND u.user_status = 'active'
              AND t.tenant_status = 'active'
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {"user_id": user.user_id, "tenant_id": tenant_id},
            ).mappings().all()

        if not rows:
            raise TenantAccessDenied(
                "No active membership is available for the requested tenant."
            )

        first = rows[0]
        role_codes = frozenset(
            str(row["role_code"]) for row in rows if row["role_code"] is not None
        )
        permission_codes = frozenset(
            str(row["permission_code"])
            for row in rows
            if row["permission_code"] is not None
        )

        return AuthenticatedTenantContext(
            user_id=int(first["user_id"]),
            membership_id=int(first["membership_id"]),
            tenant_id=int(first["tenant_id"]),
            tenant_code=str(first["tenant_code"]),
            tenant_display_name=str(first["tenant_display_name"]),
            email_normalized=str(first["email_normalized"]),
            display_name=str(first["display_name"]),
            identity_provider_code=user.identity_provider_code,
            issuer_url=user.issuer_url,
            subject_id=user.subject_id,
            role_codes=role_codes,
            permission_codes=permission_codes,
        )

    def insert_audit_event(
        self,
        context: AuthenticatedTenantContext,
        *,
        action_code: str,
        outcome_code: str,
        target_type: str | None = None,
        target_reference: str | None = None,
        event_details: Mapping[str, Any] | None = None,
    ) -> int:
        """Append one tenant-scoped audit event with bounded, non-sensitive metadata."""
        if not _ACTION_CODE.fullmatch(action_code):
            raise ValueError("action_code has an invalid format.")
        if outcome_code not in {"success", "denied", "failure"}:
            raise ValueError("outcome_code must be success, denied, or failure.")
        if target_type is not None and len(target_type) > 64:
            raise ValueError("target_type exceeds 64 characters.")
        if target_reference is not None and len(target_reference) > 128:
            raise ValueError("target_reference exceeds 128 characters.")

        safe_details: dict[str, Any] = {}
        for key, value in (event_details or {}).items():
            normalized_key = str(key).lower()
            if not _SAFE_METADATA_KEY.fullmatch(normalized_key):
                raise ValueError("Audit metadata contains an invalid key.")
            if any(fragment in normalized_key for fragment in _FORBIDDEN_METADATA_FRAGMENTS):
                raise ValueError("Sensitive audit metadata keys are not allowed.")
            if not isinstance(value, _ALLOWED_METADATA_TYPES):
                raise ValueError("Audit metadata values must be scalar JSON values.")
            if isinstance(value, str) and len(value) > 256:
                raise ValueError("Audit metadata string values are limited to 256 characters.")
            safe_details[normalized_key] = value

        serialized_details = json.dumps(
            safe_details, ensure_ascii=False, separators=(",", ":")
        )
        if len(serialized_details.encode("utf-8")) > 4096:
            raise ValueError("Audit metadata exceeds 4096 bytes.")

        statement = text(
            """
            INSERT INTO audit_events (
                tenant_id,
                actor_membership_id,
                action_code,
                target_type,
                target_reference,
                outcome_code,
                event_details_json
            ) VALUES (
                :tenant_id,
                :actor_membership_id,
                :action_code,
                :target_type,
                :target_reference,
                :outcome_code,
                :event_details_json
            )
            """
        )
        with self._engine.begin() as connection:
            result = connection.execute(
                statement,
                {
                    "tenant_id": context.tenant_id,
                    "actor_membership_id": context.membership_id,
                    "action_code": action_code,
                    "target_type": target_type,
                    "target_reference": target_reference,
                    "outcome_code": outcome_code,
                    "event_details_json": serialized_details,
                },
            )
            return int(result.lastrowid)
