from pathlib import Path

SQL_PATH = Path(__file__).resolve().parents[1] / "database" / "migrations" / "004_semantic_mapping_registry.sql"
SQL = SQL_PATH.read_text(encoding="utf-8").lower()


def test_migration_targets_existing_development_database():
    assert "use `db_airlines`;" in SQL


def test_creates_versioned_concept_catalog_and_tenant_mapping_store():
    assert "create table `semantic_concepts`" in SQL
    assert "primary key (`concept_key`, `concept_version`)" in SQL
    assert "create table `tenant_source_field_mappings`" in SQL
    assert "`mapping_version` int unsigned not null" in SQL


def test_mapping_store_is_scoped_to_tenant_and_source():
    assert "foreign key (`tenant_id`, `source_system_id`)" in SQL
    assert "references `source_systems` (`tenant_id`, `source_system_id`)" in SQL


def test_mapping_creator_and_reviewer_must_be_tenant_memberships():
    assert "foreign key (`tenant_id`, `created_by_membership_id`)" in SQL
    assert "foreign key (`tenant_id`, `reviewed_by_membership_id`)" in SQL
    assert "references `tenant_memberships` (`tenant_id`, `membership_id`)" in SQL


def test_mapping_has_one_current_version_per_source_field():
    assert "generated always as (case when `is_current` = 1 then 1 else null end) stored" in SQL
    assert "uq004_mapping_current_field" in SQL


def test_no_mapping_is_auto_approved():
    assert "default 'suggested'" not in SQL  # status is explicit for every persisted suggestion
    assert "insert into `tenant_source_field_mappings`" not in SQL
    assert "'approved'" in SQL


def test_seeds_nine_governed_concepts():
    assert SQL.count("json_array(") >= 18
    for key in (
        "customer_satisfaction_score", "net_promoter_score", "agent_quality_score",
        "average_handle_time_seconds", "service_level_pct", "offered_contacts",
        "handled_contacts", "customer_feedback_text", "contact_reference",
    ):
        assert f"'{key}'" in SQL


def test_registers_development_metadata_source_without_credentials():
    assert "db_airlines_metadata" in SQL
    assert "'mysql'" in SQL
    assert "password" not in SQL
    assert "api_key" not in SQL
