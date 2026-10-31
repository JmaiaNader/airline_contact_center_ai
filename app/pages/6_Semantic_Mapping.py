from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

from app.authentication import require_authenticated_tenant_context
from src.config.settings import get_settings
from src.database.connection import create_db_engine
from src.discovery.mysql_schema import inspect_database_schema
from src.discovery.semantic_mapping_store import SemanticMappingError, SemanticMappingService

_LOGGER = logging.getLogger(__name__)

st.set_page_config(page_title="Semantic Mapping", page_icon="🧭", layout="wide")
st.title("🧭 AeroInsight — Semantic Mapping")
st.caption("Discover fields, save suggestions, and approve safe exact identifier mappings in one action.")

settings = get_settings()
engine = create_db_engine(settings)

try:
    tenant_context = None
    try:
        tenant_context = require_authenticated_tenant_context()
    except Exception as exc:
        st.error(f"Authentication or tenant authorization is unavailable ({type(exc).__name__}).")
        st.stop()

    if not tenant_context.has_permission("mapping.view"):
        st.error("Your active company role does not grant mapping.view.")
        st.stop()

    st.info(
        f"Company: **{tenant_context.tenant_display_name}** · "
        f"Configured database: `{settings.db_name}` · Time standard: UTC"
    )

    service = SemanticMappingService(engine)

    # Discover metadata automatically on first visit; refresh is available when schema changes.
    refresh_requested = st.button("Refresh database metadata")
    if "semantic_mapping_profile" not in st.session_state or refresh_requested:
        with st.spinner("Reading configured database metadata..."):
            st.session_state["semantic_mapping_profile"] = inspect_database_schema(
                engine,
                schema_name=settings.db_name,
                expected_schema=settings.db_name,
            )

    profile = st.session_state["semantic_mapping_profile"]
    direct_suggestions = [
        (table, column, column.mapping.candidates[0] if column.mapping.candidates else None)
        for table in profile.tables
        for column in table.columns
        if column.mapping.status == "suggested"
    ]

    metric_cols = st.columns(3)
    metric_cols[0].metric("Tables discovered", profile.table_count)
    metric_cols[1].metric("Columns discovered", profile.column_count)
    metric_cols[2].metric("Direct suggestions", len(direct_suggestions))

    with st.expander("Discovery preview", expanded=False):
        preview_rows = []
        for table in profile.tables:
            for column in table.columns:
                top = column.mapping.candidates[0] if column.mapping.candidates else None
                preview_rows.append(
                    {
                        "table": column.table_name,
                        "column": column.column_name,
                        "type": column.inferred_type,
                        "primary_key": column.is_primary_key,
                        "status": column.mapping.status,
                        "suggested_concept": top.concept_key if top else None,
                        "fit_score": top.fit_score if top else None,
                        "type_compatible": top.type_compatible if top else None,
                    }
                )
        st.dataframe(preview_rows, use_container_width=True, hide_index=True)

    st.subheader("Save suggestions & approve safe exact matches")
    st.caption(
        "One action saves the current discovery results and approves only exact, unambiguous, "
        "type-compatible Contact Reference matches whose source column is a non-null primary key. "
        "KPI mappings (CSAT, NPS, AHT, SLA, Offered, Handled) and all ambiguous/partial matches "
        "remain pending; their formulas, units, populations and time grains are not inferred."
    )

    sources = service.list_sources(tenant_context)
    if not sources:
        st.warning("No active source is registered for this company in db_airlines.")
    else:
        source_by_id = {item.source_system_id: item for item in sources}
        source_id = st.selectbox(
            "Source",
            options=list(source_by_id),
            format_func=lambda key: f"{source_by_id[key].display_name} ({source_by_id[key].source_code})",
        )

        can_save = tenant_context.has_permission("mapping.review")
        can_approve = tenant_context.has_permission("mapping.approve")
        if can_save and can_approve:
            if st.button("Save & approve safe exact matches", type="primary", use_container_width=True):
                try:
                    with st.spinner("Saving suggestions and approving eligible exact identifier mappings..."):
                        result = service.save_and_approve_safe_exact_matches(
                            tenant_context,
                            source_system_id=int(source_id),
                            profile=profile,
                        )
                    st.success(
                        f"Saved/checked {result['saved_count']} field suggestions. "
                        f"Approved {result['approved_count']} safe exact identifier mappings. "
                        f"{result['pending_count']} business or ambiguous mappings remain pending."
                    )
                    st.rerun()
                except Exception as exc:
                    _LOGGER.exception("One-action semantic mapping persistence/approval failed")
                    st.error(f"Could not complete mapping save/approval ({type(exc).__name__}): {exc}")
        else:
            st.warning(
                "This action requires both mapping.review and mapping.approve for the active company."
            )

        records = service.list_current_mappings(tenant_context, source_system_id=int(source_id))
        if records:
            statuses: dict[str, int] = {}
            for item in records:
                status = str(item.get("mapping_status") or "unknown")
                statuses[status] = statuses.get(status, 0) + 1
            st.subheader("Current persisted mappings")
            status_cols = st.columns(min(4, max(1, len(statuses))))
            for index, (status, count) in enumerate(sorted(statuses.items())):
                status_cols[index % len(status_cols)].metric(status.replace("_", " ").title(), count)
            st.dataframe(
                [
                    {
                        "table": item["source_table_name"],
                        "column": item["source_column_name"],
                        "status": item["mapping_status"],
                        "concept": item.get("selected_concept_key") or item.get("suggested_concept_key"),
                        "score": item.get("fit_score"),
                        "version": item["mapping_version"],
                        "reviewed_at_utc": item.get("reviewed_at_utc"),
                    }
                    for item in records
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No persisted suggestions yet. Use the one-action button above.")

    st.caption(
        "Approval is tenant-scoped and requires the authenticated Company Admin's mapping.review "
        "and mapping.approve permissions. Each approval and audit event is persisted in db_airlines. "
        "No source business rows are read."
    )
finally:
    engine.dispose()
