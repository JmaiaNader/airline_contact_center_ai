from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

logger = logging.getLogger(__name__)

from src.config.settings import get_settings
from src.database.connection import create_db_engine
from src.ingestion.historical_metrics import HistoricalMetricsIngestionService

st.set_page_config(page_title="Historical Data Ingestion", page_icon="📥", layout="wide")
st.title("📥 AeroInsight — Historical Data Ingestion")
st.caption("Aggregated interval CSV import · Tenant-scoped · UTC · All-or-nothing")

if not getattr(getattr(st, "user", None), "is_logged_in", False):
    st.warning("Sign in with Google to import historical metrics for your company.")
    from app.authentication import require_authenticated_tenant_context
    require_authenticated_tenant_context()

from app.authentication import require_authenticated_tenant_context

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("data_source.manage"):
    st.error("Your active company membership does not grant data_source.manage.")
    st.stop()

settings = get_settings()
engine = create_db_engine(settings)
service = HistoricalMetricsIngestionService(engine)

st.info(
    f"Active company: **{tenant_context.tenant_display_name}** (`{tenant_context.tenant_code}`). "
    "Imports are written to the existing `db_airlines` database. The importer accepts only "
    "aggregated interval metrics; customer-level or passenger-level fields are rejected."
)

project_root = Path(__file__).resolve().parents[2]
template_path = project_root / "templates" / "historical_interval_metrics_template.csv"
if template_path.exists():
    st.download_button(
        "Download CSV template",
        data=template_path.read_bytes(),
        file_name="historical_interval_metrics_template.csv",
        mime="text/csv",
    )

with st.expander("Required CSV format", expanded=False):
    st.markdown(
        """
        Required columns: `interval_start_utc`, `interval_seconds`, `channel_code`.

        Optional dimensions: `market_code`, `service_code`, `queue_id`, `service_language_code`.

        Optional measures: `offered_contacts`, `answered_contacts`, `handled_contacts`,
        `abandoned_contacts`, `sla_eligible_contacts`, `answered_within_threshold_contacts`,
        `total_handle_seconds`, `total_answer_wait_seconds`.

        Optional source-reported measures (`source_reported_*`) are retained only for
        reconciliation. AeroInsight's canonical KPI results will be calculated from
        governed numerators, denominators and central Python definitions.

        **Time rule:** `interval_start_utc` must include a timezone, preferably `Z` (UTC).
        Offsets are normalized to UTC before storage. The database session remains UTC.

        **Current reference-data note:** `services` and `queues` are currently empty in this
        development database. Leave `service_code` and `queue_id` blank until those reference
        records are configured. `channel_code` must exist in the shared `channels` catalog.
        """
    )

uploaded = st.file_uploader(
    "Upload historical interval CSV",
    type=["csv"],
    accept_multiple_files=False,
    help="Maximum 25 MB and 100,000 rows. Upload aggregated intervals only; do not include personal data.",
)

if uploaded is not None:
    payload = uploaded.getvalue()
    file_hash = __import__("hashlib").sha256(payload).hexdigest()

    if st.button("Validate CSV", type="primary", use_container_width=True):
        try:
            with st.spinner("Validating columns, values and company reference codes..."):
                preview = service.preview_file(
                    tenant_context,
                    payload=payload,
                    filename=uploaded.name,
                )
            st.session_state["historical_ingestion_preview"] = {
                "content_sha256": preview.content_sha256,
                "preview": preview,
            }
        except Exception as exc:
            st.session_state.pop("historical_ingestion_preview", None)
            st.error(f"Validation failed ({type(exc).__name__}): {exc}")

    cached = st.session_state.get("historical_ingestion_preview")
    if cached and cached.get("content_sha256") == file_hash:
        preview = cached["preview"]
        left, middle, right = st.columns(3)
        left.metric("Rows received", preview.records_received)
        middle.metric("Rows parsed", len(preview.rows))
        right.metric("Validation errors", len(preview.errors))

        if preview.errors:
            st.error("The entire file is blocked. No metric rows will be imported.")
            st.dataframe(
                [{"Validation issue": error} for error in preview.errors[:100]],
                use_container_width=True,
                hide_index=True,
            )
        elif preview.can_import:
            st.success("CSV validation passed. No rows have been written yet.")
            preview_rows = []
            for row in preview.rows[:20]:
                preview_rows.append(
                    {
                        key: (value.isoformat() + "Z" if hasattr(value, "isoformat") and key == "interval_start_utc" else str(value) if value is not None else None)
                        for key, value in row.items()
                        if not key.startswith("__")
                    }
                )
            st.dataframe(preview_rows, use_container_width=True, hide_index=True)
            st.warning(
                "Import creates one ingestion batch and marks imported rows as `unreviewed`. "
                "It is all-or-nothing and uses a SHA-256 fingerprint to prevent importing the same file twice."
            )
            if st.button("Import validated intervals into db_airlines", type="primary", use_container_width=True):
                try:
                    with st.spinner("Importing validated interval aggregates..."):
                        result = service.import_file(
                            tenant_context,
                            payload=payload,
                            filename=uploaded.name,
                        )
                    if result.status == "loaded":
                        st.success(
                            f"Imported {result.records_accepted:,} interval rows. "
                            f"Batch ID: {result.ingestion_batch_id}. Source ID: {result.source_system_id}."
                        )
                        st.session_state.pop("historical_ingestion_preview", None)
                        st.rerun()
                    elif result.status == "duplicate":
                        st.warning(result.message)
                    else:
                        st.error(result.message)
                except Exception as exc:
                    logger.exception("Historical interval CSV import failed.")
                    st.error(
                        f"Import failed ({type(exc).__name__}). The database transaction was rolled back. "
                        "See the local Streamlit terminal for diagnostic details."
                    )
        else:
            st.warning("No importable data rows were found.")
else:
    st.caption("Download the template, export aggregated interval data from your source system, then upload it here.")

st.divider()
st.subheader("Recent ingestion batches")
try:
    tenant_context.require_permission("data_source.view")
    from sqlalchemy import text

    with engine.connect() as connection:
        batch_rows = connection.execute(
            text(
                """SELECT b.ingestion_batch_id, s.source_code, b.source_file_name,
                          b.batch_status, b.records_received, b.records_accepted,
                          b.records_rejected, b.received_at_utc, b.completed_at_utc
                   FROM ingestion_batches b
                   JOIN source_systems s
                     ON s.tenant_id = b.tenant_id
                    AND s.source_system_id = b.source_system_id
                   WHERE b.tenant_id = :tenant_id
                     AND b.batch_type = 'historical_interval_metrics'
                   ORDER BY b.ingestion_batch_id DESC
                   LIMIT 20"""
            ),
            {"tenant_id": tenant_context.tenant_id},
        ).mappings().all()
    st.dataframe([dict(row) for row in batch_rows], use_container_width=True, hide_index=True)
except Exception as exc:
    st.warning(f"Could not load ingestion history ({type(exc).__name__}).")
finally:
    engine.dispose()
