from datetime import datetime, timezone

import pytest

from src.analytics.root_cause_engine import MetricDefinition, investigate_root_causes


SPECS = {
    "sla": MetricDefinition("answered_within_threshold_contacts", "sla_eligible_contacts", "percent", "down"),
    "aht": MetricDefinition("total_handle_seconds", "handled_contacts", "seconds", "up"),
    "asa": MetricDefinition("total_answer_wait_seconds", "answered_contacts", "seconds", "up"),
    "abandonment_rate": MetricDefinition("abandoned_contacts", "offered_contacts", "percent", "up"),
}


def row(**overrides):
    base = {
        "market_code": "QATAR",
        "channel_code": "voice",
        "service_code": "booking",
        "service_language_code": "en",
        "offered_contacts": 100,
        "answered_contacts": 90,
        "handled_contacts": 90,
        "abandoned_contacts": 10,
        "sla_eligible_contacts": 90,
        "answered_within_threshold_contacts": 81,
        "total_handle_seconds": 18000,
        "total_answer_wait_seconds": 1800,
        "quality_status": "valid",
    }
    base.update(overrides)
    return base


def test_sla_uses_summed_numerator_and_denominator():
    baseline = [row(sla_eligible_contacts=10, answered_within_threshold_contacts=10),
                row(sla_eligible_contacts=90, answered_within_threshold_contacts=45)]
    current = [row(sla_eligible_contacts=100, answered_within_threshold_contacts=60)]
    report = investigate_root_causes(baseline, current, metric="sla", metric_definition=SPECS["sla"], min_denominator=1)
    assert report.baseline.value == pytest.approx(55.0)
    assert report.current.value == pytest.approx(60.0)


def test_aht_is_weighted_by_handled_contacts():
    baseline = [row(handled_contacts=10, total_handle_seconds=1000),
                row(handled_contacts=90, total_handle_seconds=18000)]
    current = [row(handled_contacts=100, total_handle_seconds=20000)]
    report = investigate_root_causes(baseline, current, metric="aht", metric_definition=SPECS["aht"], min_denominator=1)
    assert report.baseline.value == pytest.approx(190.0)
    assert report.current.value == pytest.approx(200.0)


def test_sla_deterioration_ranks_segment():
    baseline = [row(market_code="QATAR", sla_eligible_contacts=100, answered_within_threshold_contacts=95),
                row(market_code="UAE", sla_eligible_contacts=100, answered_within_threshold_contacts=95)]
    current = [row(market_code="QATAR", sla_eligible_contacts=100, answered_within_threshold_contacts=70),
               row(market_code="UAE", sla_eligible_contacts=100, answered_within_threshold_contacts=94)]
    report = investigate_root_causes(
        baseline, current, metric="sla", metric_definition=SPECS["sla"], dimensions=("market_code",), min_denominator=30
    )
    assert report.findings
    assert report.findings[0].dimension == "market_code"
    assert report.findings[0].segment == "QATAR"
    assert report.findings[0].adverse_change == pytest.approx(25.0)


def test_aht_increase_is_adverse():
    baseline = [row(total_handle_seconds=15000, handled_contacts=100)]
    current = [row(total_handle_seconds=20000, handled_contacts=100)]
    report = investigate_root_causes(baseline, current, metric="aht", metric_definition=SPECS["aht"], min_denominator=1)
    assert report.overall_adverse_change == pytest.approx(50.0)


def test_abandonment_rate_increase_is_adverse():
    baseline = [row(offered_contacts=100, abandoned_contacts=5)]
    current = [row(offered_contacts=100, abandoned_contacts=15)]
    report = investigate_root_causes(baseline, current, metric="abandonment_rate", metric_definition=SPECS["abandonment_rate"], min_denominator=1)
    assert report.overall_adverse_change == pytest.approx(10.0)


def test_small_segments_are_excluded():
    baseline = [row(market_code="SMALL", sla_eligible_contacts=10, answered_within_threshold_contacts=5)]
    current = [row(market_code="SMALL", sla_eligible_contacts=10, answered_within_threshold_contacts=2)]
    report = investigate_root_causes(baseline, current, metric="sla", metric_definition=SPECS["sla"], min_denominator=30)
    assert not report.findings


def test_improvement_does_not_produce_adverse_findings():
    baseline = [row(channel_code="voice", sla_eligible_contacts=100, answered_within_threshold_contacts=70)]
    current = [row(channel_code="voice", sla_eligible_contacts=100, answered_within_threshold_contacts=95)]
    report = investigate_root_causes(baseline, current, metric="sla", metric_definition=SPECS["sla"], min_denominator=1)
    assert report.overall_adverse_change == 0
    assert not report.findings


def test_zero_denominator_is_rejected():
    with pytest.raises(ValueError, match="denominator is zero"):
        investigate_root_causes(
            [row(sla_eligible_contacts=0, answered_within_threshold_contacts=0)],
            [row(sla_eligible_contacts=0, answered_within_threshold_contacts=0)],
            metric="sla", metric_definition=SPECS["sla"],
        )


def test_unsupported_metric_is_rejected():
    with pytest.raises(TypeError, match="central KPI definition registry"):
        investigate_root_causes([row()], [row()], metric="csat", metric_definition=None)


def test_negative_values_are_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        investigate_root_causes(
            [row()], [row(offered_contacts=-1)], metric="abandonment_rate",
            metric_definition=SPECS["abandonment_rate"]
        )


def test_quality_warning_marks_analysis_exploratory():
    report = investigate_root_causes(
        [row(quality_status="warning")], [row(quality_status="warning")], metric="sla", metric_definition=SPECS["sla"], min_denominator=1
    )
    assert report.analysis_class == "exploratory"
    assert report.causal_claim is False


def test_valid_data_marks_analysis_reviewable():
    report = investigate_root_causes([row()], [row()], metric="sla", metric_definition=SPECS["sla"], min_denominator=1)
    assert report.analysis_class == "reviewable"
    assert report.causal_claim is False


def test_empty_period_rejected():
    with pytest.raises(ValueError, match="must contain data"):
        investigate_root_causes(
            [], [row()], metric="sla", metric_definition=SPECS["sla"]
        )


def test_findings_are_limited_to_top_n():
    baseline = [row(market_code=m, sla_eligible_contacts=100, answered_within_threshold_contacts=95)
                for m in ("QATAR", "UAE", "USA")]
    current = [row(market_code=m, sla_eligible_contacts=100, answered_within_threshold_contacts=60)
               for m in ("QATAR", "UAE", "USA")]
    report = investigate_root_causes(baseline, current, metric="sla", metric_definition=SPECS["sla"], min_denominator=1, top_n=2)
    assert len(report.findings) <= 2


def test_to_dict_is_json_friendly():
    report = investigate_root_causes([row()], [row()], metric="sla", metric_definition=SPECS["sla"], min_denominator=1)
    payload = report.to_dict()
    assert payload["metric"] == "sla"
    assert payload["causal_claim"] is False
    assert isinstance(payload["findings"], list)
