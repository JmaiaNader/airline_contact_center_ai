from datetime import datetime, timezone

import pytest

from src.analytics.root_cause_repository import LOAD_INTERVAL_ROWS_SQL, load_interval_rows


class FakeMappings:
    def all(self):
        return [{"tenant_id": 7, "source_system_id": 12, "offered_contacts": 12}]


class FakeResult:
    def mappings(self):
        return FakeMappings()


class FakeConnection:
    def __init__(self):
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = statement
        self.params = params
        return FakeResult()


def test_loader_binds_tenant_source_and_time_window_and_loaded_batches():
    connection = FakeConnection()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = load_interval_rows(
        connection,
        authenticated_tenant_id=7,
        source_system_id=12,
        start_utc=start,
        end_utc=end,
    )
    assert rows == [{"tenant_id": 7, "source_system_id": 12, "offered_contacts": 12}]
    assert connection.params == {
        "tenant_id": 7,
        "source_system_id": 12,
        "start_utc": start,
        "end_utc": end,
    }
    sql = str(connection.statement)
    assert "m.tenant_id = :tenant_id" in sql
    assert "m.source_system_id = :source_system_id" in sql
    assert "b.batch_status = 'loaded'" in sql
    assert "b.batch_type = 'historical_interval_metrics'" in sql


def test_loader_rejects_non_positive_tenant():
    with pytest.raises(ValueError, match="authenticated_tenant_id.*positive integer"):
        load_interval_rows(
            FakeConnection(), authenticated_tenant_id=0, source_system_id=12,
            start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_loader_rejects_non_positive_source():
    with pytest.raises(ValueError, match="source_system_id.*positive integer"):
        load_interval_rows(
            FakeConnection(), authenticated_tenant_id=7, source_system_id=0,
            start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_loader_requires_timezone_aware_datetimes():
    with pytest.raises(ValueError, match="timezone-aware"):
        load_interval_rows(
            FakeConnection(), authenticated_tenant_id=7, source_system_id=12,
            start_utc=datetime(2026, 1, 1), end_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_loader_requires_ordered_window():
    with pytest.raises(ValueError, match="earlier than"):
        load_interval_rows(
            FakeConnection(), authenticated_tenant_id=7, source_system_id=12,
            start_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
            end_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
