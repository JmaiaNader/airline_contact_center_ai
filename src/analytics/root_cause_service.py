"""Application service for tenant-scoped root-cause investigations.

KPI formulas and source fields are taken from the central KPI registry. This module
only supplies adverse-direction metadata and orchestrates two explicit UTC windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence

from sqlalchemy.engine import Engine

from src.analytics.kpi_definitions import KPI_DEFINITIONS
from src.analytics.root_cause_engine import (
    MetricDefinition,
    RootCauseReport,
    investigate_root_causes,
)
from src.analytics.root_cause_repository import load_interval_rows
from src.harness.auth_models import AuthenticatedTenantContext


# Direction describes what constitutes adverse movement; it does not duplicate formulas.
ADVERSE_DIRECTIONS = {
    "service_level_percent": "down",
    "aht_seconds": "up",
    "asa_seconds": "up",
    "abandonment_rate_percent": "up",
    "answer_rate_percent": "down",
}

ROOT_CAUSE_METRIC_KEYS = tuple(ADVERSE_DIRECTIONS)


@dataclass(frozen=True, slots=True)
class RootCauseInvestigationResult:
    report: RootCauseReport
    source_system_id: int
    baseline_interval_rows: int
    current_interval_rows: int
    baseline_start_utc: datetime
    baseline_end_utc_exclusive: datetime
    current_start_utc: datetime
    current_end_utc_exclusive: datetime


def metric_definition_from_registry(metric_key: str) -> MetricDefinition:
    """Build a root-cause metric spec from the canonical KPI registry."""
    if metric_key not in ROOT_CAUSE_METRIC_KEYS:
        raise ValueError(f"Unsupported root-cause metric: {metric_key!r}.")
    definition = KPI_DEFINITIONS[metric_key]
    if not definition.numerator_field or not definition.denominator_field:
        raise ValueError(f"KPI {metric_key!r} has no ratio numerator/denominator definition.")
    unit = "percent" if definition.unit == "%" else definition.unit
    return MetricDefinition(
        numerator_field=definition.numerator_field,
        denominator_field=definition.denominator_field,
        unit=unit,
        adverse_direction=ADVERSE_DIRECTIONS[metric_key],
    )


def _utc_day_start(value: date) -> datetime:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("Investigation window boundaries must be date values.")
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def investigate_source_periods(
    engine: Engine,
    context: AuthenticatedTenantContext,
    *,
    source_system_id: int,
    metric_key: str,
    baseline_start: date,
    baseline_end: date,
    current_start: date,
    current_end: date,
    dimensions: Sequence[str],
    min_denominator: float = 30.0,
    top_n: int = 10,
) -> RootCauseInvestigationResult:
    """Investigate two non-overlapping date windows for one authenticated tenant/source."""
    if not isinstance(context, AuthenticatedTenantContext):
        raise TypeError("A server-resolved AuthenticatedTenantContext is required.")
    # Authorization returns the trusted tenant ID; it is never accepted from UI state.
    tenant_id = context.require_permission("kpi.view")
    metric_definition = metric_definition_from_registry(metric_key)

    baseline_start_utc = _utc_day_start(baseline_start)
    baseline_end_utc = _utc_day_start(baseline_end + timedelta(days=1))
    current_start_utc = _utc_day_start(current_start)
    current_end_utc = _utc_day_start(current_end + timedelta(days=1))

    if baseline_start > baseline_end:
        raise ValueError("Baseline start date must be on or before baseline end date.")
    if current_start > current_end:
        raise ValueError("Current start date must be on or before current end date.")
    if baseline_end >= current_start:
        raise ValueError("Baseline and current windows must not overlap; baseline must end before current starts.")

    if isinstance(source_system_id, bool) or not isinstance(source_system_id, int) or source_system_id <= 0:
        raise ValueError("source_system_id must be a positive integer.")

    with engine.connect() as connection:
        baseline_rows = load_interval_rows(
            connection,
            authenticated_tenant_id=tenant_id,
            source_system_id=source_system_id,
            start_utc=baseline_start_utc,
            end_utc=baseline_end_utc,
        )
        current_rows = load_interval_rows(
            connection,
            authenticated_tenant_id=tenant_id,
            source_system_id=source_system_id,
            start_utc=current_start_utc,
            end_utc=current_end_utc,
        )

    if not baseline_rows:
        raise ValueError("No loaded historical records found in the baseline window for this source.")
    if not current_rows:
        raise ValueError("No loaded historical records found in the current window for this source.")

    report = investigate_root_causes(
        baseline_rows,
        current_rows,
        metric=metric_key,
        metric_definition=metric_definition,
        dimensions=dimensions,
        min_denominator=min_denominator,
        top_n=top_n,
    )
    return RootCauseInvestigationResult(
        report=report,
        source_system_id=source_system_id,
        baseline_interval_rows=len(baseline_rows),
        current_interval_rows=len(current_rows),
        baseline_start_utc=baseline_start_utc,
        baseline_end_utc_exclusive=baseline_end_utc,
        current_start_utc=current_start_utc,
        current_end_utc_exclusive=current_end_utc,
    )
