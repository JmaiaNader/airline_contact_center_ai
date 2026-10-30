from __future__ import annotations

import pytest

from src.harness.auth_models import VerifiedExternalIdentity
from src.harness.exceptions import AuthenticationFailed
from src.harness.oidc_adapter import verified_identity_from_streamlit_user
from src.harness.oidc_config import (
    OIDCConfigurationError,
    OIDCProviderConfig,
    load_oidc_provider_configs,
)


def _secrets():
    return {
        "auth": {
            "redirect_uri": "http://localhost:8501/oauth2callback",
            "cookie_secret": "unit-test-only-secret",
            "google": {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            },
        },
        "aeroinsight_oidc": {
            "providers": {
                "google": {
                    "identity_provider_code": "google_oidc",
                    "issuer_url": "https://accounts.google.com",
                    "button_label": "Continue with Google",
                }
            }
        },
    }


def test_loads_named_provider_and_exact_issuer():
    providers = load_oidc_provider_configs(_secrets())
    assert len(providers) == 1
    assert providers[0] == OIDCProviderConfig(
        streamlit_provider_name="google",
        identity_provider_code="google_oidc",
        issuer_url="https://accounts.google.com",
        button_label="Continue with Google",
    )


def test_rejects_provider_missing_streamlit_auth_section():
    secrets = _secrets()
    del secrets["auth"]["google"]
    with pytest.raises(OIDCConfigurationError):
        load_oidc_provider_configs(secrets)


def test_rejects_http_non_loopback_issuer():
    secrets = _secrets()
    secrets["aeroinsight_oidc"]["providers"]["google"]["issuer_url"] = "http://example.com"
    with pytest.raises(OIDCConfigurationError):
        load_oidc_provider_configs(secrets)


def test_rejects_duplicate_identity_provider_codes():
    secrets = _secrets()
    secrets["auth"]["microsoft"] = {"client_id": "x"}
    secrets["aeroinsight_oidc"]["providers"]["microsoft"] = {
        "identity_provider_code": "google_oidc",
        "issuer_url": "https://login.example.com/tenant/v2.0",
        "button_label": "Continue with Microsoft",
    }
    with pytest.raises(OIDCConfigurationError):
        load_oidc_provider_configs(secrets)


def test_builds_identity_from_streamlit_verified_user_without_using_email():
    providers = load_oidc_provider_configs(_secrets())
    identity = verified_identity_from_streamlit_user(
        {
            "is_logged_in": True,
            "iss": "https://accounts.google.com",
            "sub": "stable-subject-123",
            "email": "person@example.test",
        },
        providers,
    )
    assert isinstance(identity, VerifiedExternalIdentity)
    assert identity.identity_provider_code == "google_oidc"
    assert identity.issuer_url == "https://accounts.google.com"
    assert identity.subject_id == "stable-subject-123"


def test_rejects_unmapped_issuer():
    providers = load_oidc_provider_configs(_secrets())
    with pytest.raises(AuthenticationFailed):
        verified_identity_from_streamlit_user(
            {"is_logged_in": True, "iss": "https://evil.example", "sub": "123"},
            providers,
        )


def test_rejects_missing_subject():
    providers = load_oidc_provider_configs(_secrets())
    with pytest.raises(AuthenticationFailed):
        verified_identity_from_streamlit_user(
            {"is_logged_in": True, "iss": "https://accounts.google.com"},
            providers,
        )


def test_rejects_non_logged_in_user():
    providers = load_oidc_provider_configs(_secrets())
    with pytest.raises(AuthenticationFailed):
        verified_identity_from_streamlit_user(
            {"is_logged_in": False, "iss": "https://accounts.google.com", "sub": "123"},
            providers,
        )


def test_supports_multiple_named_oidc_providers():
    secrets = _secrets()
    secrets["auth"]["microsoft"] = {
        "client_id": "entra-client",
        "client_secret": "entra-secret",
        "server_metadata_url": "https://login.microsoftonline.com/example/v2.0/.well-known/openid-configuration",
    }
    secrets["aeroinsight_oidc"]["providers"]["microsoft"] = {
        "identity_provider_code": "microsoft_entra",
        "issuer_url": "https://login.microsoftonline.com/example/v2.0",
        "button_label": "Continue with Microsoft",
    }
    providers = load_oidc_provider_configs(secrets)
    assert {provider.streamlit_provider_name for provider in providers} == {"google", "microsoft"}
