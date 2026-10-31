from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "database" / "migrations" / "005_wfm_workforce_foundation.sql"
SQL = SQL_PATH.read_text(encoding="utf-8")

EXPECTED_TABLES = {
    "employees",
    "workforce_skills",
    "employee_skills",
    "workforce_shifts",
    "workforce_shift_activities",
    "queue_skill_requirements",
    "workforce_agent_state_events",
}


def test_targets_only_db_airlines():
    assert re.search(r"(?im)^USE\s+`db_airlines`\s*;", SQL)
    assert not re.search(r"(?im)^USE\s+`(?!db_airlines`)[^`]+`", SQL)


def test_creates_all_seven_workforce_tables():
    created = set(re.findall(r"(?i)CREATE\s+TABLE\s+`([a-z0-9_]+)`", SQL))
    assert created == EXPECTED_TABLES


def test_tenant_scope_is_present_on_all_workforce_tables():
    for table in EXPECTED_TABLES:
        match = re.search(
            rf"(?is)CREATE\s+TABLE\s+`{table}`\s*\((.*?)\)\s*ENGINE=InnoDB",
            SQL,
        )
        assert match, table
        assert re.search(r"(?im)^\s*`tenant_id`\s+BIGINT\s+UNSIGNED\s+NOT\s+NULL", match.group(1)), table


def test_employee_skills_use_composite_tenant_foreign_keys():
    block = re.search(
        r"(?is)CREATE\s+TABLE\s+`employee_skills`\s*\((.*?)\)\s*ENGINE=InnoDB",
        SQL,
    ).group(1)
    assert "FOREIGN KEY (`tenant_id`, `employee_id`)" in block
    assert "FOREIGN KEY (`tenant_id`, `skill_id`)" in block


def test_shift_activities_are_linked_to_same_tenant_shift():
    block = re.search(
        r"(?is)CREATE\s+TABLE\s+`workforce_shift_activities`\s*\((.*?)\)\s*ENGINE=InnoDB",
        SQL,
    ).group(1)
    assert "FOREIGN KEY (`tenant_id`, `shift_id`)" in block
    assert "CHECK (`activity_end_utc` > `activity_start_utc`)" in block


def test_queue_requirements_are_tenant_scoped_and_proficiency_bounded():
    block = re.search(
        r"(?is)CREATE\s+TABLE\s+`queue_skill_requirements`\s*\((.*?)\)\s*ENGINE=InnoDB",
        SQL,
    ).group(1)
    assert "FOREIGN KEY (`tenant_id`, `queue_id`)" in block
    assert "FOREIGN KEY (`tenant_id`, `skill_id`)" in block
    assert "BETWEEN 1 AND 5" in block


def test_state_events_are_append_only_and_tenant_scoped():
    block = re.search(
        r"(?is)CREATE\s+TABLE\s+`workforce_agent_state_events`\s*\((.*?)\)\s*ENGINE=InnoDB",
        SQL,
    ).group(1)
    assert "event_at_utc" in block
    assert "external_event_id" in block
    assert "FOREIGN KEY (`tenant_id`, `employee_id`)" in block
    assert "FOREIGN KEY (`tenant_id`, `queue_id`)" in block


def test_utc_is_explicit_and_no_destructive_statements():
    assert "SET SESSION time_zone = '+00:00';" in SQL
    assert not re.search(r"(?i)\bDROP\s+TABLE\b|\bTRUNCATE\b|\bDELETE\s+FROM\b", SQL)


def test_no_employee_or_shift_demo_rows_are_fabricated():
    assert not re.search(r"(?i)INSERT\s+INTO\s+`employees`", SQL)
    assert not re.search(r"(?i)INSERT\s+INTO\s+`workforce_shifts`", SQL)
    assert not re.search(r"(?i)INSERT\s+INTO\s+`workforce_agent_state_events`", SQL)


def test_seeded_skill_catalog_is_idempotent_and_reference_based():
    assert SQL.count("INSERT INTO `workforce_skills`") == 2
    assert SQL.count("AND NOT EXISTS (") >= 2
    assert "CROSS JOIN `languages` AS l" in SQL
    assert "CROSS JOIN `channels` AS c" in SQL
