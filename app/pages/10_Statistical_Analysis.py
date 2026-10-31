from __future__ import annotations

import csv
import io
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

from src.analytics.kpi_engine import KPIAnalysisFilters, KPIAnalysisService
from src.analytics.statistical_analysis import analyze_kpi_trends
from src.config.settings import get_settings
from src.database.connection import create_db_engine

st.set_page_config(page_title="Statistical Analysis", page_icon="📈", layout="wide")
st.title("📈 AeroInsight — Statistical Analysis & Anomaly Detection")
st.caption("Deterministic · Tenant-scoped · Read-only · UTC · Evidence-linked to KPI trend rows")

from app.authentication import require_authenticated_tenant_context

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("kpi.view"):
    st.error("Your active company membership does not grant kpi.view.")
    st.stop()

settings = get_settings()
engine = create_db_engine(settings)
service = KPIAnalysisService(engine)

METRIC_SPECS = {
    "service_level_percent": ("Service Level", "lower_is_worse"),
    "aht_seconds": ("Average Handle Time", "higher_is_worse"),
    "asa_seconds": ("Average Speed of Answer", "higher_is_worse"),
    "abandonment_rate_percent": ("Abandonment Rate", "higher_is_worse"),
    "answer_rate_percent": ("Answer Rate", "lower_is_worse"),
    "offered_contacts": ("Offered Contacts", "two_sided"),
    "handled_contacts": ("Handled Contacts", "two_sided"),
}


def _display_number(value: float | None, metric_key: str) -> str:
    if value is None:
        return "—"
    if metric_key.endswith("_percent"):
        return f"{value:,.2f}%"
    if metric_key.endswith("_seconds"):
        return f"{value:,.2f} sec"
    return f"{value:,.0f}"


try:
    sources = service.list_sources(tenant_context)
    if not sources:
        st.warning("No loaded historical source is available for this company. Load interval data first.")
        st.stop()

    source_by_id = {source.source_system_id: source for source in sources}
    source_id = st.selectbox(
        "Historical data source",
        options=list(source_by_id),
        format_func=lambda key: f"{source_by_id[key].display_name} ({source_by_id[key].source_code})",
    )
    selected_source = source_by_id[source_id]
    filter_options = service.list_filter_options(tenant_context, source_system_id=int(source_id))

    default_start = selected_source.first_interval_utc.date() if selected_source.first_interval_utc else date(2026, 1, 1)
    default_end = selected_source.last_interval_utc.date() if selected_source.last_interval_utc else date.today()

    st.subheader("Analysis scope")
    c1, c2, c3 = st.columns(3)
    with c1:
        start_date = st.date_input("Start date (UTC)", value=default_start, key="stats_start_date")
    with c2:
        end_date = st.date_input("End date (UTC)", value=default_end, key="stats_end_date")
    with c3:
        grain_label = st.selectbox("Trend granularity", ["Daily", "Monthly"], key="stats_grain")

    f1, f2, f3 = st.columns(3)
    with f1:
        market = st.selectbox("Market", ["All", *filter_options["market_codes"]], key="stats_market")
    with f2:
        channel = st.selectbox("Channel", ["All", *filter_options["channel_codes"]], key="stats_channel")
    with f3:
        language = st.selectbox("Service language", ["All", *filter_options["language_codes"]], key="stats_language")

    if start_date > end_date:
        st.error("Start date must be on or before end date.")
        st.stop()

    grain = "day" if grain_label == "Daily" else "month"
    filters = KPIAnalysisFilters(
        source_system_id=int(source_id),
        start_date_utc=start_date,
        end_date_utc=end_date,
        market_code=None if market == "All" else market,
        channel_code=None if channel == "All" else channel,
        service_language_code=None if language == "All" else language,
        grain=grain,
    )

    with st.spinner("Calculating KPI trend rows and trailing statistical baselines..."):
        kpi_analysis = service.analyze(tenant_context, filters)

    if kpi_analysis.synthetic_demo:
        st.warning("SYNTHETIC DEMO DATA — anomaly findings are for pipeline demonstration, not actual airline operations.")
    elif not kpi_analysis.production_eligible:
        st.warning("Source data is not production-eligible. Findings are investigative signals only.")

    minimum_history = 14 if grain == "day" else 6
    lookback_periods = 28 if grain == "day" else 6
    threshold = 3.5
    result = analyze_kpi_trends(
        kpi_analysis.trend_rows,
        metric_specs=METRIC_SPECS,
        minimum_history=minimum_history,
        lookback_periods=lookback_periods,
        threshold=threshold,
    )

    st.subheader("Statistical overview")
    overview1, overview2, overview3, overview4 = st.columns(4)
    overview1.metric("Periods analyzed", str(max(result.observations_by_metric.values(), default=0)))
    overview2.metric("Metrics monitored", str(len(result.summaries)))
    overview3.metric("Anomaly candidates", str(len(result.findings)))
    overview4.metric("Baseline", f"{minimum_history}+ prior periods")

    st.caption(
        f"Company: {tenant_context.tenant_code} · Source: {selected_source.source_code} · "
        f"Baseline: previous {lookback_periods} periods · Modified robust-Z threshold: {threshold} · UTC"
    )

    st.subheader("KPI trend summaries")
    summary_rows = []
    for summary in result.summaries:
        label = METRIC_SPECS[summary.metric_key][0]
        summary_rows.append({
            "KPI": label,
            "Observations": summary.observations,
            "First period": summary.first_period,
            "Last period": summary.last_period,
            "First value": _display_number(summary.first_value, summary.metric_key),
            "Last value": _display_number(summary.last_value, summary.metric_key),
            "Minimum": _display_number(summary.minimum, summary.metric_key),
            "Maximum": _display_number(summary.maximum, summary.metric_key),
            "Net change": _display_number(summary.net_change, summary.metric_key),
            "Direction": summary.direction,
        })
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    st.subheader("Anomaly candidates")
    st.caption("Findings compare each period only with preceding periods. They identify unusual deviations; they do not prove root cause.")
    if not result.findings:
        enough = all(count >= minimum_history + 1 for count in result.observations_by_metric.values())
        if enough:
            st.success("No anomaly candidates were detected under the current statistical settings.")
        else:
            st.info(f"Insufficient history for anomaly detection. Need at least {minimum_history + 1} non-null periods per KPI.")
    else:
        finding_rows = []
        for finding in result.findings:
            finding_rows.append({
                "Period (UTC)": finding.period,
                "KPI": finding.metric_label,
                "Observed": _display_number(finding.observed_value, finding.metric_key),
                "Baseline median": _display_number(finding.baseline_median, finding.metric_key),
                "Deviation": _display_number(finding.deviation, finding.metric_key),
                "Robust Z": "Undefined (constant baseline)" if finding.robust_z_score is None else round(finding.robust_z_score, 2),
                "Severity": finding.severity,
                "Baseline periods": finding.baseline_observations,
                "Method": finding.method,
                "Explanation": finding.explanation,
            })
        st.dataframe(finding_rows, use_container_width=True, hide_index=True)

        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(finding_rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(finding_rows)
        st.download_button(
            "Export anomaly candidates (CSV)",
            data=buffer.getvalue(),
            file_name=f"{tenant_context.tenant_code}_statistical_anomaly_candidates_utc.csv",
            mime="text/csv",
        )

    with st.expander("Method and limitations"):
        st.markdown(
            "- The module consumes trend rows from the central deterministic KPI Engine; it does not redefine KPI formulas.\n"
            "- Baselines use prior periods only (trailing window), avoiding future-data leakage.\n"
            "- Modified robust Z-score uses MAD, with an IQR fallback; constant baselines are handled explicitly.\n"
            "- No seasonal adjustment or causal inference is performed in this version. Weekday/holiday/channel mix can affect comparisons.\n"
            "- Synthetic data remains labelled synthetic and is not production evidence.\n"
            "- This page is read-only and does not modify mappings, KPI definitions, or database records."
        )
finally:
    engine.dispose()
