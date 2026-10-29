from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = PROJECT_ROOT / "database" / "migrations" / "001_create_core_schema.sql"


def _sql_without_comments(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*--.*$", "", text)
    return text


def test_migration_targets_expected_schema_and_creates_eight_core_tables() -> None:
    sql = _sql_without_comments(MIGRATION)
    assert re.search(r"\bUSE\s+`?db_airlines`?\s*;", sql, re.IGNORECASE)

    tables = re.findall(r"CREATE\s+TABLE\s+`(\w+)`", sql, re.IGNORECASE)
    assert tables == [
        "markets",
        "languages",
        "channels",
        "services",
        "queues",
        "bookings",
        "contact_interactions",
        "sla_rules",
    ]


def test_all_core_tables_use_innodb() -> None:
    sql = _sql_without_comments(MIGRATION)
    create_statements = re.split(r"CREATE\s+TABLE\s+`\w+`", sql, flags=re.IGNORECASE)[1:]
    assert len(create_statements) == 8
    for statement in create_statements:
        assert re.search(r"\bENGINE\s*=\s*InnoDB\b", statement, re.IGNORECASE)


def test_market_dimension_and_market_scoped_sla_are_present() -> None:
    sql = _sql_without_comments(MIGRATION)
    assert "`reporting_timezone`" in sql
    assert re.search(r"`market_code`[^,]*NULL", sql, re.IGNORECASE)
    assert "FOREIGN KEY (`market_code`) REFERENCES `markets` (`market_code`)" in sql
    assert "UNIQUE KEY `uq_sla_rule_queue_market_start` (`queue_id`, `market_code`, `effective_from_utc`)" in sql


def test_interaction_integrity_and_indexes_are_present() -> None:
    sql = _sql_without_comments(MIGRATION)
    expected = [
        "uq_interactions_conversation_leg",
        "fk_interactions_queue_channel",
        "fk_interactions_booking",
        "chk_interactions_conversation_leg",
        "chk_interactions_answered_after_offered",
        "ix_interactions_market_offered",
    ]
    for token in expected:
        assert token in sql


def test_migration_has_no_destructive_or_seed_statements() -> None:
    sql = _sql_without_comments(MIGRATION)
    assert not re.search(r"\bDROP\s+(DATABASE|TABLE)\b", sql, re.IGNORECASE)
    assert not re.search(r"\bTRUNCATE\s+TABLE\b", sql, re.IGNORECASE)
    assert not re.search(r"\bINSERT\s+INTO\b", sql, re.IGNORECASE)
    assert not re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS", sql, re.IGNORECASE)
