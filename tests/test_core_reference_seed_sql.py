from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED = PROJECT_ROOT / "database" / "seeds" / "001_core_reference_data.sql"


def _sql_without_comments(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*--.*$", "", text)
    return text


def test_seed_includes_three_initial_markets() -> None:
    sql = _sql_without_comments(SEED)
    for market_code in ("QATAR", "USA", "UAE"):
        assert f"SELECT '{market_code}'" in sql


def test_seed_includes_expected_languages_and_channels() -> None:
    sql = _sql_without_comments(SEED)
    for language_code in ("en", "ar", "fr", "und"):
        assert f"SELECT '{language_code}'" in sql
    for channel_code in ("voice", "webchat", "whatsapp", "email", "social_media"):
        assert f"SELECT '{channel_code}'" in sql


def test_seed_is_idempotent_and_does_not_invent_business_sla_data() -> None:
    sql = _sql_without_comments(SEED)
    assert sql.count("WHERE NOT EXISTS") == 12
    assert not re.search(r"INSERT\s+INTO\s+`?(services|queues|sla_rules)`?", sql, re.IGNORECASE)
    assert not re.search(r"DROP\s+(DATABASE|TABLE)|TRUNCATE\s+TABLE", sql, re.IGNORECASE)


def test_us_market_timezone_is_left_unspecified() -> None:
    sql = _sql_without_comments(SEED)
    assert re.search(r"SELECT\s+'USA'\s*,\s*'United States'\s*,\s*'US'\s*,\s*NULL", sql, re.IGNORECASE)
