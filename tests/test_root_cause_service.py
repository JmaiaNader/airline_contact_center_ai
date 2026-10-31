from datetime import date, datetime, timezone

import pytest

from src.analytics.kpi_definitions import KPI_DEFINITIONS
from src.analytics.root_cause_service import (
    metric_definition_from_registry,
    investigate_source_periods,
)
from src.harness.auth_models import AuthenticatedTenantContext


def context(permissions=frozenset({"kpi.view"})):
    return AuthenticatedTenantContext(
        user_id=1,
        membership_id=2,
        tenant_id=7,
        tenant_code="demo_airline",
        tenant_display_name="Demo Airline",
        email_normalized="admin@example.test",
        display_name="Admin",
        identity_provider_code="google_oidc",
        issuer_url="https://accounts.google.com",
        subject_id="google-subject-1",
        role_codes=frozenset({"company_admin"}),
        permission_codes=permissions,
    )


def test_metric_definition_is_derived_from_central_sla_registry():
    result = metric_definition_from_registry("service_level_percent")
    source = KPI_DEFINITIONS["service_level_percent"]
    assert result.numerator_field == source.numerator_field
    assert result.denominator_field == source.denominator_field
    assert result.unit == "percent"
    assert result.adverse_direction == "down"


def test_metric_definition_is_derived_from_central_aht_registry():
    result = metric_definition_from_registry("aht_seconds")
    source = KPI_DEFINITIONS["aht_seconds"]
    assert result.numerator_field == source.numerator_field
    assert result.denominator_field == source.denominator_field
    assert result.unit == source.unit
    assert result.adverse_direction == "up"


def test_unsupported_sum_kpi_cannot_be_used_for_root_cause():
    with pytest.raises(ValueError, match="Unsupported root-cause metric"):
        metric_definition_from_registry("offered_contacts")


def test_investigation_requires_authenticated_tenant_context():
    class EngineNeverUsed:
        pass

    with pytest.raises(TypeError, match="AuthenticatedTenantContext"):
        investigate_source_periods(
            EngineNeverUsed(), object(), source_system_id=12,
            metric_key="service_level_percent",
            baseline_start=date(2026, 1, 1), baseline_end=date(2026, 1, 7),
            current_start=date(2026, 1, 8), current_end=date(2026, 1, 14),
            dimensions=("market_code",),
        )


def test_investigation_requires_permission_before_database_access():
    class EngineNeverUsed:
        def connect(self):
            raise AssertionError("database should not be reached")

    denied = context(permissions=frozenset())
    with pytest.raises(Exception, match="kpi.view"):
        investigate_source_periods(
            EngineNeverUsed(), denied, source_system_id=12,
            metric_key="service_level_percent",
            baseline_start=date(2026, 1, 1), baseline_end=date(2026, 1, 7),
            current_start=date(2026, 1, 8), current_end=date(2026, 1, 14),
            dimensions=("market_code",),
        )


def test_investigation_rejects_overlapping_windows_before_database_access():
    class EngineNeverUsed:
        def connect(self):
            raise AssertionError("database should not be reached")

    with pytest.raises(ValueError, match="must not overlap"):
        investigate_source_periods(
            EngineNeverUsed(), context(), source_system_id=12,
            metric_key="service_level_percent",
            baseline_start=date(2026, 1, 1), baseline_end=date(2026, 1, 10),
            current_start=date(2026, 1, 10), current_end=date(2026, 1, 14),
            dimensions=("market_code",),
        )


def test_investigation_rejects_invalid_source_before_database_access():
    class EngineNeverUsed:
        def connect(self):
            raise AssertionError("database should not be reached")

    with pytest.raises(ValueError, match="source_system_id"):
        investigate_source_periods(
            EngineNeverUsed(), context(), source_system_id=0,
            metric_key="service_level_percent",
            baseline_start=date(2026, 1, 1), baseline_end=date(2026, 1, 7),
            current_start=date(2026, 1, 8), current_end=date(2026, 1, 14),
            dimensions=("market_code",),
        )


def test_service_loads_two_windows_and_returns_ranked_segment_findings():
    class FakeMappings:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return FakeMappings(self._rows)

    class FakeConnection:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params):
            self.calls.append((str(statement), dict(params)))
            common = {
                "tenant_id": params["tenant_id"],
                "source_system_id": params["source_system_id"],
                "market_code": "QATAR",
                "channel_code": "voice",
                "service_code": "booking",
                "service_language_code": "en",
                "offered_contacts": 100,
                "answered_contacts": 95,
                "handled_contacts": 95,
                "abandoned_contacts": 5,
                "sla_eligible_contacts": 100,
                "total_handle_seconds": 19000,
                "total_answer_wait_seconds": 1900,
                "quality_status": "warning",
            }
            within = 95 if params["start_utc"].date() == date(2026, 1, 1) else 70
            row = {
                **common,
                "answered_within_threshold_contacts": within,
            }
            return FakeResult([row])

    class FakeEngine:
        def __init__(self):
            self.connection = FakeConnection()

        def connect(self):
            return self.connection

    engine = FakeEngine()
    result = investigate_source_periods(
        engine,
        context(),
        source_system_id=12,
        metric_key="service_level_percent",
        baseline_start=date(2026, 1, 1),
        baseline_end=date(2026, 1, 7),
        current_start=date(2026, 1, 8),
        current_end=date(2026, 1, 14),
        dimensions=("market_code",),
        min_denominator=30,
    )
    assert result.baseline_interval_rows == 1
    assert result.current_interval_rows == 1
    assert result.report.overall_change == pytest.approx(-25.0)
    assert result.report.findings[0].segment == "QATAR"
    assert result.report.analysis_class == "exploratory"
    assert result.report.causal_claim is False
    assert len(engine.connection.calls) == 2
    assert all(call[1]["tenant_id"] == 7 for call in engine.connection.calls)
    assert all(call[1]["source_system_id"] == 12 for call in engine.connection.calls)
