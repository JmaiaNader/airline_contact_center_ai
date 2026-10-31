from __future__ import annotations

import csv
import io

import pytest

from src.ingestion.historical_metrics import (
    ALLOWED_COLUMNS,
    HistoricalIngestionError,
    parse_historical_metrics_csv,
)


def make_csv(headers=None, rows=None):
    headers = headers or ["interval_start_utc", "interval_seconds", "channel_code", "offered_contacts", "answered_contacts", "sla_eligible_contacts", "answered_within_threshold_contacts", "total_handle_seconds"]
    rows = rows if rows is not None else [["2026-10-30T06:00:00Z", "900", "voice", "100", "92", "90", "80", "41400"]]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def test_parse_valid_aggregated_interval_csv():
    preview = parse_historical_metrics_csv(make_csv(), "history.csv")
    assert preview.can_import is True
    assert preview.records_received == 1
    row = preview.rows[0]
    assert row["interval_start_utc"].isoformat() == "2026-10-30T06:00:00"
    assert row["interval_seconds"] == 900
    assert row["offered_contacts"] == 100
    assert row["answered_contacts"] == 92


def test_accepts_utf8_bom_and_converts_offset_to_utc():
    payload = make_csv(rows=[["2026-10-30T09:00:00+03:00", "900", "voice", "10", "9", "9", "8", "400"]])
    preview = parse_historical_metrics_csv(b"\xef\xbb\xbf" + payload, "history.csv")
    assert preview.can_import
    assert preview.rows[0]["interval_start_utc"].isoformat() == "2026-10-30T06:00:00"


def test_rejects_naive_timestamp():
    preview = parse_historical_metrics_csv(
        make_csv(rows=[["2026-10-30 06:00:00", "900", "voice", "1", "1", "1", "1", "10"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert "must include a timezone offset" in preview.errors[0]


def test_rejects_zero_interval_length():
    preview = parse_historical_metrics_csv(
        make_csv(rows=[["2026-10-30T06:00:00Z", "0", "voice", "1", "1", "1", "1", "10"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert "interval_seconds must be greater than zero" in preview.errors[0]


def test_rejects_negative_or_decimal_counts():
    for invalid in ("-1", "1.5", "one"):
        preview = parse_historical_metrics_csv(
            make_csv(rows=[["2026-10-30T06:00:00Z", "900", "voice", invalid, "1", "1", "1", "10"]]),
            "history.csv",
        )
        assert not preview.can_import
        assert "whole non-negative integer" in preview.errors[0]


def test_rejects_sla_numerator_above_denominator():
    preview = parse_historical_metrics_csv(
        make_csv(rows=[["2026-10-30T06:00:00Z", "900", "voice", "10", "9", "5", "6", "100"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert "cannot exceed sla_eligible_contacts" in preview.errors[0]


def test_rejects_sla_percentage_above_100():
    headers = ["interval_start_utc", "interval_seconds", "channel_code", "source_reported_sla_percent"]
    preview = parse_historical_metrics_csv(
        make_csv(headers, [["2026-10-30T06:00:00Z", "900", "voice", "100.1"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert "between 0 and 100" in preview.errors[0]


def test_rejects_unknown_columns_to_prevent_unintended_pii_import():
    headers = ["interval_start_utc", "interval_seconds", "channel_code", "customer_email"]
    preview = parse_historical_metrics_csv(
        make_csv(headers, [["2026-10-30T06:00:00Z", "900", "voice", "person@example.test"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert any("Unsupported columns: customer_email" in error for error in preview.errors)


def test_rejects_missing_required_columns():
    headers = ["interval_start_utc", "channel_code"]
    preview = parse_historical_metrics_csv(
        make_csv(headers, [["2026-10-30T06:00:00Z", "voice"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert any("Missing required columns: interval_seconds" in error for error in preview.errors)


def test_rejects_duplicate_headers():
    preview = parse_historical_metrics_csv(
        make_csv(["interval_start_utc", "interval_seconds", "channel_code", "channel_code"], [["2026-10-30T06:00:00Z", "900", "voice", "email"]]),
        "history.csv",
    )
    assert not preview.can_import
    assert "duplicate column names" in preview.errors[0]


def test_records_sha256_for_duplicate_detection():
    payload = make_csv()
    one = parse_historical_metrics_csv(payload, "one.csv")
    two = parse_historical_metrics_csv(payload, "two.csv")
    assert one.content_sha256 == two.content_sha256


def test_template_columns_are_exactly_the_supported_allow_list():
    assert "interval_start_utc" in ALLOWED_COLUMNS
    assert "channel_code" in ALLOWED_COLUMNS
    assert "tenant_id" not in ALLOWED_COLUMNS
    assert "source_system_id" not in ALLOWED_COLUMNS
    assert "customer_email" not in ALLOWED_COLUMNS


def test_blank_rows_are_ignored_and_source_row_number_is_preserved():
    payload = make_csv(rows=[
        ["2026-10-30T06:00:00Z", "900", "voice", "1", "1", "1", "1", "10"],
        ["", "", "", "", "", "", "", ""],
        ["2026-10-30T06:15:00Z", "900", "email", "2", "2", "2", "1", "20"],
    ])
    preview = parse_historical_metrics_csv(payload, "history.csv")
    assert preview.can_import
    assert preview.records_received == 2
    assert preview.rows[0]["__source_row_number"] == 2
    assert preview.rows[1]["__source_row_number"] == 4
