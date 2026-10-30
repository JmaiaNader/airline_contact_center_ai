from __future__ import annotations

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, event

from src.discovery.mysql_schema import inspect_database_schema


def _build_sqlite_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "tenants",
        metadata,
        Column("tenant_id", Integer, primary_key=True),
        Column("tenant_code", String(64), nullable=False, unique=True),
    )
    Table(
        "customer_feedback",
        metadata,
        Column("feedback_id", Integer, primary_key=True),
        Column("tenant_id", Integer, ForeignKey("tenants.tenant_id"), nullable=False),
        Column("survey_rating", Integer, nullable=True),
        Column("customer_comment", String(255), nullable=True),
    )
    metadata.create_all(engine)
    return engine


def test_inspects_schema_columns_without_reading_business_rows():
    engine = _build_sqlite_engine()
    inspected_statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        inspected_statements.append(statement.lower())

    profile = inspect_database_schema(
        engine,
        schema_name="main",
        expected_schema="main",
    )

    assert profile.table_count == 2
    assert profile.column_count == 6
    feedback = next(table for table in profile.tables if table.table_name == "customer_feedback")
    assert feedback.has_tenant_id is True
    rating = next(column for column in feedback.columns if column.column_name == "survey_rating")
    assert rating.inferred_type == "integer"
    assert rating.mapping.status == "suggested"
    assert rating.mapping.candidates[0].concept_key == "customer_satisfaction_score"
    tenant_id = next(column for column in feedback.columns if column.column_name == "tenant_id")
    assert tenant_id.foreign_key_targets == ("main.tenants.tenant_id",)
    assert not any("from customer_feedback" in sql for sql in inspected_statements)
    engine.dispose()


def test_rejects_schema_other_than_configured_schema():
    engine = _build_sqlite_engine()
    with pytest.raises(PermissionError, match="configured database"):
        inspect_database_schema(engine, schema_name="other_db", expected_schema="main")
    engine.dispose()


def test_rejects_unknown_table_filter():
    engine = _build_sqlite_engine()
    with pytest.raises(ValueError, match="not present"):
        inspect_database_schema(
            engine,
            schema_name="main",
            expected_schema="main",
            table_names=("not_a_real_table",),
        )
    engine.dispose()


def test_rejects_invalid_schema_identifier():
    engine = _build_sqlite_engine()
    with pytest.raises(ValueError, match="invalid format"):
        inspect_database_schema(engine, schema_name="main; DROP TABLE users", expected_schema="main")
    engine.dispose()
