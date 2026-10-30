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
from src.discovery.mysql_schema import inspect_database_schema
from src.discovery.semantic_mapping_store import SemanticMappingError, SemanticMappingService

st.set_page_config(page_title="Semantic Mapping", page_icon="🧭", layout="wide")
st.title("🧭 AeroInsight — Semantic Mapping & Approval")
st.caption("Stage 3 · Deterministic suggestions · Tenant-scoped review · Versioned approvals")

settings = get_settings()
st.info(
    f"Development schema: `{settings.db_name}`. This page reads schema metadata only; "
    "it does not read contact/customer rows or send source data to an LLM."
)

# A logged-in identity is accepted only through the server-side OIDC + authorization flow.
# Without that verified context, this page remains preview-only. It never trusts a tenant_id
# supplied by a browser widget or session-state value.
tenant_context = None
if getattr(getattr(st, "user", None), "is_logged_in", False):
    try:
        from app.authentication import require_authenticated_tenant_context

        tenant_context = require_authenticated_tenant_context()
    except ImportError:
        tenant_context = None

engine = create_db_engine(settings)
try:
    with st.expander("Governed semantic catalog", expanded=False):
        st.caption("The canonical catalog is persisted and versioned in db_airlines after Migration 004.")
        from sqlalchemy import text

        with engine.connect() as connection:
            concept_rows = connection.execute(
                text(
                    """
                    SELECT c.concept_key, c.concept_version, c.display_name,
                           c.expected_types_json, c.required_approval_fields_json
                    FROM semantic_concepts c
                    JOIN (
                        SELECT concept_key, MAX(concept_version) AS latest_version
                        FROM semantic_concepts
                        WHERE concept_status = 'active'
                        GROUP BY concept_key
                    ) latest
                      ON latest.concept_key = c.concept_key
                     AND latest.latest_version = c.concept_version
                    ORDER BY c.display_name
                    """
                )
            ).mappings().all()
        st.dataframe(
            [
                {
                    "concept_key": item["concept_key"],
                    "version": item["concept_version"],
                    "display_name": item["display_name"],
                    "expected_types": item["expected_types_json"],
                    "required_approval_fields": item["required_approval_fields_json"],
                }
                for item in concept_rows
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("1. Inspect configured database metadata")
    if st.button("Inspect schema and generate suggestions", type="primary"):
        try:
            with st.spinner("Inspecting database metadata..."):
                st.session_state["semantic_mapping_profile"] = inspect_database_schema(
                    engine,
                    schema_name=settings.db_name,
                    expected_schema=settings.db_name,
                )
            st.success("Schema inspection completed. Suggestions are heuristic and require human review.")
        except Exception as exc:
            st.error(
                f"Schema inspection failed ({type(exc).__name__}). "
                "Check the local database configuration and connectivity."
            )

    profile = st.session_state.get("semantic_mapping_profile")
    if profile is not None:
        summary_left, summary_middle, summary_right = st.columns(3)
        summary_left.metric("Tables", profile.table_count)
        summary_middle.metric("Columns", profile.column_count)
        suggested_count = sum(
            1 for table in profile.tables for column in table.columns
            if column.mapping.status == "suggested"
        )
        summary_right.metric("Direct suggestions", suggested_count)

        suggestion_rows = []
        for table in profile.tables:
            for column in table.columns:
                candidates = column.mapping.candidates
                top = candidates[0] if candidates else None
                suggestion_rows.append(
                    {
                        "table": column.table_name,
                        "column": column.column_name,
                        "type": column.inferred_type,
                        "status": column.mapping.status,
                        "suggested_concept": top.concept_key if top else None,
                        "fit_score": top.fit_score if top else None,
                        "type_compatible": top.type_compatible if top else None,
                        "rationale": " | ".join(top.rationale) if top else "No catalog match",
                    }
                )
        st.subheader("2. Review deterministic suggestions")
        st.caption(
            "Fit scores are ranking heuristics, not probabilities. Similar names do not prove "
            "equivalent definitions, scales, populations, time windows or formulas."
        )
        st.dataframe(suggestion_rows, use_container_width=True, hide_index=True)

        st.subheader("3. Persist suggestions and approve mappings")
        if tenant_context is None:
            st.warning(
                "Preview-only mode. Saving and approving mappings requires a verified OIDC login, "
                "an active membership in the selected company, and mapping.review / mapping.approve permissions. "
                "No tenant ID is accepted from the UI."
            )
        else:
            service = SemanticMappingService(engine)
            if not tenant_context.has_permission("mapping.view"):
                st.warning("Your active company membership does not grant mapping.view.")
            else:
                try:
                    sources = service.list_sources(tenant_context)
                except Exception as exc:
                    st.error(f"Could not load company sources ({type(exc).__name__}).")
                    sources = ()
                if not sources:
                    st.warning("No active data source is registered for this company.")
                else:
                    source_by_id = {item.source_system_id: item for item in sources}
                    source_id = st.selectbox(
                        "Registered source",
                        options=list(source_by_id),
                        format_func=lambda key: (
                            f"{source_by_id[key].display_name} ({source_by_id[key].source_code})"
                        ),
                    )
                    if tenant_context.has_permission("mapping.review"):
                        if st.button("Save current suggestions for this source"):
                            try:
                                summary = service.save_suggestions(
                                    tenant_context,
                                    source_system_id=int(source_id),
                                    profile=profile,
                                )
                                st.success(
                                    f"Saved {summary.saved_count} versioned field suggestions "
                                    f"for tenant {tenant_context.tenant_code}. No mapping was approved."
                                )
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not save suggestions ({type(exc).__name__}).")
                    else:
                        st.info("You have mapping.view but not mapping.review; suggestions cannot be saved.")

                    try:
                        records = service.list_current_mappings(
                            tenant_context, source_system_id=int(source_id)
                        )
                    except Exception:
                        records = ()
                    st.markdown("**Current mapping records**")
                    st.dataframe(
                        [
                            {
                                "mapping_id": item["mapping_id"],
                                "table": item["source_table_name"],
                                "column": item["source_column_name"],
                                "version": item["mapping_version"],
                                "status": item["mapping_status"],
                                "suggested_concept": item["suggested_concept_key"],
                                "selected_concept": item["selected_concept_key"],
                            }
                            for item in records
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

                    if tenant_context.has_permission("mapping.approve"):
                        reviewable = [
                            item for item in records
                            if item["mapping_status"] in {"suggested", "ambiguous"}
                        ]
                        if reviewable:
                            labels = {
                                int(item["mapping_id"]): (
                                    f"{item['source_table_name']}.{item['source_column_name']} "
                                    f"— {item['mapping_status']} (v{item['mapping_version']})"
                                )
                                for item in reviewable
                            }
                            mapping_id = st.selectbox(
                                "Mapping to review",
                                options=list(labels),
                                format_func=lambda key: labels[key],
                            )
                            selected_record = next(
                                item for item in reviewable if int(item["mapping_id"]) == mapping_id
                            )
                            candidates = (
                                selected_record["candidate_details_json"] or {}
                            ).get("candidates", [])
                            compatible = [item for item in candidates if item.get("type_compatible") is True]
                            if compatible:
                                candidate_by_key = {item["concept_key"]: item for item in compatible}
                                concept_key = st.selectbox(
                                    "Choose the concept after reviewing its meaning",
                                    options=list(candidate_by_key),
                                    format_func=lambda key: candidate_by_key[key]["display_name"],
                                )
                                evidence: dict[str, object] = {}
                                st.markdown("**Confirm business semantics**")
                                required_fields = service.get_concept_approval_fields(
                                    tenant_context, concept_key=concept_key
                                )
                                for required_field in required_fields:
                                    label = required_field.replace("_", " ").title()
                                    if required_field == "privacy_review":
                                        evidence[required_field] = st.checkbox(
                                            f"{label} completed", key=f"mapping_{mapping_id}_{required_field}"
                                        )
                                    else:
                                        evidence[required_field] = st.text_area(
                                            label,
                                            key=f"mapping_{mapping_id}_{required_field}",
                                            height=70,
                                        )
                                col_approve, col_reject = st.columns(2)
                                with col_approve:
                                    if st.button("Approve mapping", type="primary"):
                                        try:
                                            service.review_mapping(
                                                tenant_context,
                                                mapping_id=int(mapping_id),
                                                decision="approve",
                                                selected_concept_key=concept_key,
                                                review_evidence=evidence,
                                            )
                                            st.success("Mapping approved and audit event recorded.")
                                            st.rerun()
                                        except SemanticMappingError as exc:
                                            st.error(str(exc))
                                        except Exception as exc:
                                            st.error(f"Approval failed ({type(exc).__name__}).")
                                with col_reject:
                                    rejection_reason = st.text_input(
                                        "Rejection reason", key=f"mapping_{mapping_id}_rejection"
                                    )
                                    if st.button("Reject mapping"):
                                        try:
                                            service.review_mapping(
                                                tenant_context,
                                                mapping_id=int(mapping_id),
                                                decision="reject",
                                                rejection_reason=rejection_reason,
                                            )
                                            st.success("Mapping rejected and audit event recorded.")
                                            st.rerun()
                                        except SemanticMappingError as exc:
                                            st.error(str(exc))
                                        except Exception as exc:
                                            st.error(f"Rejection failed ({type(exc).__name__}).")
                            else:
                                st.info("No type-compatible candidate is available for approval.")

    st.divider()
    st.caption(
        "Engine boundary: metadata and governed definitions only. Mapping is versioned per tenant/source/field. "
        "Approval requires mapping.approve and records reviewer membership plus an audit event in the same transaction."
    )
finally:
    engine.dispose()
