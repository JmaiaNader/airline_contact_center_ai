from __future__ import annotations

import pytest

from src.harness.exceptions import AuthenticationFailed
from src.harness.oidc_adapter import (
    GOOGLE_ISSUER,
    GOOGLE_PROVIDER_CODE,
    google_profile_from_streamlit_user,
)


def _claims(**overrides):
    values = {
        "is_logged_in": True,
        "iss": GOOGLE_ISSUER,
        "sub": "google-subject-123",
        "email": "Admin.Example@gmail.com",
        "email_verified": True,
        "name": "AeroInsight Admin",
        "iat": 1_000,
        "exp": 2_000,
    }
    values.update(overrides)
    return values


def test_google_profile_uses_verified_subject_and_normalizes_email():
    profile = google_profile_from_streamlit_user(_claims(), now_epoch=1_200)
    assert profile.identity.identity_provider_code == GOOGLE_PROVIDER_CODE
    assert profile.identity.issuer_url == GOOGLE_ISSUER
    assert profile.identity.subject_id == "google-subject-123"
    assert profile.email_normalized == "admin.example@gmail.com"
    assert profile.display_name == "AeroInsight Admin"
    assert profile.email_verified is True


def test_rejects_unverified_google_email():
    with pytest.raises(AuthenticationFailed):
        google_profile_from_streamlit_user(_claims(email_verified=False), now_epoch=1_200)


def test_rejects_non_google_issuer():
    with pytest.raises(AuthenticationFailed):
        google_profile_from_streamlit_user(_claims(iss="https://attacker.example"), now_epoch=1_200)


def test_rejects_expired_identity_token_claims():
    with pytest.raises(AuthenticationFailed, match="expired"):
        google_profile_from_streamlit_user(_claims(exp=1_100), now_epoch=1_200)


def test_rejects_future_issued_identity_token():
    with pytest.raises(AuthenticationFailed):
        google_profile_from_streamlit_user(_claims(iat=1_300, exp=2_000), now_epoch=1_200)


def test_rejects_unlogged_user():
    with pytest.raises(AuthenticationFailed):
        google_profile_from_streamlit_user(_claims(is_logged_in=False), now_epoch=1_200)
