from __future__ import annotations

import csv
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

from src.analytics.kpi_engine import KPIAnalysisFilters, KPIAnalysisService
from src.config.settings import get_settings
from src.database.connection import create_db_engine

st.set_page_config(page_title="KPI Analysis", page_icon="📊", layout="wide")
st.title("📊 AeroInsight — Deterministic KPI Analysis")
st.caption("Tenant-scoped · Read-only · UTC · Central Python KPI definitions")

if not getattr(getattr(st, "user", None), "is_logged_in", False):
    st.warning("Sign in with Google to view company-scoped KPI analysis.")
    from app.authentication import require_authenticated_tenant_context
    require_authenticated_tenant_context()

from app.authentication import require_authenticated_tenant_context

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("kpi.view"):
    st.error("Your active company membership does not grant kpi.view.")
    st.stop()

settings = get_settings()
engine = create_db_engine(settings)
service = KPIAnalysisService(engine)

st.info(
    f"Active company: **{tenant_context.tenant_display_name}** (`{tenant_context.tenant_code}`). "
    "Calculations use canonical interval numerators and denominators from the existing "
    "db_airlines.historical_interval_metrics table. No source-reported percentages or "
    "averages are used as canonical KPI results."
)


def _display_value(value: int | Decimal | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "contacts":
        return f"{int(value):,}"
    if unit == "%":
        return f"{value:,.2f}%"
    return f"{value:,.2f} sec"


def _number_or_none(value: int | Decimal | None) -> float | None:
    return None if value is None else float(value)


try:
    sources = service.list_sources(tenant_context)
    if not sources:
        st.warning(
            "No loaded historical interval source is available for this company. "
            "Load aggregated interval data first in Historical Data Ingestion."
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

    filter_options = service.list_filter_options(
        tenant_context, source_system_id=int(source_id)
    )

    default_start = (
        selected_source.first_interval_utc.date()
        if selected_source.first_interval_utc is not None
        else date(2026, 1, 1)
    )
    default_end = (
        selected_source.last_interval_utc.date()
        if selected_source.last_interval_utc is not None
        else date.today()
    )

    st.subheader("Analysis filters")
    date_col_1, date_col_2, grain_col = st.columns([1, 1, 1])
    with date_col_1:
        start_date = st.date_input("Start date (UTC)", value=default_start, key="kpi_start_date")
    with date_col_2:
        end_date = st.date_input("End date (UTC)", value=default_end, key="kpi_end_date")
    with grain_col:
        grain_label = st.selectbox("Trend granularity", ["Daily", "Monthly"], index=0)

    filter_col_1, filter_col_2, filter_col_3 = st.columns(3)
    with filter_col_1:
        markets = ["All"] + list(filter_options["market_codes"])
        market_choice = st.selectbox("Market", markets)
    with filter_col_2:
        channels = ["All"] + list(filter_options["channel_codes"])
        channel_choice = st.selectbox("Channel", channels)
    with filter_col_3:
        languages = ["All"] + list(filter_options["language_codes"])
        language_choice = st.selectbox("Service language", languages)

    if start_date > end_date:
        st.error("Start date must be on or before end date.")
        st.stop()

    filters = KPIAnalysisFilters(
        source_system_id=int(source_id),
        start_date_utc=start_date,
        end_date_utc=end_date,
        market_code=None if market_choice == "All" else market_choice,
        channel_code=None if channel_choice == "All" else channel_choice,
        service_language_code=None if language_choice == "All" else language_choice,
        grain="day" if grain_label == "Daily" else "month",
    )

    with st.spinner("Calculating deterministic KPIs from interval numerators and denominators..."):
        analysis = service.analyze(tenant_context, filters)

    if analysis.synthetic_demo:
        st.warning(
            "SYNTHETIC DEMO DATA — these results demonstrate the calculation pipeline and "
            "are NOT actual airline operational performance. Production eligibility is false."
        )
    elif not analysis.production_eligible:
        st.warning(
            "Data quality checks found warning, unreviewed or incomplete records. "
            "Calculated values are displayed for investigation and are not marked production-eligible."
        )

    quality = analysis.quality
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Interval rows", f"{quality.interval_rows:,}")
    q2.metric("Loaded batches", f"{selected_source.loaded_batch_count:,}")
    q3.metric("Warning rows", f"{quality.warning_rows:,}")
    q4.metric("Synthetic rows", f"{quality.synthetic_rows:,}")

    st.caption(
        f"Source: {selected_source.source_code} · "
        f"UTC coverage: {quality.first_interval_utc or '—'} → {quality.last_interval_utc or '—'} · "
        f"Definition version: 1.0.0 · Production eligible: {'Yes' if analysis.production_eligible else 'No'}"
    )

    st.subheader("KPI results")
    metric_by_key = {item.key: item for item in analysis.metrics}
    display_order = (
        "offered_contacts",
        "answered_contacts",
        "handled_contacts",
        "abandoned_contacts",
        "service_level_percent",
        "aht_seconds",
        "asa_seconds",
        "abandonment_rate_percent",
        "answer_rate_percent",
    )
    for offset in range(0, len(display_order), 3):
        cards = st.columns(3)
        for column, key in zip(cards, display_order[offset : offset + 3]):
            metric = metric_by_key[key]
            delta = None if metric.status == "calculated" else metric.status.replace("_", " ").title()
            column.metric(metric.label, _display_value(metric.value, metric.unit), delta=delta)

    with st.expander("KPI formulas and calculation lineage", expanded=False):
        st.dataframe(
            [
                {
                    "KPI": item.label,
                    "Value": _display_value(item.value, item.unit),
                    "Formula": item.formula,
                    "Numerator": None if item.numerator is None else str(item.numerator),
                    "Denominator": None if item.denominator is None else str(item.denominator),
                    "Status": item.status,
                    "Definition version": item.definition_version,
                    "Description": item.description,
                }
                for item in analysis.metrics
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "All ratio KPIs are calculated from period-level SUM(numerator) / SUM(denominator). "
            "The engine does not average interval percentages or source-reported averages."
        )

    st.subheader("Trend analysis")
    if analysis.trend_rows:
        trend_table = []
        for row in analysis.trend_rows:
            trend_table.append(
                {
                    "Period (UTC)": row["period_start"],
                    "Intervals": row["interval_rows"],
                    "Offered": row["offered_contacts"],
                    "Answered": row["answered_contacts"],
                    "Handled": row["handled_contacts"],
                    "Abandoned": row["abandoned_contacts"],
                    "Service Level %": _number_or_none(row["service_level_percent"]),
                    "AHT seconds": _number_or_none(row["aht_seconds"]),
                    "ASA seconds": _number_or_none(row["asa_seconds"]),
                }
            )
        st.dataframe(trend_table, use_container_width=True, hide_index=True)
        csv_buffer = io.StringIO(newline="")
        csv_writer = csv.DictWriter(csv_buffer, fieldnames=list(trend_table[0].keys()), lineterminator="\n")
        csv_writer.writeheader()
        csv_writer.writerows(trend_table)
        st.download_button(
            "Export KPI trend (CSV)",
            data=csv_buffer.getvalue(),
            file_name=f"{tenant_context.tenant_code}_kpi_trend_utc.csv",
            mime="text/csv",
        )
        import pandas as pd

        trend_frame = pd.DataFrame(trend_table)
        chart_frame = trend_frame.set_index("Period (UTC)")[["Offered", "Handled"]]
        st.line_chart(chart_frame)
        st.line_chart(
            trend_frame.set_index("Period (UTC)")[["Service Level %"]]
        )
    else:
        st.info("No interval data matched the selected source and filters.")

    st.subheader("Data quality and evidence controls")
    quality_rows = [
        {"Check": "Synthetic demo records", "Affected rows": quality.synthetic_rows},
        {"Check": "Quality status = warning", "Affected rows": quality.warning_rows},
        {"Check": "Quality status = unreviewed", "Affected rows": quality.unreviewed_rows},
        {"Check": "Offered != answered + abandoned", "Affected rows": quality.volume_balance_issue_rows},
        {"Check": "Handled contacts without handle-time total", "Affected rows": quality.missing_aht_component_rows},
        {"Check": "Answered contacts without wait-time total", "Affected rows": quality.missing_asa_component_rows},
        {"Check": "SLA within-threshold > eligible", "Affected rows": quality.invalid_sla_rows},
    ]
    st.dataframe(quality_rows, use_container_width=True, hide_index=True)
    st.info(
        "CSAT and NPS are not calculated from this interval table because it contains no survey "
        "responses or promoter/detractor counts. They require a separate approved feedback source. "
        "No target is assumed: KPI targets are separate from KPI formulas and remain unconfigured "
        "until a tenant-level target is explicitly set."
    )
finally:
    engine.dispose()
