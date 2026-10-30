"""Google OIDC login, one-time first-admin bootstrap and tenant RBAC context."""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import get_settings
from src.database.connection import create_db_engine
from src.harness.admin_bootstrap import (
    FirstAdminBootstrapError,
    FirstAdminBootstrapRepository,
    load_first_admin_bootstrap_settings,
)
from src.harness.authorization_service import AuthorizationService
from src.harness.auth_models import AuthenticatedTenantContext
from src.harness.exceptions import AuthenticationFailed, TenantAccessDenied
from src.harness.oidc_adapter import (
    GOOGLE_ISSUER,
    GOOGLE_PROVIDER_CODE,
    google_profile_from_streamlit_user,
)
from src.harness.oidc_config import OIDCConfigurationError, load_oidc_provider_configs


@st.cache_resource(show_spinner=False)
def _get_engine():
    """One pooled SQLAlchemy engine for the local Streamlit process."""
    return create_db_engine(get_settings())


@st.cache_resource(show_spinner=False)
def _get_authorization_service() -> AuthorizationService:
    return AuthorizationService(_get_engine())


def _require_google_provider(secrets: Mapping[str, object]):
    providers = load_oidc_provider_configs(secrets)
    auth_section = secrets.get("auth")
    google_auth = auth_section.get("google") if isinstance(auth_section, Mapping) else None
    metadata_url = google_auth.get("server_metadata_url") if isinstance(google_auth, Mapping) else None
    if metadata_url != "https://accounts.google.com/.well-known/openid-configuration":
        raise OIDCConfigurationError("Google server_metadata_url must use Google's official discovery endpoint.")
    google = next(
        (
            item for item in providers
            if item.streamlit_provider_name == "google"
            and item.identity_provider_code == GOOGLE_PROVIDER_CODE
            and item.issuer_url == GOOGLE_ISSUER
        ),
        None,
    )
    if google is None:
        raise OIDCConfigurationError(
            "Configure the named Google provider in [auth.google] and "
            "[aeroinsight_oidc.providers.google]."
        )
    return google


def _show_google_login(google_provider) -> None:
    st.title("AeroInsight")
    st.subheader("Sign in with Google")
    st.caption("Your verified Google identity will be linked to your AeroInsight company membership.")
    if st.button("Continue with Google", type="primary", use_container_width=True):
        st.login(google_provider.streamlit_provider_name)
    st.stop()


def _show_sign_out() -> None:
    if st.sidebar.button("Sign out", key="aeroinsight_sign_out"):
        st.logout()
        st.stop()


def require_authenticated_tenant_context() -> AuthenticatedTenantContext:
    """Require verified Google OIDC, a local account, active tenant membership and RBAC.

    The only automatic account creation path is the one-time, verified-email allow-list
    bootstrap for demo_airline. Once any Company Admin has been assigned, the DB row lock
    and role check permanently close the bootstrap path.
    """
    if not hasattr(st, "login") or not hasattr(st, "user"):
        st.error("AeroInsight authentication requires Streamlit 1.45+ with its auth extra.")
        st.stop()

    try:
        google_provider = _require_google_provider(st.secrets)
    except (OIDCConfigurationError, KeyError, TypeError) as exc:
        st.error("Google OIDC is not configured.")
        st.caption(str(exc))
        st.info("Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and follow docs/google_oidc_first_admin_v1.md.")
        st.stop()

    streamlit_user = st.user
    if getattr(streamlit_user, "is_logged_in", False) is not True:
        _show_google_login(google_provider)

    try:
        profile = google_profile_from_streamlit_user(streamlit_user)
    except AuthenticationFailed as exc:
        st.error(str(exc))
        st.warning("Please sign out and sign in again with the configured Google account.")
        _show_sign_out()
        st.stop()

    service = _get_authorization_service()
    bootstrap_completed = False
    bootstrap_settings = None

    def try_first_admin_bootstrap():
        nonlocal bootstrap_settings
        if bootstrap_settings is None:
            bootstrap_settings = load_first_admin_bootstrap_settings(st.secrets)
        if profile.email_normalized != bootstrap_settings.admin_email_normalized:
            raise FirstAdminBootstrapError(
                "This Google account is not the configured first-admin account."
            )
        return FirstAdminBootstrapRepository(_get_engine()).provision_first_company_admin(
            profile, bootstrap_settings
        )

    try:
        user = service.authenticate_verified_identity(profile.identity)
    except SQLAlchemyError:
        st.error("AeroInsight could not verify your Google identity against db_airlines.")
        _show_sign_out()
        st.stop()
    except AuthenticationFailed:
        try:
            try_first_admin_bootstrap()
            bootstrap_completed = True
            user = service.authenticate_verified_identity(profile.identity)
        except FirstAdminBootstrapError as exc:
            st.error("This Google account is not provisioned for AeroInsight access.")
            st.caption(str(exc))
            st.info("The first-admin bootstrap is one-time and restricted to the verified email configured locally.")
            _show_sign_out()
            st.stop()
        except SQLAlchemyError:
            st.error("First-admin provisioning could not be completed against db_airlines.")
            _show_sign_out()
            st.stop()

    try:
        memberships = service.list_available_tenants(user)
    except SQLAlchemyError:
        st.error("AeroInsight could not load your company memberships from db_airlines.")
        _show_sign_out()
        st.stop()

    # If the identity was previously linked but the demo_airline membership is still
    # pending/missing, allow only the configured verified Google admin to complete the
    # same one-time bootstrap. The DB transaction and durable audit marker prevent reuse.
    try:
        if bootstrap_settings is None:
            bootstrap_settings = load_first_admin_bootstrap_settings(st.secrets)
        has_target_membership = any(
            item.tenant_code == bootstrap_settings.tenant_code for item in memberships
        )
        if (
            not has_target_membership
            and profile.email_normalized == bootstrap_settings.admin_email_normalized
        ):
            try_first_admin_bootstrap()
            bootstrap_completed = True
            user = service.authenticate_verified_identity(profile.identity)
            memberships = service.list_available_tenants(user)
    except FirstAdminBootstrapError:
        # Existing memberships in other tenants remain valid; this user simply cannot
        # claim the already-provisioned demo tenant through bootstrap.
        pass
    except Exception:
        # Bootstrap configuration is required only for the first administrator. It
        # must not block normal sign-in for already-provisioned users.
        pass

    if not memberships:
        st.error("Your Google identity has no active company membership.")
        _show_sign_out()
        st.stop()

    by_id = {item.tenant_id: item for item in memberships}
    tenant_ids = list(by_id)
    selected = st.sidebar.selectbox(
        "Active company",
        options=tenant_ids,
        format_func=lambda tenant_id: by_id[tenant_id].tenant_display_name,
        key="aeroinsight_active_tenant_id",
    )
    try:
        context = service.select_tenant(user, int(selected))
    except TenantAccessDenied:
        st.error("You do not have an active membership in the selected company.")
        _show_sign_out()
        st.stop()

    if bootstrap_completed:
        st.sidebar.success("First Company Admin access created for demo_airline.")
    st.sidebar.caption(f"Signed in: {context.display_name}")
    st.sidebar.caption(f"Company: {context.tenant_display_name}")
    st.sidebar.caption("Roles: " + (", ".join(sorted(context.role_codes)) or "None"))
    _show_sign_out()
    return context
