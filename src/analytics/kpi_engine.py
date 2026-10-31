"""Tenant-scoped, read-only deterministic KPI analysis over canonical intervals.

The engine queries only aggregate-ready rows from historical_interval_metrics and
loaded ingestion_batches. It never executes LLM-generated SQL. All tenant and source
filters are bound parameters; the tenant ID comes only from AuthenticatedTenantContext.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from sqlalchemy import Engine, text

from src.analytics.kpi_definitions import KPI_DEFINITIONS, KPI_DEFINITION_VERSION
from src.harness.auth_models import AuthenticatedTenantContext


class KPIAnalysisError(RuntimeError):
    """Raised when a KPI analysis request is invalid or not authorized."""


class KPIDataSourceNotFound(KPIAnalysisError):
    """Raised when a source is absent, inactive or does not belong to the active tenant."""


@dataclass(frozen=True, slots=True)
class KPIAnalysisFilters:
    source_system_id: int
    start_date_utc: date
    end_date_utc: date
    market_code: str | None = None
    channel_code: str | None = None
    service_language_code: str | None = None
    grain: str = "day"

    def __post_init__(self) -> None:
        if isinstance(self.source_system_id, bool) or not isinstance(self.source_system_id, int) or self.source_system_id <= 0:
            raise ValueError("source_system_id must be a positive integer.")
        if not isinstance(self.start_date_utc, date) or isinstance(self.start_date_utc, datetime):
            raise ValueError("start_date_utc must be a date.")
        if not isinstance(self.end_date_utc, date) or isinstance(self.end_date_utc, datetime):
            raise ValueError("end_date_utc must be a date.")
        if self.end_date_utc < self.start_date_utc:
            raise ValueError("end_date_utc must be on or after start_date_utc.")
        if self.grain not in {"day", "month"}:
            raise ValueError("grain must be 'day' or 'month'.")
        for field_name, value, max_length in (
            ("market_code", self.market_code, 16),
            ("channel_code", self.channel_code, 32),
            ("service_language_code", self.service_language_code, 12),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > max_length):
                raise ValueError(f"{field_name} has an invalid value.")


@dataclass(frozen=True, slots=True)
class KPIResult:
    key: str
    label: str
    value: int | Decimal | None
    unit: str
    formula: str
    numerator: Decimal | None
    denominator: Decimal | None
    status: str
    description: str
    definition_version: str


@dataclass(frozen=True, slots=True)
class KPIDataQuality:
    interval_rows: int
    warning_rows: int
    unreviewed_rows: int
    synthetic_rows: int
    volume_balance_issue_rows: int
    missing_aht_component_rows: int
    missing_asa_component_rows: int
    invalid_sla_rows: int
    first_interval_utc: datetime | None
    last_interval_utc: datetime | None

    @property
    def has_quality_warnings(self) -> bool:
        return any(
            (
                self.warning_rows,
                self.unreviewed_rows,
                self.synthetic_rows,
                self.volume_balance_issue_rows,
                self.missing_aht_component_rows,
                self.missing_asa_component_rows,
                self.invalid_sla_rows,
            )
        )


@dataclass(frozen=True, slots=True)
class KPIDataSource:
    source_system_id: int
    source_code: str
    display_name: str
    source_type: str
    loaded_batch_count: int
    loaded_record_count: int
    first_interval_utc: datetime | None
    last_interval_utc: datetime | None
    is_synthetic_demo: bool


@dataclass(frozen=True, slots=True)
class KPIAnalysis:
    tenant_code: str
    source: KPIDataSource
    filters: KPIAnalysisFilters
    metrics: tuple[KPIResult, ...]
    trend_rows: tuple[Mapping[str, Any], ...]
    quality: KPIDataQuality
    aggregate_values: Mapping[str, Any]
    synthetic_demo: bool
    production_eligible: bool

    def metric(self, key: str) -> KPIResult:
        for item in self.metrics:
            if item.key == key:
                return item
        raise KeyError(key)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _rounded(value: Decimal, precision: int) -> Decimal:
    quantum = Decimal("1") if precision == 0 else Decimal("1").scaleb(-precision)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def calculate_kpis(aggregate_values: Mapping[str, Any]) -> tuple[KPIResult, ...]:
    """Calculate all KPIs from aggregate numerators/denominators using central definitions.

    Null components remain unavailable; zero denominators return `zero_denominator`.
    Source-reported averages and percentages are intentionally ignored.
    """
    if not isinstance(aggregate_values, Mapping):
        raise TypeError("aggregate_values must be a mapping.")

    results: list[KPIResult] = []
    for definition in KPI_DEFINITIONS.values():
        if definition.formula_kind == "sum":
            raw = _decimal(aggregate_values.get(definition.source_fields[0]))
            status = "calculated" if raw is not None else "no_data"
            value: int | Decimal | None = None if raw is None else int(raw) if raw == raw.to_integral_value() else raw
            results.append(
                KPIResult(
                    key=definition.key,
                    label=definition.label,
                    value=value,
                    unit=definition.unit,
                    formula=definition.formula,
                    numerator=raw,
                    denominator=None,
                    status=status,
                    description=definition.description,
                    definition_version=KPI_DEFINITION_VERSION,
                )
            )
            continue

        numerator = _decimal(aggregate_values.get(definition.numerator_field or ""))
        denominator = _decimal(aggregate_values.get(definition.denominator_field or ""))
        if numerator is None or denominator is None:
            value = None
            status = "missing_components"
        elif denominator == 0:
            value = None
            status = "zero_denominator"
        else:
            calculated = numerator / denominator
            if definition.formula_kind == "ratio_percent":
                calculated *= Decimal("100")
            value = _rounded(calculated, definition.precision)
            status = "calculated"

        results.append(
            KPIResult(
                key=definition.key,
                label=definition.label,
                value=value,
                unit=definition.unit,
                formula=definition.formula,
                numerator=numerator,
                denominator=denominator,
                status=status,
                description=definition.description,
                definition_version=KPI_DEFINITION_VERSION,
            )
        )
    return tuple(results)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _source_from_row(row: Mapping[str, Any]) -> KPIDataSource:
    source_code = str(row["source_code"])
    display_name = str(row["display_name"])
    is_synthetic = "synthetic" in source_code.lower() or "synthetic" in display_name.lower()
    return KPIDataSource(
        source_system_id=int(row["source_system_id"]),
        source_code=source_code,
        display_name=display_name,
        source_type=str(row["source_type"]),
        loaded_batch_count=_as_int(row.get("loaded_batch_count")),
        loaded_record_count=_as_int(row.get("loaded_record_count")),
        first_interval_utc=row.get("first_interval_utc"),
        last_interval_utc=row.get("last_interval_utc"),
        is_synthetic_demo=is_synthetic,
    )


class KPIAnalysisService:
    """Read-only KPI query service, always scoped to a verified tenant context."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _tenant_id(context: AuthenticatedTenantContext) -> int:
        if not isinstance(context, AuthenticatedTenantContext):
            raise TypeError("A server-resolved AuthenticatedTenantContext is required.")
        return context.require_permission("kpi.view")

    def list_sources(self, context: AuthenticatedTenantContext) -> tuple[KPIDataSource, ...]:
        tenant_id = self._tenant_id(context)
        statement = text(
            """SELECT
                   s.source_system_id, s.source_code, s.display_name, s.source_type,
                   COALESCE(batches.loaded_batch_count, 0) AS loaded_batch_count,
                   COALESCE(batches.loaded_record_count, 0) AS loaded_record_count,
                   metrics.first_interval_utc,
                   metrics.last_interval_utc
               FROM source_systems s
               LEFT JOIN (
                   SELECT tenant_id, source_system_id,
                          COUNT(*) AS loaded_batch_count,
                          SUM(records_accepted) AS loaded_record_count
                   FROM ingestion_batches
                   WHERE batch_type = 'historical_interval_metrics'
                     AND batch_status = 'loaded'
                   GROUP BY tenant_id, source_system_id
               ) batches
                 ON batches.tenant_id = s.tenant_id
                AND batches.source_system_id = s.source_system_id
               LEFT JOIN (
                   SELECT m.tenant_id, m.source_system_id,
                          MIN(m.interval_start_utc) AS first_interval_utc,
                          MAX(m.interval_start_utc) AS last_interval_utc
                   FROM historical_interval_metrics m
                   JOIN ingestion_batches b
                     ON b.tenant_id = m.tenant_id
                    AND b.source_system_id = m.source_system_id
                    AND b.ingestion_batch_id = m.ingestion_batch_id
                    AND b.batch_type = 'historical_interval_metrics'
                    AND b.batch_status = 'loaded'
                   GROUP BY m.tenant_id, m.source_system_id
               ) metrics
                 ON metrics.tenant_id = s.tenant_id
                AND metrics.source_system_id = s.source_system_id
               WHERE s.tenant_id = :tenant_id
                 AND s.source_status = 'active'
                 AND COALESCE(batches.loaded_batch_count, 0) > 0
               ORDER BY s.display_name, s.source_code"""
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"tenant_id": tenant_id}).mappings().all()
        return tuple(_source_from_row(row) for row in rows)

    def list_filter_options(
        self,
        context: AuthenticatedTenantContext,
        *,
        source_system_id: int,
    ) -> Mapping[str, tuple[str, ...]]:
        tenant_id = self._tenant_id(context)
        self._ensure_source(context, source_system_id)
        base = """SELECT DISTINCT {column} AS value
                  FROM historical_interval_metrics m
                  JOIN ingestion_batches b
                    ON b.tenant_id = m.tenant_id
                   AND b.source_system_id = m.source_system_id
                   AND b.ingestion_batch_id = m.ingestion_batch_id
                   AND b.batch_status = 'loaded'
                  WHERE m.tenant_id = :tenant_id
                    AND m.source_system_id = :source_system_id
                    AND {column} IS NOT NULL
                  ORDER BY value"""
        # Column expressions are fixed constants, never supplied by the browser.
        values: dict[str, tuple[str, ...]] = {}
        with self._engine.connect() as connection:
            for key, column in (
                ("market_codes", "m.market_code"),
                ("channel_codes", "m.channel_code"),
                ("language_codes", "m.service_language_code"),
            ):
                rows = connection.execute(
                    text(base.format(column=column)),
                    {"tenant_id": tenant_id, "source_system_id": source_system_id},
                ).mappings().all()
                values[key] = tuple(str(row["value"]) for row in rows)
        return values

    def _ensure_source(self, context: AuthenticatedTenantContext, source_system_id: int) -> Mapping[str, Any]:
        tenant_id = self._tenant_id(context)
        if isinstance(source_system_id, bool) or not isinstance(source_system_id, int) or source_system_id <= 0:
            raise ValueError("source_system_id must be a positive integer.")
        statement = text(
            """SELECT source_system_id, source_code, display_name, source_type
               FROM source_systems
               WHERE tenant_id = :tenant_id
                 AND source_system_id = :source_system_id
                 AND source_status = 'active'"""
        )
        with self._engine.connect() as connection:
            row = connection.execute(
                statement,
                {"tenant_id": tenant_id, "source_system_id": source_system_id},
            ).mappings().one_or_none()
        if row is None:
            raise KPIDataSourceNotFound("The selected source is not active for the current company.")
        return row

    def analyze(
        self,
        context: AuthenticatedTenantContext,
        filters: KPIAnalysisFilters,
    ) -> KPIAnalysis:
        tenant_id = self._tenant_id(context)
        if not isinstance(filters, KPIAnalysisFilters):
            raise TypeError("filters must be a KPIAnalysisFilters instance.")
        source_row = self._ensure_source(context, filters.source_system_id)
        source = _source_from_row(
            {
                **dict(source_row),
                "loaded_batch_count": 0,
                "loaded_record_count": 0,
                "first_interval_utc": None,
                "last_interval_utc": None,
            }
        )

        params = {
            "tenant_id": tenant_id,
            "source_system_id": filters.source_system_id,
            "start_utc": datetime.combine(filters.start_date_utc, time.min),
            "end_utc_exclusive": datetime.combine(filters.end_date_utc + timedelta(days=1), time.min),
            "market_code": filters.market_code,
            "channel_code": filters.channel_code,
            "service_language_code": filters.service_language_code,
        }
        where = """m.tenant_id = :tenant_id
                    AND m.source_system_id = :source_system_id
                    AND m.interval_start_utc >= :start_utc
                    AND m.interval_start_utc < :end_utc_exclusive
                    AND b.batch_status = 'loaded'
                    AND b.batch_type = 'historical_interval_metrics'
                    AND (:market_code IS NULL OR m.market_code = :market_code)
                    AND (:channel_code IS NULL OR m.channel_code = :channel_code)
                    AND (:service_language_code IS NULL OR m.service_language_code = :service_language_code)"""

        aggregate_sql = text(
            f"""SELECT
                    COUNT(*) AS interval_rows,
                    MIN(m.interval_start_utc) AS first_interval_utc,
                    MAX(m.interval_start_utc) AS last_interval_utc,
                    SUM(m.offered_contacts) AS offered_contacts,
                    SUM(m.answered_contacts) AS answered_contacts,
                    SUM(m.handled_contacts) AS handled_contacts,
                    SUM(m.abandoned_contacts) AS abandoned_contacts,
                    SUM(m.answered_within_threshold_contacts) AS answered_within_threshold_contacts,
                    SUM(m.sla_eligible_contacts) AS sla_eligible_contacts,
                    SUM(m.total_handle_seconds) AS total_handle_seconds,
                    SUM(m.total_answer_wait_seconds) AS total_answer_wait_seconds,
                    SUM(CASE WHEN m.quality_status = 'warning' THEN 1 ELSE 0 END) AS warning_rows,
                    SUM(CASE WHEN m.quality_status = 'unreviewed' THEN 1 ELSE 0 END) AS unreviewed_rows,
                    SUM(CASE WHEN JSON_UNQUOTE(JSON_EXTRACT(m.quality_notes_json, '$.dataset_type')) = 'synthetic_demo'
                              OR JSON_UNQUOTE(JSON_EXTRACT(b.validation_summary_json, '$.dataset_type')) = 'synthetic_demo'
                             THEN 1 ELSE 0 END) AS synthetic_rows,
                    SUM(CASE WHEN m.offered_contacts IS NOT NULL
                                  AND m.answered_contacts IS NOT NULL
                                  AND m.abandoned_contacts IS NOT NULL
                                  AND m.offered_contacts <> m.answered_contacts + m.abandoned_contacts
                             THEN 1 ELSE 0 END) AS volume_balance_issue_rows,
                    SUM(CASE WHEN COALESCE(m.handled_contacts, 0) > 0 AND m.total_handle_seconds IS NULL
                             THEN 1 ELSE 0 END) AS missing_aht_component_rows,
                    SUM(CASE WHEN COALESCE(m.answered_contacts, 0) > 0 AND m.total_answer_wait_seconds IS NULL
                             THEN 1 ELSE 0 END) AS missing_asa_component_rows,
                    SUM(CASE WHEN m.sla_eligible_contacts IS NOT NULL
                                  AND m.answered_within_threshold_contacts IS NOT NULL
                                  AND m.answered_within_threshold_contacts > m.sla_eligible_contacts
                             THEN 1 ELSE 0 END) AS invalid_sla_rows
                FROM historical_interval_metrics m
                JOIN ingestion_batches b
                  ON b.tenant_id = m.tenant_id
                 AND b.source_system_id = m.source_system_id
                 AND b.ingestion_batch_id = m.ingestion_batch_id
                WHERE {where}"""
        )

        if filters.grain == "day":
            period_expression = "DATE(m.interval_start_utc)"
        else:
            period_expression = (
                "DATE_SUB(DATE(m.interval_start_utc), "
                "INTERVAL DAYOFMONTH(m.interval_start_utc) - 1 DAY)"
            )
        trend_sql = text(
            f"""SELECT
                    {period_expression} AS period_start,
                    COUNT(*) AS interval_rows,
                    SUM(m.offered_contacts) AS offered_contacts,
                    SUM(m.answered_contacts) AS answered_contacts,
                    SUM(m.handled_contacts) AS handled_contacts,
                    SUM(m.abandoned_contacts) AS abandoned_contacts,
                    SUM(m.answered_within_threshold_contacts) AS answered_within_threshold_contacts,
                    SUM(m.sla_eligible_contacts) AS sla_eligible_contacts,
                    SUM(m.total_handle_seconds) AS total_handle_seconds,
                    SUM(m.total_answer_wait_seconds) AS total_answer_wait_seconds
                FROM historical_interval_metrics m
                JOIN ingestion_batches b
                  ON b.tenant_id = m.tenant_id
                 AND b.source_system_id = m.source_system_id
                 AND b.ingestion_batch_id = m.ingestion_batch_id
                WHERE {where}
                GROUP BY period_start
                ORDER BY period_start"""
        )

        with self._engine.connect() as connection:
            aggregate = dict(connection.execute(aggregate_sql, params).mappings().one())
            trend_raw = connection.execute(trend_sql, params).mappings().all()

        metrics = calculate_kpis(aggregate)
        quality = KPIDataQuality(
            interval_rows=_as_int(aggregate.get("interval_rows")),
            warning_rows=_as_int(aggregate.get("warning_rows")),
            unreviewed_rows=_as_int(aggregate.get("unreviewed_rows")),
            synthetic_rows=_as_int(aggregate.get("synthetic_rows")),
            volume_balance_issue_rows=_as_int(aggregate.get("volume_balance_issue_rows")),
            missing_aht_component_rows=_as_int(aggregate.get("missing_aht_component_rows")),
            missing_asa_component_rows=_as_int(aggregate.get("missing_asa_component_rows")),
            invalid_sla_rows=_as_int(aggregate.get("invalid_sla_rows")),
            first_interval_utc=aggregate.get("first_interval_utc"),
            last_interval_utc=aggregate.get("last_interval_utc"),
        )
        synthetic_demo = source.is_synthetic_demo or quality.synthetic_rows > 0
        production_eligible = (
            not synthetic_demo
            and quality.interval_rows > 0
            and quality.warning_rows == 0
            and quality.unreviewed_rows == 0
            and quality.volume_balance_issue_rows == 0
            and quality.missing_aht_component_rows == 0
            and quality.missing_asa_component_rows == 0
            and quality.invalid_sla_rows == 0
        )

        trend_rows: list[Mapping[str, Any]] = []
        for row in trend_raw:
            row_dict = dict(row)
            row_kpis = {item.key: item.value for item in calculate_kpis(row_dict)}
            trend_rows.append(
                {
                    "period_start": row_dict["period_start"],
                    "interval_rows": _as_int(row_dict.get("interval_rows")),
                    **row_kpis,
                }
            )

        return KPIAnalysis(
            tenant_code=context.tenant_code,
            source=source,
            filters=filters,
            metrics=metrics,
            trend_rows=tuple(trend_rows),
            quality=quality,
            aggregate_values=aggregate,
            synthetic_demo=synthetic_demo,
            production_eligible=production_eligible,
        )
