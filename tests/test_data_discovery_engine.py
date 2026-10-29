from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.discovery import approve_mapping, assess_field_mapping, profile_csv
from src.discovery.mapping import MappingAssessment, MappingCandidate


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "synthetic_data"


def test_profiles_csv_schema_and_numeric_range() -> None:
    report = profile_csv(EXAMPLES / "company_a_customer_feedback.csv")

    assert report.rows_profiled == 4
    assert report.truncated is False
    fields = {field.name: field for field in report.fields}
    assert fields["survey_rating"].inferred_type == "integer"
    assert fields["survey_rating"].numeric_min == 3.0
    assert fields["survey_rating"].numeric_max == 5.0
    assert fields["customer_comment"].inferred_type == "text"


def test_equivalent_names_suggest_same_concept_but_never_auto_approve() -> None:
    company_a = profile_csv(EXAMPLES / "company_a_customer_feedback.csv")
    company_b = profile_csv(EXAMPLES / "company_b_customer_feedback.csv")
    fields_a = {field.name: field for field in company_a.fields}
    fields_b = {field.name: field for field in company_b.fields}

    suggestion_a = assess_field_mapping(fields_a["survey_rating"])
    suggestion_b = assess_field_mapping(fields_b["customer_score"])

    assert suggestion_a.status == "suggested"
    assert suggestion_b.status == "suggested"
    assert suggestion_a.candidates[0].concept_key == "customer_satisfaction_score"
    assert suggestion_b.candidates[0].concept_key == "customer_satisfaction_score"
    assert suggestion_a.requires_human_approval is True
    assert suggestion_b.requires_human_approval is True
    # Same candidate concept is only a proposal: ranges differ, so human review is required.
    assert fields_a["survey_rating"].numeric_max == 5.0
    assert fields_b["customer_score"].numeric_max == 10.0


def test_generic_score_field_is_ambiguous(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous_score.csv"
    path.write_text("score\n8\n9\n", encoding="utf-8")
    profile = profile_csv(path)
    assessment = assess_field_mapping(profile.fields[0])
    assert assessment.status == "ambiguous"
    assert len(assessment.candidates) >= 2


def test_unknown_field_remains_unmapped(tmp_path: Path) -> None:
    path = tmp_path / "unknown_field.csv"
    path.write_text("misc_value\nabc\ndef\n", encoding="utf-8")
    profile = profile_csv(path)
    assessment = assess_field_mapping(profile.fields[0])
    assert assessment.status == "unmapped"
    assert assessment.candidates == ()


def test_incompatible_type_is_not_approved(tmp_path: Path) -> None:
    path = tmp_path / "invalid_aht.csv"
    path.write_text("aht_secs\nfast\nslow\n", encoding="utf-8")
    profile = profile_csv(path)
    assessment = assess_field_mapping(profile.fields[0])
    assert assessment.status == "type_mismatch"
    with pytest.raises(ValueError, match="Resolve the data issue"):
        approve_mapping(
            assessment,
            tenant_id="tenant-a",
            source_id="source-a",
            canonical_concept="average_handle_time_seconds",
            approved_by="reviewer@example.test",
            confirmations={"business_definition": True},
        )


def test_cannot_approve_a_non_top_candidate_with_incompatible_type() -> None:
    assessment = MappingAssessment(
        source_field="metric_value",
        inferred_type="text",
        status="suggested",
        candidates=(
            MappingCandidate("customer_feedback_text", "Customer feedback text", 0.94, True, ("exact alias",)),
            MappingCandidate(
                "average_handle_time_seconds",
                "Average handle time (seconds)",
                0.61,
                False,
                ("partial token overlap", "type mismatch"),
            ),
        ),
    )
    confirmations = {
        "business_definition": True, "unit": True, "grain": True, "time_window": True,
        "population": True, "exclusions": True,
    }
    with pytest.raises(ValueError, match="incompatible data type"):
        approve_mapping(
            assessment,
            tenant_id="tenant-a",
            source_id="source-a",
            canonical_concept="average_handle_time_seconds",
            approved_by="reviewer@example.test",
            confirmations=confirmations,
        )


def test_approval_requires_tenant_source_reviewer_and_all_concept_checks() -> None:
    profile = profile_csv(EXAMPLES / "company_a_customer_feedback.csv")
    fields = {field.name: field for field in profile.fields}
    assessment = assess_field_mapping(fields["survey_rating"])
    with pytest.raises(ValueError, match="Human review is incomplete"):
        approve_mapping(
            assessment,
            tenant_id="tenant-a",
            source_id="csv-a",
            canonical_concept="customer_satisfaction_score",
            approved_by="reviewer@example.test",
            confirmations={"business_definition": True, "measurement_scale": True},
        )

    confirmations = {
        "business_definition": True,
        "measurement_scale": True,
        "population": True,
        "time_window": True,
        "exclusions": True,
    }
    approval = approve_mapping(
        assessment,
        tenant_id="tenant-a",
        source_id="csv-a",
        canonical_concept="customer_satisfaction_score",
        approved_by="reviewer@example.test",
        confirmations=confirmations,
    )
    assert approval.tenant_id == "tenant-a"
    assert approval.source_id == "csv-a"
    assert approval.canonical_concept == "customer_satisfaction_score"
    assert approval.approved_by == "reviewer@example.test"
    assert approval.approved_at_utc.endswith("+00:00")


def test_rejects_duplicate_and_blank_headers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("Score,score\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate column names"):
        profile_csv(duplicate)

    blank = tmp_path / "blank.csv"
    blank.write_text("score,\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="blank column name"):
        profile_csv(blank)


def test_max_rows_is_bounded_and_reported(tmp_path: Path) -> None:
    source = tmp_path / "many.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["offered_count"])
        writer.writerows([[1], [2], [3]])

    report = profile_csv(source, max_rows=2)
    assert report.rows_profiled == 2
    assert report.truncated is True
    assert any("coverage is partial" in issue for issue in report.quality_issues)


def test_rejects_invalid_limits(tmp_path: Path) -> None:
    source = tmp_path / "one.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_rows"):
        profile_csv(source, max_rows=0)
    with pytest.raises(ValueError, match="sample_values"):
        profile_csv(source, sample_values=21)
