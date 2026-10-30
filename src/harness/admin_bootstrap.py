"""One-time, allow-listed first Company Admin provisioning for Google OIDC.

The bootstrap grants no access from a browser-supplied email alone. It requires a
Google OIDC profile produced by google_profile_from_streamlit_user(), an exact local
allow-list email configured in Streamlit secrets, an active tenant, and no existing
Company Admin assignment for that tenant. All local user/identity/membership/role/audit
writes occur in one database transaction. No schema migration is performed here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Engine, text

from src.harness.oidc_adapter import GOOGLE_ISSUER, GOOGLE_PROVIDER_CODE, GoogleOIDCProfile

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_TENANT_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class FirstAdminBootstrapError(RuntimeError):
    """First-admin provisioning was not allowed or could not be completed."""


@dataclass(frozen=True, slots=True)
class FirstAdminBootstrapSettings:
    enabled: bool
    tenant_code: str
    admin_email_normalized: str


def load_first_admin_bootstrap_settings(
    secrets: Mapping[str, object],
) -> FirstAdminBootstrapSettings:
    raw = secrets.get("aeroinsight_bootstrap")
    if not isinstance(raw, Mapping):
        raise FirstAdminBootstrapError("First-admin bootstrap is not configured in local Streamlit secrets.")
    enabled = raw.get("enabled")
    tenant_code = raw.get("tenant_code")
    email = raw.get("admin_email")
    if enabled is not True:
        raise FirstAdminBootstrapError("First-admin bootstrap is disabled.")
    if not isinstance(tenant_code, str) or not _TENANT_CODE_RE.fullmatch(tenant_code):
        raise FirstAdminBootstrapError("First-admin tenant configuration is invalid.")
    if tenant_code != "demo_airline":
        raise FirstAdminBootstrapError("Initial bootstrap is restricted to demo_airline.")
    if not isinstance(email, str):
        raise FirstAdminBootstrapError("First-admin email is not configured.")
    normalized_email = email.strip().lower()
    if len(normalized_email) > 254 or not _EMAIL_RE.fullmatch(normalized_email):
        raise FirstAdminBootstrapError("First-admin email configuration is invalid.")
    return FirstAdminBootstrapSettings(True, tenant_code, normalized_email)


class FirstAdminBootstrapRepository:
    """Provision the first Company Admin exactly once for the configured tenant."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def provision_first_company_admin(
        self,
        profile: GoogleOIDCProfile,
        settings: FirstAdminBootstrapSettings,
    ) -> dict[str, int | str]:
        if not isinstance(profile, GoogleOIDCProfile) or profile.email_verified is not True:
            raise FirstAdminBootstrapError("A verified Google identity is required.")
        if (
            profile.identity.identity_provider_code != GOOGLE_PROVIDER_CODE
            or profile.identity.issuer_url != GOOGLE_ISSUER
        ):
            raise FirstAdminBootstrapError("Only the configured Google identity can bootstrap this tenant.")
        if profile.email_normalized != settings.admin_email_normalized:
            raise FirstAdminBootstrapError("This Google account is not the configured first-admin account.")
        if not settings.enabled:
            raise FirstAdminBootstrapError("First-admin bootstrap is disabled.")

        # MySQL locks the tenant row so concurrent first-login attempts serialize.
        lock_clause = " FOR UPDATE" if self._engine.dialect.name in {"mysql", "mariadb", "postgresql"} else ""
        with self._engine.begin() as connection:
            tenant = connection.execute(
                text(
                    "SELECT tenant_id, display_name, tenant_status FROM tenants "
                    "WHERE tenant_code = :tenant_code" + lock_clause
                ),
                {"tenant_code": settings.tenant_code},
            ).mappings().one_or_none()
            if tenant is None or tenant["tenant_status"] != "active":
                raise FirstAdminBootstrapError("The configured company is missing or inactive.")
            tenant_id = int(tenant["tenant_id"])

            existing_admin = connection.execute(
                text(
                    """
                    SELECT mr.membership_id
                    FROM membership_roles AS mr
                    INNER JOIN roles AS r
                      ON r.tenant_id = mr.tenant_id AND r.role_id = mr.role_id
                    WHERE mr.tenant_id = :tenant_id AND r.role_code = 'company_admin'
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id},
            ).first()
            prior_bootstrap = connection.execute(
                text(
                    """
                    SELECT audit_event_id FROM audit_events
                    WHERE tenant_id = :tenant_id
                      AND action_code = 'identity.first_admin_bootstrapped'
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id},
            ).first()
            if existing_admin is not None or prior_bootstrap is not None:
                raise FirstAdminBootstrapError(
                    "First-admin bootstrap has already been claimed for this company."
                )

            existing_identity = connection.execute(
                text(
                    """
                    SELECT user_identity_id, user_id, identity_provider_code,
                           provider_email_normalized
                    FROM user_identities
                    WHERE issuer_url = :issuer_url AND subject_id = :subject_id
                    """ + lock_clause
                ),
                {
                    "issuer_url": profile.identity.issuer_url,
                    "subject_id": profile.identity.subject_id,
                },
            ).mappings().one_or_none()

            if existing_identity is not None:
                if (
                    existing_identity["identity_provider_code"] != GOOGLE_PROVIDER_CODE
                    or int(existing_identity["user_id"]) <= 0
                ):
                    raise FirstAdminBootstrapError("This Google identity is already linked to another account.")
                user_id = int(existing_identity["user_id"])
                if existing_identity["provider_email_normalized"] not in (None, profile.email_normalized):
                    raise FirstAdminBootstrapError("The linked Google identity email does not match the allow-list.")
                user = connection.execute(
                    text("SELECT user_id, user_status FROM users WHERE user_id = :user_id" + lock_clause),
                    {"user_id": user_id},
                ).mappings().one_or_none()
                connection.execute(
                    text(
                        """
                        UPDATE user_identities
                        SET provider_email_normalized = :provider_email, email_verified = 1
                        WHERE user_identity_id = :identity_id
                        """
                    ),
                    {
                        "provider_email": profile.email_normalized,
                        "identity_id": int(existing_identity["user_identity_id"]),
                    },
                )
            else:
                user = connection.execute(
                    text("SELECT user_id, user_status FROM users WHERE email_normalized = :email" + lock_clause),
                    {"email": profile.email_normalized},
                ).mappings().one_or_none()
                if user is None:
                    result = connection.execute(
                        text(
                            """
                            INSERT INTO users (email_normalized, display_name, user_status)
                            VALUES (:email, :display_name, 'active')
                            """
                        ),
                        {"email": profile.email_normalized, "display_name": profile.display_name[:128]},
                    )
                    user_id = int(result.lastrowid)
                    user = {"user_id": user_id, "user_status": "active"}
                else:
                    user_id = int(user["user_id"])

                connection.execute(
                    text(
                        """
                        INSERT INTO user_identities (
                            user_id, identity_provider_code, issuer_url, subject_id,
                            provider_email_normalized, email_verified
                        ) VALUES (
                            :user_id, :provider_code, :issuer_url, :subject_id,
                            :provider_email, 1
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "provider_code": GOOGLE_PROVIDER_CODE,
                        "issuer_url": profile.identity.issuer_url,
                        "subject_id": profile.identity.subject_id,
                        "provider_email": profile.email_normalized,
                    },
                )

            if user is None:
                raise FirstAdminBootstrapError("The local user record could not be resolved.")
            user_status = str(user["user_status"])
            if user_status not in {"active", "pending"}:
                raise FirstAdminBootstrapError("The local user account is suspended or disabled.")
            if user_status == "pending":
                connection.execute(
                    text("UPDATE users SET user_status = 'active' WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )

            membership = connection.execute(
                text(
                    """
                    SELECT membership_id, membership_status
                    FROM tenant_memberships
                    WHERE tenant_id = :tenant_id AND user_id = :user_id
                    """ + lock_clause
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            ).mappings().one_or_none()
            if membership is None:
                result = connection.execute(
                    text(
                        """
                        INSERT INTO tenant_memberships (
                            tenant_id, user_id, membership_status, activated_at_utc
                        ) VALUES (:tenant_id, :user_id, 'active', CURRENT_TIMESTAMP)
                        """
                    ),
                    {"tenant_id": tenant_id, "user_id": user_id},
                )
                membership_id = int(result.lastrowid)
            else:
                membership_id = int(membership["membership_id"])
                membership_status = str(membership["membership_status"])
                if membership_status not in {"active", "pending"}:
                    raise FirstAdminBootstrapError("The existing company membership is not eligible for activation.")
                if membership_status == "pending":
                    connection.execute(
                        text(
                            """
                            UPDATE tenant_memberships
                            SET membership_status = 'active', activated_at_utc = CURRENT_TIMESTAMP
                            WHERE tenant_id = :tenant_id AND membership_id = :membership_id
                            """
                        ),
                        {"tenant_id": tenant_id, "membership_id": membership_id},
                    )

            role = connection.execute(
                text(
                    """
                    SELECT role_id FROM roles
                    WHERE tenant_id = :tenant_id AND role_code = 'company_admin'
                      AND role_status = 'active'
                    """ + lock_clause
                ),
                {"tenant_id": tenant_id},
            ).mappings().one_or_none()
            if role is None:
                raise FirstAdminBootstrapError("The Company Admin role is missing or inactive.")

            connection.execute(
                text(
                    """
                    INSERT INTO membership_roles (
                        tenant_id, membership_id, role_id, assigned_by_membership_id
                    ) VALUES (:tenant_id, :membership_id, :role_id, NULL)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "membership_id": membership_id,
                    "role_id": int(role["role_id"]),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO audit_events (
                        tenant_id, actor_membership_id, action_code, target_type,
                        target_reference, outcome_code, event_details_json
                    ) VALUES (
                        :tenant_id, :membership_id, 'identity.first_admin_bootstrapped',
                        'user', :target_reference, 'success', :details
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "membership_id": membership_id,
                    "target_reference": str(user_id),
                    "details": '{"identity_provider":"google_oidc","method":"verified_email_allowlist"}',
                },
            )

        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "membership_id": membership_id,
            "tenant_code": settings.tenant_code,
        }
