from datetime import date, timedelta

import pytest

from src.analytics.statistical_analysis import (
    StatisticalAnalysisError,
    analyze_kpi_trends,
    detect_anomalies,
    summarize_series,
)


def _rows(values, metric_key="service_level_percent"):
    start = date(2026, 1, 1)
    return [
        {"period_start": start + timedelta(days=index), "service_level_percent": value,
         "aht_seconds": 300 + index, "offered_contacts": 100 + index, metric_key: value}
        for index, value in enumerate(values)
    ]


def test_summary_reports_basic_statistics_and_direction():
    rows = _rows([90, 91, 92, 93])
    summary = summarize_series(rows, metric_key="service_level_percent")
    assert summary.observations == 4
    assert summary.first_value == 90
    assert summary.last_value == 93
    assert summary.net_change == 3
    assert summary.direction == "increasing"


def test_summary_handles_no_data():
    summary = summarize_series([{"period_start": date(2026, 1, 1), "aht_seconds": None}], metric_key="aht_seconds")
    assert summary.observations == 0
    assert summary.direction == "no_data"


def test_detects_low_sla_against_trailing_baseline():
    values = [95.0] * 20 + [70.0]
    findings = detect_anomalies(
        _rows(values), metric_key="service_level_percent", metric_label="Service Level",
        direction="lower_is_worse", minimum_history=14, lookback_periods=20,
    )
    assert len(findings) == 1
    assert findings[0].severity == "adverse_deviation"
    assert findings[0].observed_value == 70.0
    assert findings[0].baseline_median == 95.0


def test_detects_high_aht_as_adverse():
    rows = _rows([300.0] * 15 + [700.0], metric_key="aht_seconds")
    findings = detect_anomalies(rows, metric_key="aht_seconds", direction="higher_is_worse", minimum_history=14)
    assert len(findings) == 1
    assert findings[0].severity == "adverse_deviation"


def test_constant_baseline_deviation_is_flagged_without_infinite_score():
    rows = _rows([90.0] * 14 + [92.0])
    findings = detect_anomalies(rows, metric_key="service_level_percent", minimum_history=14)
    assert len(findings) == 1
    assert findings[0].robust_z_score is None
    assert findings[0].method == "constant_baseline_deviation"


def test_no_anomaly_when_series_is_stable():
    rows = _rows([90.0, 91.0, 90.5, 90.8, 91.1, 90.9, 91.0, 90.7, 91.2, 90.6, 91.1, 90.8, 91.0, 90.9, 91.0])
    findings = detect_anomalies(rows, metric_key="service_level_percent", minimum_history=14)
    assert findings == ()


def test_uses_prior_periods_only_no_future_leakage():
    rows = _rows([100.0] * 14 + [200.0, 100.0], metric_key="offered_contacts")
    findings = detect_anomalies(rows, metric_key="offered_contacts", minimum_history=14)
    assert [item.period for item in findings] == [date(2026, 1, 15).isoformat()]


def test_ignores_missing_and_non_numeric_observations():
    rows = _rows([90.0] * 14 + [None, "not-a-number", 70.0])
    findings = detect_anomalies(rows, metric_key="service_level_percent", minimum_history=14)
    assert len(findings) == 1
    assert findings[0].observed_value == 70.0


def test_validates_direction():
    with pytest.raises(StatisticalAnalysisError, match="direction"):
        detect_anomalies(_rows([1, 2, 3, 4]), metric_key="aht_seconds", direction="bad")


def test_validates_minimum_history():
    with pytest.raises(StatisticalAnalysisError, match="minimum_history"):
        detect_anomalies(_rows([1, 2, 3]), metric_key="aht_seconds", minimum_history=2)


def test_validates_lookback():
    with pytest.raises(StatisticalAnalysisError, match="lookback_periods"):
        detect_anomalies(_rows([1, 2, 3, 4]), metric_key="aht_seconds", minimum_history=3, lookback_periods=2)


def test_analyze_multiple_kpis_and_keep_direction_labels():
    rows = _rows([95.0] * 20 + [70.0])
    result = analyze_kpi_trends(
        rows,
        metric_specs={
            "service_level_percent": ("Service Level", "lower_is_worse"),
            "aht_seconds": ("AHT", "higher_is_worse"),
        },
        minimum_history=14,
    )
    assert len(result.summaries) == 2
    sla = [item for item in result.findings if item.metric_key == "service_level_percent"]
    assert len(sla) == 1
    assert sla[0].severity == "adverse_deviation"


def test_findings_explain_not_causal_claim():
    findings = detect_anomalies(_rows([90.0] * 14 + [70.0]), metric_key="service_level_percent", minimum_history=14)
    assert "does not establish the cause" in findings[0].explanation
