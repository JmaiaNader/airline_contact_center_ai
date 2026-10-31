from __future__ import annotations

from src.evidence.readiness import build_readiness_report, export_approved_mappings_csv


def _approved(mapping_id=1, concept="customer_satisfaction_score", **overrides):
    row = {
        "mapping_id": mapping_id,
        "source_table_name": "survey_results",
        "source_column_name": "survey_rating",
        "mapping_version": 1,
        "mapping_status": "approved",
        "selected_concept_key": concept,
        "reviewed_at_utc": "2026-10-30 12:00:00.000000",
        "review_evidence_json": {"business_definition": "Survey response score"},
    }
    row.update(overrides)
    return row


def test_only_approved_mappings_contribute_to_readiness():
    report = build_readiness_report(
        [
            _approved(),
            {
                "mapping_id": 2,
                "mapping_version": 1,
                "mapping_status": "suggested",
                "suggested_concept_key": "average_handle_time_seconds",
            },
        ]
    )
    assert report.approved_mappings == 1
    assert report.pending_mappings == 1
    assert report.approved_concepts == ("customer_satisfaction_score",)


def test_approval_without_review_evidence_is_excluded():
    report = build_readiness_report([_approved(review_evidence_json=None)])
    assert report.approved_mappings == 0
    assert report.invalid_approval_records == 1
    assert "customer_satisfaction_score" not in report.approved_concepts


def test_approval_without_review_timestamp_is_excluded():
    report = build_readiness_report([_approved(reviewed_at_utc=None)])
    assert report.approved_mappings == 0
    assert report.invalid_approval_records == 1


def test_rejected_mapping_never_counts_as_approved():
    report = build_readiness_report(
        [{"mapping_status": "rejected", "rejection_reason": "Wrong definition"}]
    )
    assert report.rejected_mappings == 1
    assert report.approved_mappings == 0


def test_csat_is_mapping_complete_only_when_approved_concept_exists():
    report = build_readiness_report([_approved()])
    csat = next(item for item in report.metric_readiness if item.metric_key == "csat")
    assert csat.status == "mapping_complete"
    assert csat.missing_concepts == ()


def test_contact_volume_requires_both_offered_and_handled_concepts():
    report = build_readiness_report(
        [_approved(1, "offered_contacts")]
    )
    volume = next(item for item in report.metric_readiness if item.metric_key == "contact_volume_pair")
    assert volume.status == "mapping_incomplete"
    assert volume.missing_concepts == ("handled_contacts",)


def test_contact_volume_is_mapping_complete_when_both_concepts_are_approved():
    report = build_readiness_report(
        [_approved(1, "offered_contacts"), _approved(2, "handled_contacts")]
    )
    volume = next(item for item in report.metric_readiness if item.metric_key == "contact_volume_pair")
    assert volume.status == "mapping_complete"


def test_current_rejected_and_pending_counts_are_separate():
    rows = [
        _approved(),
        {"mapping_status": "ambiguous"},
        {"mapping_status": "unmapped"},
        {"mapping_status": "rejected"},
        {"mapping_status": "superseded"},
    ]
    report = build_readiness_report(rows)
    assert report.total_mappings == 5
    assert report.approved_mappings == 1
    assert report.pending_mappings == 2
    assert report.rejected_mappings == 1


def test_csv_export_contains_lineage_metadata_only():
    report = build_readiness_report([_approved()])
    text = export_approved_mappings_csv(report.approved_bindings)
    assert "survey_results,survey_rating,1,customer_satisfaction_score" in text
    assert "business_definition" not in text
    assert "password" not in text.lower()


def test_duplicate_approved_fields_preserve_both_lineage_records():
    report = build_readiness_report(
        [
            _approved(1, "offered_contacts", source_column_name="offered"),
            _approved(2, "offered_contacts", source_column_name="offered_count"),
        ]
    )
    assert report.approved_mappings == 2
    assert report.approved_concepts == ("offered_contacts",)
    assert len(report.approved_bindings) == 2
