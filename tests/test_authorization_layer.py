from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.harness.auth_models import VerifiedExternalIdentity
from src.harness.authorization_service import AuthorizationService
from src.harness.exceptions import (
    AuthenticationFailed,
    PermissionDenied,
    TenantAccessDenied,
)


@pytest.fixture()
def auth_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    schema = [
        """CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            email_normalized TEXT NOT NULL,
            display_name TEXT NOT NULL,
            user_status TEXT NOT NULL
        )""",
        """CREATE TABLE user_identities (
            user_identity_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            identity_provider_code TEXT NOT NULL,
            issuer_url TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            last_authenticated_at_utc TEXT NULL
        )""",
        """CREATE TABLE tenants (
            tenant_id INTEGER PRIMARY KEY,
            tenant_code TEXT NOT NULL,
            display_name TEXT NOT NULL,
            tenant_status TEXT NOT NULL
        )""",
        """CREATE TABLE tenant_memberships (
            membership_id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            membership_status TEXT NOT NULL
        )""",
        """CREATE TABLE roles (
            role_id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            role_code TEXT NOT NULL,
            role_name TEXT NOT NULL,
            role_status TEXT NOT NULL
        )""",
        """CREATE TABLE membership_roles (
            tenant_id INTEGER NOT NULL,
            membership_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL
        )""",
        """CREATE TABLE permissions (
            permission_code TEXT PRIMARY KEY,
            permission_category TEXT NOT NULL,
            description TEXT NOT NULL
        )""",
        """CREATE TABLE role_permissions (
            tenant_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            permission_code TEXT NOT NULL
        )""",
        """CREATE TABLE audit_events (
            audit_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            actor_membership_id INTEGER NULL,
            action_code TEXT NOT NULL,
            target_type TEXT NULL,
            target_reference TEXT NULL,
            outcome_code TEXT NOT NULL,
            event_details_json TEXT NULL,
            occurred_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    with engine.begin() as connection:
        for statement in schema:
            connection.execute(text(statement))
        connection.execute(
            text(
                """
                INSERT INTO users VALUES
                    (1, 'user1@example.test', 'User One', 'active'),
                    (2, 'suspended@example.test', 'Suspended User', 'suspended')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO user_identities
                    (user_identity_id, user_id, identity_provider_code, issuer_url, subject_id)
                VALUES
                    (1, 1, 'oidc_dev', 'https://issuer.example.test', 'subject-1'),
                    (2, 2, 'oidc_dev', 'https://issuer.example.test', 'subject-2')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tenants VALUES
                    (10, 'airline_a', 'Airline A', 'active'),
                    (20, 'bank_b', 'Bank B', 'active'),
                    (30, 'closed_c', 'Closed C', 'closed')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tenant_memberships VALUES
                    (100, 10, 1, 'active'),
                    (200, 20, 1, 'active'),
                    (300, 30, 1, 'active'),
                    (400, 10, 2, 'active'),
                    (500, 10, 1, 'suspended')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO roles VALUES
                    (1000, 10, 'company_admin', 'Company Admin', 'active'),
                    (2000, 20, 'viewer', 'Viewer', 'active'),
                    (2001, 20, 'manager', 'Manager', 'disabled')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO membership_roles VALUES
                    (10, 100, 1000),
                    (20, 200, 2000),
                    (20, 200, 2001)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO permissions VALUES
                    ('tenant.view', 'tenant', 'View tenant'),
                    ('tenant.manage', 'tenant', 'Manage tenant'),
                    ('kpi.view', 'analytics', 'View KPIs'),
                    ('data.view', 'analytics', 'View authorized data')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO role_permissions VALUES
                    (10, 1000, 'tenant.view'),
                    (10, 1000, 'tenant.manage'),
                    (10, 1000, 'kpi.view'),
                    (20, 2000, 'kpi.view')
                """
            )
        )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def service(auth_engine):
    return AuthorizationService(auth_engine)


@pytest.fixture()
def identity():
    return VerifiedExternalIdentity(
        identity_provider_code="oidc_dev",
        issuer_url="https://issuer.example.test",
        subject_id="subject-1",
    )


def test_verified_identity_resolves_active_local_user_and_updates_timestamp(service, identity, auth_engine):
    user = service.authenticate_verified_identity(identity)
    assert user.user_id == 1
    assert user.email_normalized == "user1@example.test"
    with auth_engine.connect() as connection:
        last_auth = connection.execute(
            text("SELECT last_authenticated_at_utc FROM user_identities WHERE user_identity_id = 1")
        ).scalar_one()
    assert last_auth is not None


def test_unlinked_external_identity_fails_closed(service):
    unknown = VerifiedExternalIdentity("oidc_dev", "https://issuer.example.test", "unknown")
    with pytest.raises(AuthenticationFailed):
        service.authenticate_verified_identity(unknown)


def test_suspended_user_cannot_authenticate(service):
    suspended = VerifiedExternalIdentity("oidc_dev", "https://issuer.example.test", "subject-2")
    with pytest.raises(AuthenticationFailed):
        service.authenticate_verified_identity(suspended)


def test_membership_listing_only_returns_active_tenants_and_memberships(service, identity):
    user = service.authenticate_verified_identity(identity)
    memberships = service.list_available_tenants(user)
    assert [membership.tenant_id for membership in memberships] == [10, 20]


def test_tenant_context_loads_tenant_specific_roles_and_permissions(service, identity):
    user = service.authenticate_verified_identity(identity)
    context = service.select_tenant(user, 10)
    assert context.tenant_id == 10
    assert context.role_codes == frozenset({"company_admin"})
    assert "tenant.manage" in context.permission_codes


def test_same_user_has_different_permissions_in_another_tenant(service, identity):
    user = service.authenticate_verified_identity(identity)
    airline_context = service.select_tenant(user, 10)
    bank_context = service.select_tenant(user, 20)
    assert "tenant.manage" in airline_context.permission_codes
    assert "tenant.manage" not in bank_context.permission_codes
    assert bank_context.role_codes == frozenset({"viewer"})


def test_disabled_role_does_not_grant_permissions(service, identity):
    user = service.authenticate_verified_identity(identity)
    context = service.select_tenant(user, 20)
    assert "manager" not in context.role_codes
    assert "tenant.manage" not in context.permission_codes


def test_suspended_or_closed_tenant_cannot_be_selected(service, identity):
    user = service.authenticate_verified_identity(identity)
    with pytest.raises(TenantAccessDenied):
        service.select_tenant(user, 30)


def test_unrelated_tenant_cannot_be_selected(service, identity):
    user = service.authenticate_verified_identity(identity)
    with pytest.raises(TenantAccessDenied):
        service.select_tenant(user, 999)


def test_inactive_membership_cannot_be_selected(service, identity, auth_engine):
    with auth_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants VALUES (40, 'pending_tenant', 'Pending', 'active')")
        )
        connection.execute(
            text("INSERT INTO tenant_memberships VALUES (600, 40, 1, 'pending')")
        )
    user = service.authenticate_verified_identity(identity)
    with pytest.raises(TenantAccessDenied):
        service.select_tenant(user, 40)


def test_permission_check_returns_trusted_tenant_id(service, identity):
    user = service.authenticate_verified_identity(identity)
    context = service.select_tenant(user, 10)
    assert service.require_permission(context, "kpi.view") == 10


def test_permission_check_is_exact_and_denial_is_audited(service, identity, auth_engine):
    user = service.authenticate_verified_identity(identity)
    context = service.select_tenant(user, 20)
    with pytest.raises(PermissionDenied):
        service.require_permission(context, "tenant.manage")
    with auth_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT tenant_id, actor_membership_id, action_code,
                       target_reference, outcome_code, event_details_json
                FROM audit_events
                """
            )
        ).mappings().one()
    assert row["tenant_id"] == 20
    assert row["actor_membership_id"] == 200
    assert row["action_code"] == "authorization.permission_denied"
    assert row["target_reference"] == "tenant.manage"
    assert row["outcome_code"] == "denied"


def test_audit_metadata_rejects_secret_like_keys(service, identity):
    user = service.authenticate_verified_identity(identity)
    context = service.select_tenant(user, 10)
    with pytest.raises(ValueError, match="Sensitive audit metadata"):
        service.record_security_event(
            context,
            action_code="membership.invite",
            outcome_code="success",
            target_type="membership",
            event_details={"access_token": "never-log-this"},
        )


def test_invalid_tenant_id_is_rejected(service, identity):
    user = service.authenticate_verified_identity(identity)
    with pytest.raises(ValueError):
        service.select_tenant(user, True)


def test_verified_identity_rejects_invalid_provider_code():
    with pytest.raises(ValueError):
        VerifiedExternalIdentity("OIDC DEV", "https://issuer.example.test", "sub-1")
