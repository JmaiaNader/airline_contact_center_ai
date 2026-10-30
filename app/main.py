from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.authentication import require_authenticated_tenant_context
from src.config.settings import get_settings

settings = get_settings()
st.set_page_config(
    page_title=settings.app_name,
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

tenant_context = require_authenticated_tenant_context()

st.title("✈️ AeroInsight — Evidence & Decision Engine")
st.caption("Multi-company analytics · Verified identity · Evidence-led decisions")
st.success(
    f"Welcome, {tenant_context.display_name}. "
    f"Active company: {tenant_context.tenant_display_name}."
)
if "company_admin" in tenant_context.role_codes:
    st.info("Company Admin access is active for this company.")

left, right = st.columns(2)
with left:
    st.subheader("Engine workflow")
    st.markdown(
        "1. Discover source metadata\n"
        "2. Map source fields to governed business concepts\n"
        "3. Review and approve mappings\n"
        "4. Build evidence-backed analytics"
    )
with right:
    st.subheader("Current access")
    st.write({
        "tenant": tenant_context.tenant_code,
        "roles": sorted(tenant_context.role_codes),
        "mapping_view": tenant_context.has_permission("mapping.view"),
        "mapping_review": tenant_context.has_permission("mapping.review"),
        "mapping_approve": tenant_context.has_permission("mapping.approve"),
    })

st.divider()
st.caption(f"Environment: {settings.app_env} · Database: {settings.db_name} · DB timestamps: UTC")
