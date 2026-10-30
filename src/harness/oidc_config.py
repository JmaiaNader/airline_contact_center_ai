"""Validated configuration for Streamlit-managed OIDC providers.

Streamlit performs the OIDC protocol flow and validates the ID token. This module
only validates the application's allow-list that maps a named Streamlit provider
to the issuer and identity_provider_code stored in AeroInsight's database.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

_PROVIDER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_PROVIDER_CODE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class OIDCConfigurationError(ValueError):
    """Raised when OIDC provider configuration is absent or unsafe."""


@dataclass(frozen=True, slots=True)
class OIDCProviderConfig:
    streamlit_provider_name: str
    identity_provider_code: str
    issuer_url: str
    button_label: str


def _as_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OIDCConfigurationError(f"{name} must be a TOML table.")
    return value


def _validate_issuer(issuer_url: object, provider_name: str) -> str:
    if not isinstance(issuer_url, str) or not issuer_url or issuer_url != issuer_url.strip():
        raise OIDCConfigurationError(
            f"Provider {provider_name!r} must have an exact issuer_url string."
        )
    parsed = urlparse(issuer_url)
    is_https = parsed.scheme == "https" and bool(parsed.netloc)
    is_local_http = (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and parsed.port is not None
    )
    if not (is_https or is_local_http):
        raise OIDCConfigurationError(
            f"Provider {provider_name!r} issuer_url must use HTTPS "
            "(HTTP is allowed only for an explicit localhost development issuer)."
        )
    if parsed.query or parsed.fragment:
        raise OIDCConfigurationError("issuer_url cannot contain a query or fragment.")
    return issuer_url


def load_oidc_provider_configs(
    secrets: Mapping[str, object],
) -> tuple[OIDCProviderConfig, ...]:
    """Load a strict allow-list and ensure every provider has Streamlit auth config.

    Expected shape:
      [auth.google] ...
      [aeroinsight_oidc.providers.google]
      identity_provider_code = "google_oidc"
      issuer_url = "https://accounts.google.com"
      button_label = "Continue with Google"
    """
    auth = _as_mapping(secrets.get("auth"), "[auth]")
    aeroinsight = _as_mapping(
        secrets.get("aeroinsight_oidc"), "[aeroinsight_oidc]"
    )
    provider_tables = _as_mapping(
        aeroinsight.get("providers"), "[aeroinsight_oidc.providers]"
    )
    if not provider_tables:
        raise OIDCConfigurationError("No OIDC providers are configured.")

    missing_shared = {"redirect_uri", "cookie_secret"}.difference(auth)
    if missing_shared:
        raise OIDCConfigurationError(
            "[auth] is missing required settings: " + ", ".join(sorted(missing_shared))
        )

    configs: list[OIDCProviderConfig] = []
    seen_codes: set[str] = set()
    seen_issuers: set[str] = set()

    for provider_name, raw_spec in provider_tables.items():
        if not isinstance(provider_name, str) or not _PROVIDER_NAME.fullmatch(provider_name):
            raise OIDCConfigurationError("An OIDC provider name has an invalid format.")
        if provider_name not in auth:
            raise OIDCConfigurationError(
                f"Provider {provider_name!r} is missing its [auth.{provider_name}] settings."
            )
        auth_provider = _as_mapping(auth[provider_name], f"[auth.{provider_name}]")
        missing_provider_settings = {"client_id", "client_secret", "server_metadata_url"}.difference(auth_provider)
        if missing_provider_settings:
            raise OIDCConfigurationError(
                f"[auth.{provider_name}] is missing required settings: "
                + ", ".join(sorted(missing_provider_settings))
            )
        spec = _as_mapping(
            raw_spec, f"[aeroinsight_oidc.providers.{provider_name}]"
        )

        code = spec.get("identity_provider_code")
        if not isinstance(code, str) or not _PROVIDER_CODE.fullmatch(code):
            raise OIDCConfigurationError(
                f"Provider {provider_name!r} has an invalid identity_provider_code."
            )
        if code in seen_codes:
            raise OIDCConfigurationError("identity_provider_code values must be unique.")

        issuer = _validate_issuer(spec.get("issuer_url"), provider_name)
        if issuer in seen_issuers:
            raise OIDCConfigurationError("OIDC issuer_url values must be unique.")

        label = spec.get("button_label", f"Continue with {provider_name}")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise OIDCConfigurationError(
                f"Provider {provider_name!r} has an invalid button_label."
            )

        seen_codes.add(code)
        seen_issuers.add(issuer)
        configs.append(
            OIDCProviderConfig(
                streamlit_provider_name=provider_name,
                identity_provider_code=code,
                issuer_url=issuer,
                button_label=label.strip(),
            )
        )

    return tuple(sorted(configs, key=lambda item: item.streamlit_provider_name))
