from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.analytics.kpi_definitions import KPI_DEFINITIONS, KPI_DEFINITION_VERSION
from src.analytics.kpi_engine import (
    KPIAnalysisFilters,
    KPIAnalysisService,
    KPIDataSourceNotFound,
    calculate_kpis,
)
from src.harness.auth_models import AuthenticatedTenantContext
from src.harness.exceptions import PermissionDenied


def _aggregate(**overrides):
    values = {
        "interval_rows": 2,
        "offered_contacts": 100,
        "answered_contacts": 90,
        "handled_contacts": 88,
        "abandoned_contacts": 10,
        "answered_within_threshold_contacts": 72,
        "sla_eligible_contacts": 90,
        "total_handle_seconds": 17600,
        "total_answer_wait_seconds": 4500,
        # These reported values must not drive the canonical calculations.
        "source_reported_aht_seconds": Decimal("999.999"),
        "source_reported_asa_seconds": Decimal("888.888"),
        "source_reported_sla_percent": Decimal("1.00"),
    }
    values.update(overrides)
    return values


def _metric(results, key):
    return next(item for item in results if item.key == key)


def _context(*permissions: str) -> AuthenticatedTenantContext:
    return AuthenticatedTenantContext(
        user_id=7,
        membership_id=11,
        tenant_id=41,
        tenant_code="demo_airline",
        tenant_display_name="Demo Airline",
        email_normalized="admin@example.test",
        display_name="Admin",
        identity_provider_code="google_oidc",
        issuer_url="https://accounts.google.com",
        subject_id="google-subject-7",
        role_codes=frozenset({"company_admin"}),
        permission_codes=frozenset(permissions),
    )


def test_kpi_definitions_are_central_and_versioned():
    assert len(KPI_DEFINITIONS) == 9
    assert KPI_DEFINITION_VERSION == "1.0.0"
    assert KPI_DEFINITIONS["service_level_percent"].denominator_field == "sla_eligible_contacts"
    assert KPI_DEFINITIONS["aht_seconds"].denominator_field == "handled_contacts"


def test_count_kpis_use_canonical_sums():
    results = calculate_kpis(_aggregate())
    assert _metric(results, "offered_contacts").value == 100
    assert _metric(results, "answered_contacts").value == 90
    assert _metric(results, "handled_contacts").value == 88
    assert _metric(results, "abandoned_contacts").value == 10


def test_service_level_uses_summed_numerator_and_eligible_denominator():
    result = _metric(calculate_kpis(_aggregate()), "service_level_percent")
    assert result.value == Decimal("80.00")
    assert result.numerator == Decimal("72")
    assert result.denominator == Decimal("90")
    assert result.formula == "100 × SUM(answered_within_threshold_contacts) / SUM(sla_eligible_contacts)"


def test_aht_is_weighted_from_total_handle_seconds_over_handled_contacts():
    result = _metric(calculate_kpis(_aggregate()), "aht_seconds")
    assert result.value == Decimal("200.00")
    assert result.numerator == Decimal("17600")
    assert result.denominator == Decimal("88")


def test_asa_is_weighted_from_total_wait_seconds_over_answered_contacts():
    result = _metric(calculate_kpis(_aggregate()), "asa_seconds")
    assert result.value == Decimal("50.00")
    assert result.numerator == Decimal("4500")
    assert result.denominator == Decimal("90")


def test_contact_rates_use_offered_contacts_as_denominator():
    results = calculate_kpis(_aggregate())
    assert _metric(results, "abandonment_rate_percent").value == Decimal("10.00")
    assert _metric(results, "answer_rate_percent").value == Decimal("90.00")


def test_source_reported_fields_are_ignored():
    first = calculate_kpis(_aggregate())
    second = calculate_kpis(
        _aggregate(
            source_reported_aht_seconds=Decimal("1"),
            source_reported_asa_seconds=Decimal("2"),
            source_reported_sla_percent=Decimal("100"),
        )
    )
    assert {item.key: item.value for item in first} == {item.key: item.value for item in second}


def test_zero_denominator_is_not_reported_as_zero_percent():
    results = calculate_kpis(
        _aggregate(
            offered_contacts=0,
            answered_contacts=0,
            handled_contacts=0,
            sla_eligible_contacts=0,
        )
    )
    assert _metric(results, "service_level_percent").value is None
    assert _metric(results, "service_level_percent").status == "zero_denominator"
    assert _metric(results, "aht_seconds").status == "zero_denominator"
    assert _metric(results, "answer_rate_percent").status == "zero_denominator"


def test_missing_numerator_or_denominator_is_flagged():
    results = calculate_kpis(_aggregate(total_handle_seconds=None))
    assert _metric(results, "aht_seconds").value is None
    assert _metric(results, "aht_seconds").status == "missing_components"


def test_null_sum_field_is_no_data_not_zero():
    result = _metric(calculate_kpis(_aggregate(offered_contacts=None)), "offered_contacts")
    assert result.value is None
    assert result.status == "no_data"


def test_ratio_rounds_half_up():
    result = _metric(
        calculate_kpis(
            _aggregate(
                total_handle_seconds=Decimal("100"),
                handled_contacts=Decimal("3"),
            )
        ),
        "aht_seconds",
    )
    assert result.value == Decimal("33.33")


def test_filters_accept_valid_date_range_and_grain():
    filters = KPIAnalysisFilters(
        source_system_id=2,
        start_date_utc=date(2026, 1, 1),
        end_date_utc=date(2026, 10, 31),
        grain="month",
    )
    assert filters.grain == "month"


def test_filters_reject_end_before_start():
    with pytest.raises(ValueError, match="on or after"):
        KPIAnalysisFilters(2, date(2026, 2, 1), date(2026, 1, 31))


def test_filters_reject_unapproved_grain():
    with pytest.raises(ValueError, match="grain"):
        KPIAnalysisFilters(2, date(2026, 1, 1), date(2026, 1, 2), grain="hour")


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if len(self._rows) != 1:
            raise AssertionError("Expected exactly one fake row")
        return self._rows[0]


class _FakeConnection:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, dict(params)))
        for marker, rows in self.responses:
            if marker in sql:
                return _FakeResult(rows)
        raise AssertionError(f"Unexpected SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, connections):
        self.connections = list(connections)

    def connect(self):
        return self.connections.pop(0)


def test_list_sources_is_tenant_scoped_and_uses_loaded_batch_aggregate():
    connection = _FakeConnection(
        [
            (
                "FROM source_systems s",
                [
                    {
                        "source_system_id": 9,
                        "source_code": "synthetic_historical_2026",
                        "display_name": "Synthetic demo",
                        "source_type": "manual",
                        "loaded_batch_count": 1,
                        "loaded_record_count": 233472,
                        "first_interval_utc": datetime(2026, 1, 1),
                        "last_interval_utc": datetime(2026, 10, 31, 23, 45),
                    }
                ],
            )
        ]
    )
    service = KPIAnalysisService(_FakeEngine([connection]))
    sources = service.list_sources(_context("kpi.view"))

    assert len(sources) == 1
    assert sources[0].is_synthetic_demo is True
    assert sources[0].loaded_record_count == 233472
    sql, params = connection.calls[0]
    assert "WHERE s.tenant_id = :tenant_id" in sql
    assert params["tenant_id"] == 41


def test_list_sources_requires_kpi_view_permission():
    service = KPIAnalysisService(_FakeEngine([]))
    with pytest.raises(PermissionDenied):
        service.list_sources(_context("mapping.view"))


def test_source_ownership_is_checked_with_context_tenant_id():
    connection = _FakeConnection([("FROM source_systems", [])])
    service = KPIAnalysisService(_FakeEngine([connection]))
    with pytest.raises(KPIDataSourceNotFound):
        service._ensure_source(_context("kpi.view"), 99)
    sql, params = connection.calls[0]
    assert "tenant_id = :tenant_id" in sql
    assert params == {"tenant_id": 41, "source_system_id": 99}
