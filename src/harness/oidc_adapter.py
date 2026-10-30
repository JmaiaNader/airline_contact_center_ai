"""Strict adapter for Streamlit-validated Google OIDC identity claims.

Streamlit owns the OIDC authorization-code flow and token signature/audience/nonce
validation. This module applies AeroInsight-specific issuer, subject, email-verification,
and time-claim checks. Never pass user-controlled values to this adapter.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.harness.auth_models import VerifiedExternalIdentity
from src.harness.exceptions import AuthenticationFailed
from src.harness.oidc_config import OIDCProviderConfig

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_PROVIDER_CODE = "google_oidc"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MISSING = object()


def _claim(user: object, name: str) -> Any:
    if isinstance(user, Mapping):
        return user.get(name, _MISSING)
    getter = getattr(user, "get", None)
    if callable(getter):
        try:
            return getter(name, _MISSING)
        except (KeyError, TypeError, AttributeError):
            pass
    return getattr(user, name, _MISSING)


def _required_string(user: object, name: str, maximum: int) -> str:
    value = _claim(user, name)
    if not isinstance(value, str):
        raise AuthenticationFailed("Google sign-in could not be verified.")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise AuthenticationFailed("Google sign-in could not be verified.")
    return normalized


@dataclass(frozen=True, slots=True)
class GoogleOIDCProfile:
    """Minimal verified profile; no ID/access token is retained."""

    identity: VerifiedExternalIdentity
    email_normalized: str
    display_name: str
    email_verified: bool
    issued_at: int
    expires_at: int


def google_profile_from_streamlit_user(
    streamlit_user: object,
    *,
    now_epoch: int | None = None,
    clock_skew_seconds: int = 60,
) -> GoogleOIDCProfile:
    """Accept only logged-in, Streamlit-validated Google claims with a live ID token."""
    if _claim(streamlit_user, "is_logged_in") is not True:
        raise AuthenticationFailed("Google sign-in could not be verified.")

    issuer = _required_string(streamlit_user, "iss", 512)
    subject = _required_string(streamlit_user, "sub", 255)
    if issuer != GOOGLE_ISSUER:
        raise AuthenticationFailed("Google sign-in could not be verified.")

    email = _required_string(streamlit_user, "email", 254).lower()
    if not _EMAIL_RE.fullmatch(email):
        raise AuthenticationFailed("Google sign-in could not be verified.")
    if _claim(streamlit_user, "email_verified") is not True:
        raise AuthenticationFailed("A verified Google email address is required.")

    issued_at = _claim(streamlit_user, "iat")
    expires_at = _claim(streamlit_user, "exp")
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, (int, float))
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
    ):
        raise AuthenticationFailed("Google sign-in could not be verified.")
    issued_at = int(issued_at)
    expires_at = int(expires_at)
    now_value = int(time.time()) if now_epoch is None else int(now_epoch)
    if expires_at <= now_value or issued_at > now_value + clock_skew_seconds or expires_at <= issued_at:
        raise AuthenticationFailed("Your Google sign-in session has expired. Please sign in again.")

    raw_name = _claim(streamlit_user, "name")
    display_name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not display_name:
        display_name = email.split("@", 1)[0]
    display_name = display_name[:128]

    return GoogleOIDCProfile(
        identity=VerifiedExternalIdentity(
            identity_provider_code=GOOGLE_PROVIDER_CODE,
            issuer_url=issuer,
            subject_id=subject,
        ),
        email_normalized=email,
        display_name=display_name,
        email_verified=True,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def verified_identity_from_streamlit_user(
    streamlit_user: object,
    providers: tuple[OIDCProviderConfig, ...],
) -> VerifiedExternalIdentity:
    """Backward-compatible generic adapter for already configured providers.

    This function deliberately uses issuer + subject, never email, as the local
    identity key. The production Google path uses google_profile_from_streamlit_user
    for the additional verified-email and ID-token time checks.
    """
    if _claim(streamlit_user, "is_logged_in") is not True:
        raise AuthenticationFailed("Authentication could not be completed.")
    issuer = _required_string(streamlit_user, "iss", 512)
    subject = _required_string(streamlit_user, "sub", 255)
    provider = next((item for item in providers if item.issuer_url == issuer), None)
    if provider is None:
        raise AuthenticationFailed("Authentication could not be completed.")
    return VerifiedExternalIdentity(
        identity_provider_code=provider.identity_provider_code,
        issuer_url=issuer,
        subject_id=subject,
    )
