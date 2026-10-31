"""Deterministic, evidence-ranked segment analysis for contact-centre KPIs.

This module identifies segments whose KPI movement is associated with an
observed deterioration. It does not establish causality and does not use an
LLM to calculate, rank, or approve results.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class MetricDefinition:
    numerator_field: str
    denominator_field: str
    unit: str
    adverse_direction: str  # "down" means a decrease is adverse; "up" means an increase is adverse.


DEFAULT_DIMENSIONS: tuple[str, ...] = (
    "market_code",
    "channel_code",
    "service_code",
    "service_language_code",
)


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    numerator: float
    denominator: float
    unit: str


@dataclass(frozen=True)
class SegmentFinding:
    dimension: str
    segment: str
    baseline_value: float
    current_value: float
    change: float
    adverse_change: float
    current_exposure: float
    impact_score: float
    baseline_denominator: float
    current_denominator: float
    baseline_rows: int
    current_rows: int
    unit: str
    interpretation: str


@dataclass(frozen=True)
class RootCauseReport:
    metric: str
    unit: str
    baseline: MetricValue
    current: MetricValue
    overall_change: float | None
    overall_adverse_change: float | None
    findings: tuple[SegmentFinding, ...]
    quality_statuses: tuple[str, ...]
    analysis_class: str
    causal_claim: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "unit": self.unit,
            "baseline": asdict(self.baseline),
            "current": asdict(self.current),
            "overall_change": self.overall_change,
            "overall_adverse_change": self.overall_adverse_change,
            "findings": [asdict(item) for item in self.findings],
            "quality_statuses": list(self.quality_statuses),
            "analysis_class": self.analysis_class,
            "causal_claim": self.causal_claim,
            "notes": list(self.notes),
        }


def _number(row: Mapping[str, Any], field: str) -> float:
    value = row.get(field)
    if value is None:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field {field!r} must be numeric or NULL; got {value!r}.") from exc
    if not isfinite(parsed) or parsed < 0:
        raise ValueError(f"Field {field!r} must be finite and non-negative; got {value!r}.")
    return parsed


def _metric_value(rows: Sequence[Mapping[str, Any]], definition: MetricDefinition) -> MetricValue:
    numerator = sum(_number(row, definition.numerator_field) for row in rows)
    denominator = sum(_number(row, definition.denominator_field) for row in rows)
    if denominator == 0:
        value = None
    elif definition.unit == "percent":
        value = numerator / denominator * 100.0
    else:
        value = numerator / denominator
    return MetricValue(value=value, numerator=numerator, denominator=denominator, unit=definition.unit)


def _adverse_change(change: float, direction: str) -> float:
    # Always return a non-negative value for deterioration and zero for
    # improvement/no movement. Preserve raw signed `change` separately.
    return max(0.0, -change if direction == "down" else change)


def investigate_root_causes(
    baseline_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[Mapping[str, Any]],
    *,
    metric: str,
    metric_definition: MetricDefinition,
    dimensions: Sequence[str] = DEFAULT_DIMENSIONS,
    min_denominator: float = 30.0,
    top_n: int = 10,
) -> RootCauseReport:
    """Rank dimensions/segments associated with an adverse KPI movement.

    Inputs must be pre-filtered to one authenticated tenant and two explicit,
    non-overlapping comparison windows by the caller. Values are recomputed
    from summed numerators and denominators (never averaged row-level rates).
    """
    if not isinstance(metric_definition, MetricDefinition):
        raise TypeError("metric_definition must come from the central KPI definition registry.")
    if min_denominator <= 0:
        raise ValueError("min_denominator must be greater than zero.")
    if top_n < 1:
        raise ValueError("top_n must be at least 1.")
    if not dimensions:
        raise ValueError("At least one segmentation dimension is required.")

    baseline = tuple(dict(row) for row in baseline_rows)
    current = tuple(dict(row) for row in current_rows)
    if not baseline or not current:
        raise ValueError("Both baseline_rows and current_rows must contain data.")

    definition = metric_definition
    baseline_total = _metric_value(baseline, definition)
    current_total = _metric_value(current, definition)
    if baseline_total.value is None or current_total.value is None:
        raise ValueError(f"Cannot calculate {metric}: baseline or current denominator is zero.")

    change = current_total.value - baseline_total.value
    overall_adverse = _adverse_change(change, definition.adverse_direction)
    total_current_exposure = current_total.denominator
    findings: list[SegmentFinding] = []
    notes: list[str] = [
        "Findings are associations across segments, not proof of causality.",
        "KPI values are calculated from summed numerators and denominators.",
        "Comparison windows and tenant scope must be enforced by the caller.",
    ]

    for dimension in dimensions:
        base_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        current_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in baseline:
            key = row.get(dimension)
            label = "(NULL / unspecified)" if key is None else str(key)
            base_groups[label].append(row)
        for row in current:
            key = row.get(dimension)
            label = "(NULL / unspecified)" if key is None else str(key)
            current_groups[label].append(row)

        for segment in sorted(set(base_groups) & set(current_groups)):
            base_rows = base_groups[segment]
            current_segment_rows = current_groups[segment]
            base_value = _metric_value(base_rows, definition)
            current_value = _metric_value(current_segment_rows, definition)
            if (
                base_value.value is None
                or current_value.value is None
                or base_value.denominator < min_denominator
                or current_value.denominator < min_denominator
            ):
                continue
            segment_change = current_value.value - base_value.value
            adverse = _adverse_change(segment_change, definition.adverse_direction)
            exposure = current_value.denominator / total_current_exposure if total_current_exposure else 0.0
            impact = adverse * exposure
            if adverse <= 0:
                continue
            findings.append(
                SegmentFinding(
                    dimension=dimension,
                    segment=segment,
                    baseline_value=base_value.value,
                    current_value=current_value.value,
                    change=segment_change,
                    adverse_change=adverse,
                    current_exposure=exposure,
                    impact_score=impact,
                    baseline_denominator=base_value.denominator,
                    current_denominator=current_value.denominator,
                    baseline_rows=len(base_rows),
                    current_rows=len(current_segment_rows),
                    unit=definition.unit,
                    interpretation=(
                        f"{dimension}={segment} deteriorated by {adverse:.3f} {definition.unit} "
                        f"versus baseline; this is an associated segment, not a proven cause."
                    ),
                )
            )

    findings.sort(key=lambda item: (item.impact_score, item.adverse_change), reverse=True)
    quality_statuses = tuple(
        sorted(
            {
                str(row.get("quality_status") or "unknown").lower()
                for row in (*baseline, *current)
            }
        )
    )
    analysis_class = "exploratory" if any(status != "valid" for status in quality_statuses) else "reviewable"
    if analysis_class == "exploratory":
        notes.append(
            "At least one source row is not marked quality_status='valid'; treat findings as exploratory."
        )

    return RootCauseReport(
        metric=metric,
        unit=definition.unit,
        baseline=baseline_total,
        current=current_total,
        overall_change=change,
        overall_adverse_change=overall_adverse,
        findings=tuple(findings[:top_n]),
        quality_statuses=quality_statuses,
        analysis_class=analysis_class,
        causal_claim=False,
        notes=tuple(notes),
    )
