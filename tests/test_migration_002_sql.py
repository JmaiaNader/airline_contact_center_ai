from pathlib import Path
import re

SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "database"
    / "migrations"
    / "002_tenant_source_lineage_historical_metrics.sql"
)
SQL = SQL_PATH.read_text(encoding="utf-8").lower()


def test_migration_targets_canonical_database():
    assert re.search(r"\buse\s+`db_airlines`\s*;", SQL)


def test_creates_tenant_registry_and_development_tenant():
    assert "create table `tenants`" in SQL
    assert "demo_airline" in SQL
    assert "fk_services_tenant" in SQL


def test_creates_source_lineage_tables():
    assert "create table `source_systems`" in SQL
    assert "create table `ingestion_batches`" in SQL
    assert "source_content_sha256" in SQL
    assert "validation_summary_json" in SQL


def test_creates_historical_interval_table():
    assert "create table `historical_interval_metrics`" in SQL
    assert "interval_start_utc" in SQL
    assert "interval_seconds" in SQL
    assert "source_row_number" in SQL


def test_core_operational_tables_receive_tenant_id():
    for table in (
        "services", "queues", "bookings", "contact_interactions", "sla_rules"
    ):
        assert f"alter table `{table}`" in SQL
        assert "tenant_id" in SQL


def test_service_queue_relationship_is_tenant_scoped():
    assert "foreign key (`tenant_id`, `service_code`)" in SQL
    assert "references `services` (`tenant_id`, `service_code`)" in SQL


def test_interaction_queue_and_booking_relationships_are_tenant_scoped():
    assert "foreign key (`tenant_id`, `queue_id`, `channel_code`)" in SQL
    assert "references `queues` (`tenant_id`, `queue_id`, `channel_code`)" in SQL
    assert "foreign key (`tenant_id`, `booking_id`)" in SQL
    assert "references `bookings` (`tenant_id`, `booking_id`)" in SQL


def test_ingestion_batch_ties_to_matching_source_and_tenant():
    assert "foreign key (`tenant_id`, `source_system_id`)" in SQL
    assert "references `source_systems` (`tenant_id`, `source_system_id`)" in SQL
    assert "foreign key (`tenant_id`, `source_system_id`, `ingestion_batch_id`)" in SQL


def test_metric_stores_numerators_denominators_and_reconciliation_values():
    for column in (
        "offered_contacts", "answered_contacts", "handled_contacts",
        "abandoned_contacts", "sla_eligible_contacts",
        "answered_within_threshold_contacts", "total_handle_seconds",
        "total_answer_wait_seconds", "source_reported_aht_seconds",
        "source_reported_asa_seconds", "source_reported_sla_percent",
    ):
        assert f"`{column}`" in SQL


def test_migration_does_not_drop_or_truncate_tables():
    assert "drop table" not in SQL
    assert "truncate table" not in SQL
    assert not re.search(r"\bdelete\s+from\b", SQL)


def test_migration_warns_not_to_rerun_blindly():
    assert "not idempotent" in SQL
    assert "do not rerun blindly" in SQL
    assert "implicitly commits" in SQL
