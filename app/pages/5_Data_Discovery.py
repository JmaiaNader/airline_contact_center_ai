from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.authentication import require_authenticated_tenant_context
from src.config.settings import get_settings
from src.database.connection import create_db_engine
from src.discovery.mysql_schema import inspect_database_schema

st.set_page_config(page_title="Data Discovery Engine", page_icon="🔎", layout="wide")
st.title("🔎 AeroInsight — Data Discovery Engine")
st.caption("Stage 2 · Read-only MySQL schema discovery · Deterministic mapping suggestions")

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("data_source.view"):
    st.error("Your active company role does not grant data_source.view.")
    st.stop()

settings = get_settings()
st.info(
    f"Company: `{tenant_context.tenant_code}`. This page inspects the configured MySQL schema `db_airlines` metadata only. "
    "It does not read customer/passenger rows, create tables, update data, or send data to an LLM."
)

st.subheader("Configured database")
left, right = st.columns(2)
left.metric("Database schema", settings.db_name)
right.metric("Database host", settings.db_host)

if "discovery_schema_profile" not in st.session_state:
    st.session_state["discovery_schema_profile"] = None

if st.button("Inspect database schema", type="primary"):
    engine = None
    try:
        engine = create_db_engine(settings)
        with st.spinner("Reading schema metadata from db_airlines..."):
            profile = inspect_database_schema(
                engine,
                schema_name=settings.db_name,
                expected_schema=settings.db_name,
            )
        st.session_state["discovery_schema_profile"] = profile
        st.success("Schema metadata inspection completed.")
    except Exception as exc:  # Do not render connection strings or secret-bearing errors.
        st.error(f"Schema inspection failed ({type(exc).__name__}). Check the local DB configuration and connectivity.")
    finally:
        if engine is not None:
            engine.dispose()

profile = st.session_state.get("discovery_schema_profile")
if profile is not None:
    st.divider()
    st.subheader("Discovery summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Tables discovered", profile.table_count)
    c2.metric("Columns discovered", profile.column_count)
    c3.metric("Tenant-scoped tables", sum(1 for table in profile.tables if table.has_tenant_id))

    rows: list[dict[str, object]] = []
    for table in profile.tables:
        for column in table.columns:
            top = column.mapping.candidates[0] if column.mapping.candidates else None
            rows.append(
                {
                    "table": column.table_name,
                    "column": column.column_name,
                    "database_type": column.database_type,
                    "inferred_type": column.inferred_type,
                    "nullable": column.nullable,
                    "primary_key": column.is_primary_key,
                    "indexed": column.is_indexed,
                    "foreign_key_targets": ", ".join(column.foreign_key_targets),
                    "tenant_scoped_table": table.has_tenant_id,
                    "mapping_status": column.mapping.status,
                    "suggested_concept": top.concept_key if top else None,
                    "fit_score": top.fit_score if top else None,
                    "mapping_rationale": " | ".join(top.rationale) if top else "No catalog candidate",
                }
            )

    st.subheader("Column-level semantic suggestions")
    st.caption("Suggestions only. Scores are heuristic rankings and must not be treated as confidence probabilities.")
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Table details")
    for table in profile.tables:
        with st.expander(f"{table.table_name} · {len(table.columns)} columns"):
            st.write(
                {
                    "schema": table.schema_name,
                    "primary_key": list(table.primary_key_columns),
                    "has_tenant_id": table.has_tenant_id,
                }
            )
            details = [
                {
                    "column": item.column_name,
                    "type": item.database_type,
                    "nullable": item.nullable,
                    "primary_key": item.is_primary_key,
                    "indexed": item.is_indexed,
                    "foreign_keys": ", ".join(item.foreign_key_targets),
                }
                for item in table.columns
            ]
            st.dataframe(details, use_container_width=True, hide_index=True)

    st.subheader("Engine boundaries")
    for warning in profile.warnings:
        st.caption(f"• {warning}")
else:
    st.warning("Select **Inspect database schema** to start the read-only discovery scan.")
