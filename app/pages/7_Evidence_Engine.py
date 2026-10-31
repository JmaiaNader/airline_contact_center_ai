from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

from src.config.settings import get_settings
from src.database.connection import create_db_engine
from src.discovery.semantic_mapping_store import SemanticMappingError, SemanticMappingService
from src.evidence.readiness import build_readiness_report, export_approved_mappings_csv

st.set_page_config(page_title="Evidence Engine", page_icon="🧾", layout="wide")
st.title("🧾 AeroInsight — Evidence Engine")
st.caption("Stage 1 · Approved semantic coverage · Tenant-scoped · Metadata-only")
st.info(
    "This first Evidence Engine stage checks whether core concepts have approved mappings. "
    "It does not read customer/contact rows or calculate KPIs yet."
)

if not getattr(getattr(st, "user", None), "is_logged_in", False):
    st.warning("Sign in with Google to view company-scoped evidence readiness.")
    from app.authentication import require_authenticated_tenant_context
    require_authenticated_tenant_context()

from app.authentication import require_authenticated_tenant_context

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("mapping.view"):
    st.error("Your active company membership does not grant mapping.view.")
    st.stop()

settings = get_settings()
engine = create_db_engine(settings)
try:
    service = SemanticMappingService(engine)
    try:
        sources = service.list_sources(tenant_context)
    except Exception as exc:
        st.error(f"Could not load registered sources ({type(exc).__name__}).")
        sources = ()

    if not sources:
        st.warning("No active source is registered for the selected company.")
        st.stop()

    source_by_id = {item.source_system_id: item for item in sources}
    source_id = st.selectbox(
        "Company data source",
        options=list(source_by_id),
        format_func=lambda key: (
            f"{source_by_id[key].display_name} ({source_by_id[key].source_code})"
        ),
    )

    try:
        records = service.list_current_mappings(
            tenant_context, source_system_id=int(source_id)
        )
    except SemanticMappingError as exc:
        st.error(str(exc))
        st.stop()

    report = build_readiness_report(records)
    st.subheader(f"Evidence readiness — {tenant_context.tenant_display_name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current mappings", report.total_mappings)
    c2.metric("Approved mappings", report.approved_mappings)
    c3.metric("Pending review", report.pending_mappings)
    c4.metric("Rejected", report.rejected_mappings)

    if report.invalid_approval_records:
        st.warning(
            f"{report.invalid_approval_records} record(s) marked approved did not pass the "
            "Evidence Engine's completeness checks. They are excluded from readiness."
        )

    st.subheader("1. Core contact-centre concept coverage")
    metric_rows = [
        {
            "Metric / capability": item.display_name,
            "Status": item.status,
            "Required concepts": ", ".join(item.required_concepts),
            "Approved concepts found": ", ".join(item.mapped_concepts) or "—",
            "Missing concepts": ", ".join(item.missing_concepts) or "—",
        }
        for item in report.metric_readiness
    ]
    st.dataframe(metric_rows, use_container_width=True, hide_index=True)

    st.subheader("2. Approved field lineage")
    if report.approved_bindings:
        binding_rows = [
            {
                "Table": item.source_table,
                "Column": item.source_column,
                "Canonical concept": item.concept_key,
                "Mapping version": item.mapping_version,
                "Reviewed at (UTC)": item.reviewed_at_utc,
                "Mapping ID": item.mapping_id,
            }
            for item in report.approved_bindings
        ]
        st.dataframe(binding_rows, use_container_width=True, hide_index=True)
        st.download_button(
            "Export approved mapping lineage (CSV)",
            data=export_approved_mappings_csv(report.approved_bindings),
            file_name=f"{tenant_context.tenant_code}_approved_mapping_lineage.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "No approved mappings are available for this source yet. Visit Semantic Mapping, "
            "save the generated suggestions, then approve valid candidates with the required evidence."
        )

    st.subheader("3. What this report does — and does not — prove")
    st.success(
        "A concept is counted only when a current mapping is approved and has a selected concept, "
        "review timestamp and non-empty review evidence."
    )
    st.warning(
        "Mapping completeness is not the same as analytical readiness. Before calculating a KPI, "
        "AeroInsight must also validate source-row availability, grain, units, time zone, population, "
        "formula, denominator and data quality. No KPI value is calculated on this page."
    )
finally:
    engine.dispose()
