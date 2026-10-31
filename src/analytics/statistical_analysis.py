"""Deterministic statistical summaries and trailing-baseline anomaly candidates.

This module consumes already-calculated KPI trend rows. It does not query SQL,
change KPI formulas, infer causal explanations, or mark synthetic data as production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


class StatisticalAnalysisError(ValueError):
    """Raised when the supplied trend series or analysis configuration is invalid."""


@dataclass(frozen=True, slots=True)
class TrendSummary:
    metric_key: str
    observations: int
    first_period: str | None
    last_period: str | None
    first_value: float | None
    last_value: float | None
    minimum: float | None
    maximum: float | None
    mean: float | None
    net_change: float | None
    net_change_percent: float | None
    direction: str


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    metric_key: str
    metric_label: str
    period: str
    observed_value: float
    baseline_median: float
    deviation: float
    robust_z_score: float | None
    baseline_observations: int
    baseline_start_period: str
    baseline_end_period: str
    direction: str
    severity: str
    method: str
    explanation: str


@dataclass(frozen=True, slots=True)
class StatisticalAnalysisResult:
    summaries: tuple[TrendSummary, ...]
    findings: tuple[AnomalyFinding, ...]
    observations_by_metric: Mapping[str, int]
    minimum_history: int
    lookback_periods: int
    threshold: float


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _period_text(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _percent_change(first: float, last: float) -> float | None:
    if first == 0:
        return None
    return ((last - first) / abs(first)) * 100.0


def summarize_series(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric_key: str,
) -> TrendSummary:
    """Return a compact descriptive summary from ordered KPI trend rows."""
    if not metric_key or not isinstance(metric_key, str):
        raise StatisticalAnalysisError("metric_key must be a non-empty string.")
    usable: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise StatisticalAnalysisError("Each trend row must be a mapping.")
        value = _number(row.get(metric_key))
        if value is not None:
            usable.append((_period_text(row.get("period_start", "")), value))

    if not usable:
        return TrendSummary(metric_key, 0, None, None, None, None, None, None, None, None, None, "no_data")

    first_period, first_value = usable[0]
    last_period, last_value = usable[-1]
    net_change = last_value - first_value
    if net_change > 0:
        direction = "increasing"
    elif net_change < 0:
        direction = "decreasing"
    else:
        direction = "stable"
    return TrendSummary(
        metric_key=metric_key,
        observations=len(usable),
        first_period=first_period,
        last_period=last_period,
        first_value=first_value,
        last_value=last_value,
        minimum=min(value for _, value in usable),
        maximum=max(value for _, value in usable),
        mean=sum(value for _, value in usable) / len(usable),
        net_change=net_change,
        net_change_percent=_percent_change(first_value, last_value),
        direction=direction,
    )


def _quartiles(values: Sequence[float]) -> tuple[float, float]:
    ordered = sorted(values)
    n = len(ordered)
    if n < 2:
        return ordered[0], ordered[0]
    midpoint = n // 2
    lower = ordered[:midpoint] if n % 2 == 0 else ordered[:midpoint]
    upper = ordered[midpoint:] if n % 2 == 0 else ordered[midpoint + 1 :]
    if not lower:
        lower = ordered
    if not upper:
        upper = ordered
    return float(median(lower)), float(median(upper))


def _robust_score(observed: float, baseline: Sequence[float]) -> tuple[float | None, float, str]:
    center = float(median(baseline))
    deviations = [abs(value - center) for value in baseline]
    mad = float(median(deviations))
    delta = observed - center
    if mad > 0:
        return 0.67448975 * delta / mad, center, "modified_z_mad"

    q1, q3 = _quartiles(baseline)
    iqr = q3 - q1
    if iqr > 0:
        scale = iqr / 1.349
        return delta / scale, center, "robust_z_iqr_fallback"

    # A constant baseline has no estimated dispersion. A different value is a
    # deviation candidate, but its score is undefined rather than infinite.
    if delta != 0:
        return None, center, "constant_baseline_deviation"
    return 0.0, center, "constant_baseline"


def detect_anomalies(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric_key: str,
    metric_label: str | None = None,
    direction: str = "two_sided",
    minimum_history: int = 14,
    lookback_periods: int = 28,
    threshold: float = 3.5,
) -> tuple[AnomalyFinding, ...]:
    """Detect unusual points against prior observations only (no future leakage).

    `direction` controls severity wording only; it does not change which statistical
    deviations are flagged. Use 'higher_is_worse', 'lower_is_worse', or 'two_sided'.
    A finding is a statistical anomaly candidate, not a causal diagnosis.
    """
    if direction not in {"higher_is_worse", "lower_is_worse", "two_sided"}:
        raise StatisticalAnalysisError("direction must be higher_is_worse, lower_is_worse or two_sided.")
    if isinstance(minimum_history, bool) or not isinstance(minimum_history, int) or minimum_history < 3:
        raise StatisticalAnalysisError("minimum_history must be an integer >= 3.")
    if isinstance(lookback_periods, bool) or not isinstance(lookback_periods, int) or lookback_periods < minimum_history:
        raise StatisticalAnalysisError("lookback_periods must be >= minimum_history.")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or threshold <= 0:
        raise StatisticalAnalysisError("threshold must be a positive number.")

    series: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise StatisticalAnalysisError("Each trend row must be a mapping.")
        value = _number(row.get(metric_key))
        if value is not None:
            series.append((_period_text(row.get("period_start", "")), value))

    findings: list[AnomalyFinding] = []
    label = metric_label or metric_key
    for index, (period, observed) in enumerate(series):
        history = series[max(0, index - lookback_periods) : index]
        if len(history) < minimum_history:
            continue
        baseline_values = [value for _, value in history]
        score, center, method = _robust_score(observed, baseline_values)
        deviation = observed - center
        is_anomaly = (score is not None and abs(score) >= threshold) or (
            score is None and method == "constant_baseline_deviation"
        )
        if not is_anomaly:
            continue

        if direction == "higher_is_worse":
            severity = "adverse_deviation" if deviation > 0 else "favourable_deviation"
        elif direction == "lower_is_worse":
            severity = "adverse_deviation" if deviation < 0 else "favourable_deviation"
        else:
            severity = "unusual_deviation"

        score_text = "undefined (constant baseline)" if score is None else f"{score:.2f}"
        findings.append(
            AnomalyFinding(
                metric_key=metric_key,
                metric_label=label,
                period=period,
                observed_value=observed,
                baseline_median=center,
                deviation=deviation,
                robust_z_score=score,
                baseline_observations=len(history),
                baseline_start_period=history[0][0],
                baseline_end_period=history[-1][0],
                direction=direction,
                severity=severity,
                method=method,
                explanation=(
                    f"{label} was {observed:.4g}; trailing baseline median was {center:.4g} "
                    f"across {len(history)} prior periods. Robust score: {score_text}. "
                    "This flags an unusual deviation; it does not establish the cause."
                ),
            )
        )
    return tuple(findings)


def analyze_kpi_trends(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric_specs: Mapping[str, tuple[str, str]],
    minimum_history: int = 14,
    lookback_periods: int = 28,
    threshold: float = 3.5,
) -> StatisticalAnalysisResult:
    """Summarize and detect anomalies for configured KPI metrics.

    metric_specs maps KPI key -> (display label, direction). Missing/None KPI values
    are skipped. Callers should pass KPIAnalysis.trend_rows from the central KPI engine.
    """
    if not isinstance(metric_specs, Mapping) or not metric_specs:
        raise StatisticalAnalysisError("metric_specs must be a non-empty mapping.")
    summaries: list[TrendSummary] = []
    findings: list[AnomalyFinding] = []
    counts: dict[str, int] = {}
    for key, (label, direction) in metric_specs.items():
        summary = summarize_series(rows, metric_key=key)
        summaries.append(summary)
        counts[key] = summary.observations
        findings.extend(
            detect_anomalies(
                rows,
                metric_key=key,
                metric_label=label,
                direction=direction,
                minimum_history=minimum_history,
                lookback_periods=lookback_periods,
                threshold=threshold,
            )
        )
    findings.sort(key=lambda item: (item.period, item.metric_key))
    return StatisticalAnalysisResult(
        summaries=tuple(summaries),
        findings=tuple(findings),
        observations_by_metric=counts,
        minimum_history=minimum_history,
        lookback_periods=lookback_periods,
        threshold=threshold,
    )
