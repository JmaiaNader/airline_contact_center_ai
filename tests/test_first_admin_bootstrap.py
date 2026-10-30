from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from src.harness.admin_bootstrap import (
    FirstAdminBootstrapError,
    FirstAdminBootstrapRepository,
    FirstAdminBootstrapSettings,
    load_first_admin_bootstrap_settings,
)
from src.harness.auth_models import VerifiedExternalIdentity
from src.harness.oidc_adapter import GoogleOIDCProfile, GOOGLE_ISSUER, GOOGLE_PROVIDER_CODE


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ddl = [
        "CREATE TABLE tenants (tenant_id INTEGER PRIMARY KEY, tenant_code TEXT UNIQUE, display_name TEXT, tenant_status TEXT)",
        "CREATE TABLE users (user_id INTEGER PRIMARY KEY AUTOINCREMENT, email_normalized TEXT UNIQUE, display_name TEXT, user_status TEXT)",
        "CREATE TABLE user_identities (user_identity_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, identity_provider_code TEXT, issuer_url TEXT, subject_id TEXT, provider_email_normalized TEXT, email_verified INTEGER, UNIQUE(issuer_url, subject_id))",
        "CREATE TABLE tenant_memberships (membership_id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER, user_id INTEGER, membership_status TEXT, activated_at_utc TEXT, UNIQUE(tenant_id, user_id))",
        "CREATE TABLE roles (role_id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER, role_code TEXT, role_status TEXT, UNIQUE(tenant_id, role_code))",
        "CREATE TABLE membership_roles (tenant_id INTEGER, membership_id INTEGER, role_id INTEGER, assigned_by_membership_id INTEGER, PRIMARY KEY(tenant_id, membership_id, role_id))",
        "CREATE TABLE audit_events (audit_event_id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER, actor_membership_id INTEGER, action_code TEXT, target_type TEXT, target_reference TEXT, outcome_code TEXT, event_details_json TEXT)",
    ]
    with engine.begin() as connection:
        for statement in ddl:
            connection.execute(text(statement))
        connection.execute(text("INSERT INTO tenants VALUES (1, 'demo_airline', 'Demo Airline', 'active')"))
        connection.execute(text("INSERT INTO roles (tenant_id, role_code, role_status) VALUES (1, 'company_admin', 'active')"))
    return engine


def _profile(email="admin.example@gmail.com"):
    return GoogleOIDCProfile(
        identity=VerifiedExternalIdentity(
            identity_provider_code=GOOGLE_PROVIDER_CODE,
            issuer_url=GOOGLE_ISSUER,
            subject_id="google-subject-123",
        ),
        email_normalized=email,
        display_name="AeroInsight Admin",
        email_verified=True,
        issued_at=1_000,
        expires_at=2_000,
    )


def _settings(email="admin.example@gmail.com"):
    return FirstAdminBootstrapSettings(True, "demo_airline", email)


def test_first_admin_bootstrap_creates_user_identity_membership_role_and_audit_atomically():
    engine = _engine()
    result = FirstAdminBootstrapRepository(engine).provision_first_company_admin(_profile(), _settings())
    assert result["tenant_code"] == "demo_airline"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users WHERE user_status='active'")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM user_identities WHERE email_verified=1")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM tenant_memberships WHERE membership_status='active'")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM membership_roles mr JOIN roles r ON r.role_id=mr.role_id WHERE r.role_code='company_admin'")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM audit_events WHERE action_code='identity.first_admin_bootstrapped'")).scalar_one() == 1
    engine.dispose()


def test_bootstrap_is_one_time_even_if_admin_role_is_later_removed():
    engine = _engine()
    repo = FirstAdminBootstrapRepository(engine)
    repo.provision_first_company_admin(_profile(), _settings())
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM membership_roles"))
    with pytest.raises(FirstAdminBootstrapError, match="already been claimed"):
        repo.provision_first_company_admin(_profile(), _settings())
    engine.dispose()


def test_bootstrap_rejects_email_not_on_local_allowlist_without_database_writes():
    engine = _engine()
    with pytest.raises(FirstAdminBootstrapError, match="not the configured"):
        FirstAdminBootstrapRepository(engine).provision_first_company_admin(
            _profile("other@gmail.com"), _settings()
        )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 0
    engine.dispose()


def test_bootstrap_rejects_missing_or_inactive_company():
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text("UPDATE tenants SET tenant_status='disabled' WHERE tenant_id=1"))
    with pytest.raises(FirstAdminBootstrapError, match="missing or inactive"):
        FirstAdminBootstrapRepository(engine).provision_first_company_admin(_profile(), _settings())
    engine.dispose()


def test_settings_require_explicit_enabled_demo_tenant_and_valid_email():
    loaded = load_first_admin_bootstrap_settings({
        "aeroinsight_bootstrap": {
            "enabled": True,
            "tenant_code": "demo_airline",
            "admin_email": "Admin.Example@gmail.com",
        }
    })
    assert loaded.admin_email_normalized == "admin.example@gmail.com"
    with pytest.raises(FirstAdminBootstrapError):
        load_first_admin_bootstrap_settings({"aeroinsight_bootstrap": {"enabled": False}})


def test_bootstrap_rejects_profile_that_did_not_confirm_verified_email():
    engine = _engine()
    unverified = GoogleOIDCProfile(
        identity=_profile().identity,
        email_normalized="admin.example@gmail.com",
        display_name="AeroInsight Admin",
        email_verified=False,
        issued_at=1_000,
        expires_at=2_000,
    )
    with pytest.raises(FirstAdminBootstrapError, match="verified Google identity"):
        FirstAdminBootstrapRepository(engine).provision_first_company_admin(unverified, _settings())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 0
    engine.dispose()


def test_bootstrap_rejects_non_google_provider_code():
    engine = _engine()
    non_google = GoogleOIDCProfile(
        identity=VerifiedExternalIdentity(
            identity_provider_code="other_oidc",
            issuer_url="https://accounts.google.com",
            subject_id="google-subject-123",
        ),
        email_normalized="admin.example@gmail.com",
        display_name="AeroInsight Admin",
        email_verified=True,
        issued_at=1_000,
        expires_at=2_000,
    )
    with pytest.raises(FirstAdminBootstrapError, match="Only the configured Google"):
        FirstAdminBootstrapRepository(engine).provision_first_company_admin(non_google, _settings())
    engine.dispose()
