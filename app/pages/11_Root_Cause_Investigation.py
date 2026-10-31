from __future__ import annotations

import csv
import io
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

from src.analytics.kpi_definitions import KPI_DEFINITIONS
from src.analytics.kpi_engine import KPIAnalysisService
from src.analytics.root_cause_service import (
    ROOT_CAUSE_METRIC_KEYS,
    investigate_source_periods,
)
from src.config.settings import get_settings
from src.database.connection import create_db_engine

st.set_page_config(page_title="Root Cause Investigation", page_icon="🔎", layout="wide")
st.title("🔎 AeroInsight — Root Cause Investigation")
st.caption("Deterministic · Tenant-scoped · Read-only · UTC · Associations, not causal proof")

from app.authentication import require_authenticated_tenant_context

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("kpi.view"):
    st.error("Your active company membership does not grant kpi.view.")
    st.stop()

settings = get_settings()
engine = create_db_engine(settings)
kpi_service = KPIAnalysisService(engine)


def _format_metric(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:,.2f}%"
    if unit == "seconds":
        return f"{value:,.2f} sec"
    return f"{value:,.2f} {unit}"


def _format_change(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:+,.2f} percentage points"
    if unit == "seconds":
        return f"{value:+,.2f} sec"
    return f"{value:+,.2f}"


try:
    sources = kpi_service.list_sources(tenant_context)
    if not sources:
        st.warning(
            "No loaded historical source is available for this company. "
            "Load interval aggregates first in Historical Data Ingestion."
        )
        st.stop()

    source_by_id = {item.source_system_id: item for item in sources}
    source_id = st.selectbox(
        "Historical data source",
        options=list(source_by_id),
        format_func=lambda key: (
            f"{source_by_id[key].display_name} ({source_by_id[key].source_code})"
        ),
    )
    selected_source = source_by_id[source_id]

    source_first = (
        selected_source.first_interval_utc.date()
        if selected_source.first_interval_utc is not None
        else date(2026, 1, 1)
    )
    source_last = (
        selected_source.last_interval_utc.date()
        if selected_source.last_interval_utc is not None
        else date.today()
    )

    # Defaults use the latest 28-day current period and the immediately preceding
    # 28-day baseline when sufficient history exists. Users can change both windows.
    current_end_default = source_last
    current_start_default = max(source_first, current_end_default - timedelta(days=27))
    baseline_end_default = current_start_default - timedelta(days=1)
    baseline_start_default = max(source_first, baseline_end_default - timedelta(days=27))

    if baseline_end_default < source_first:
        st.info(
            "The selected source does not yet contain two separate periods for a comparison. "
            "Use a source with a longer historical range."
        )
        st.caption(
            f"Available UTC coverage: {source_first.isoformat()} → {source_last.isoformat()}"
        )
        st.stop()

    st.subheader("Investigation setup")
    metric_labels = {key: KPI_DEFINITIONS[key].label for key in ROOT_CAUSE_METRIC_KEYS}
    metric_key = st.selectbox(
        "KPI to investigate",
        options=list(ROOT_CAUSE_METRIC_KEYS),
        format_func=lambda key: metric_labels[key],
    )

    baseline_heading, current_heading = st.columns(2)
    with baseline_heading:
        st.markdown("**Baseline window (UTC)**")
        baseline_start = st.date_input(
            "Baseline start", value=baseline_start_default, key="rc_baseline_start"
        )
        baseline_end = st.date_input(
            "Baseline end", value=baseline_end_default, key="rc_baseline_end"
        )
    with current_heading:
        st.markdown("**Current window (UTC)**")
        current_start = st.date_input(
            "Current start", value=current_start_default, key="rc_current_start"
        )
        current_end = st.date_input(
            "Current end", value=current_end_default, key="rc_current_end"
        )

    st.caption(
        f"Source coverage: {source_first.isoformat()} → {source_last.isoformat()} UTC · "
        f"Source: {selected_source.source_code} · Company: {tenant_context.tenant_code}"
    )

    dimension_labels = {
        "market_code": "Market",
        "channel_code": "Channel",
        "service_code": "Service",
        "service_language_code": "Service language",
    }
    selected_dimensions = st.multiselect(
        "Compare segments by",
        options=list(dimension_labels),
        default=list(dimension_labels),
        format_func=lambda key: dimension_labels[key],
        help="The investigation compares each selected segment between the baseline and current windows.",
    )

    options_col_1, options_col_2 = st.columns(2)
    with options_col_1:
        min_denominator = st.number_input(
            "Minimum denominator per segment",
            min_value=1,
            max_value=1_000_000,
            value=30,
            step=10,
            help="Segments below this volume in either period are excluded to reduce small-sample noise.",
        )
    with options_col_2:
        top_n = st.number_input("Maximum findings", min_value=1, max_value=50, value=10, step=1)

    if selected_source.is_synthetic_demo:
        st.warning(
            "SYNTHETIC DEMO DATA — findings are for demonstration and investigation only, "
            "not actual airline operational evidence."
        )

    run = st.button("Run root-cause investigation", type="primary", use_container_width=True)
    if run:
        if not selected_dimensions:
            st.error("Select at least one segmentation dimension.")
            st.stop()
        if baseline_start > baseline_end:
            st.error("Baseline start must be on or before baseline end.")
            st.stop()
        if current_start > current_end:
            st.error("Current start must be on or before current end.")
            st.stop()
        if baseline_end >= current_start:
            st.error("The baseline and current windows must not overlap. Baseline must end before current starts.")
            st.stop()

        with st.spinner("Loading tenant-scoped intervals and ranking segment movements..."):
            result = investigate_source_periods(
                engine,
                tenant_context,
                source_system_id=int(source_id),
                metric_key=metric_key,
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                current_start=current_start,
                current_end=current_end,
                dimensions=tuple(selected_dimensions),
                min_denominator=float(min_denominator),
                top_n=int(top_n),
            )

        report = result.report
        if report.analysis_class == "exploratory" or selected_source.is_synthetic_demo:
            st.warning(
                "EXPLORATORY ANALYSIS — one or more input rows are synthetic, warning, "
                "unreviewed or otherwise not marked valid. Do not treat findings as production conclusions."
            )

        definition = KPI_DEFINITIONS[metric_key]
        st.subheader("Overall comparison")
        card_1, card_2, card_3, card_4 = st.columns(4)
        card_1.metric("Baseline", _format_metric(report.baseline.value, report.unit))
        card_2.metric("Current", _format_metric(report.current.value, report.unit))
        card_3.metric("Change", _format_change(report.overall_change, report.unit))
        card_4.metric(
            "Adverse movement",
            _format_metric(report.overall_adverse_change, report.unit),
        )

        st.caption(
            f"Formula: {definition.formula} · Numerator: {definition.numerator_field} · "
            f"Denominator: {definition.denominator_field} · KPI definition version: 1.0.0"
        )
        st.caption(
            f"Baseline intervals: {result.baseline_interval_rows:,} · "
            f"Current intervals: {result.current_interval_rows:,} · "
            f"Quality statuses: {', '.join(report.quality_statuses)}"
        )

        st.subheader("Segments associated with deterioration")
        if not report.findings:
            st.success(
                "No segment deterioration met the current minimum-volume and comparison rules. "
                "This does not prove that no operational issue exists."
            )
        else:
            finding_rows = []
            for finding in report.findings:
                finding_rows.append(
                    {
                        "Dimension": dimension_labels.get(finding.dimension, finding.dimension),
                        "Segment": finding.segment,
                        "Baseline": _format_metric(finding.baseline_value, finding.unit),
                        "Current": _format_metric(finding.current_value, finding.unit),
                        "Change": _format_change(finding.change, finding.unit),
                        "Current exposure %": round(finding.current_exposure * 100.0, 2),
                        "Impact score": round(finding.impact_score, 4),
                        "Baseline volume": round(finding.baseline_denominator),
                        "Current volume": round(finding.current_denominator),
                        "Interpretation": finding.interpretation,
                    }
                )
            st.dataframe(finding_rows, use_container_width=True, hide_index=True)

            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(
                csv_buffer,
                fieldnames=list(finding_rows[0].keys()),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(finding_rows)
            st.download_button(
                "Export investigation findings (CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"{tenant_context.tenant_code}_{metric_key}_root_cause_findings_utc.csv",
                mime="text/csv",
            )

        with st.expander("Method, evidence and limitations"):
            st.markdown(
                f"- KPI formula comes from the central registry: `{definition.formula}`.\n"
                "- Segment results use summed numerator and denominator values; interval percentages are not averaged.\n"
                "- Data is restricted to the authenticated tenant, selected active source and loaded ingestion batches.\n"
                "- Baseline and current UTC windows are explicit and non-overlapping.\n"
                "- Segments below the minimum denominator in either window are excluded.\n"
                "- Impact score = adverse segment movement × current exposure share. It is a prioritization score, not causal attribution.\n"
                "- The report always sets `causal_claim = false`; findings are associations requiring operational investigation.\n"
                f"- Analysis class: `{report.analysis_class}`."
            )

except ValueError as exc:
    st.warning(str(exc))
except Exception as exc:
    st.error("Root-cause investigation could not be completed.")
    st.caption(f"{type(exc).__name__}: {exc}")
finally:
    engine.dispose()
