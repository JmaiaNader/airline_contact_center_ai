from __future__ import annotations

from src.discovery.semantic_mapping_store import (
    InvalidMappingReview,
    SemanticMappingService,
    _validate_bulk_mapping_ids,
    is_bulk_approval_candidate,
)
from src.harness.auth_models import AuthenticatedTenantContext
from src.harness.exceptions import PermissionDenied


def _context() -> AuthenticatedTenantContext:
    return AuthenticatedTenantContext(
        user_id=7,
        membership_id=19,
        tenant_id=3,
        tenant_code="demo_airline",
        tenant_display_name="Demo Airline",
        email_normalized="admin@example.test",
        display_name="Admin",
        identity_provider_code="test_idp",
        issuer_url="https://idp.example.test",
        subject_id="subject-7",
        role_codes=frozenset({"company_admin"}),
        permission_codes=frozenset({"mapping.view", "mapping.review", "mapping.approve"}),
    )


def _record(
    *,
    status: str = "suggested",
    score: float = 0.94,
    compatible: bool = True,
    rationale: str = "Source field exactly matches a governed alias.",
    concept_key: str = "average_handle_time_seconds",
):
    return {
        "mapping_status": status,
        "candidate_details_json": {
            "candidates": [
                {
                    "concept_key": concept_key,
                    "display_name": "Average handle time (seconds)",
                    "fit_score": score,
                    "type_compatible": compatible,
                    "rationale": [rationale],
                }
            ]
        },
    }


def test_exact_compatible_unambiguous_alias_is_bulk_eligible():
    assert is_bulk_approval_candidate(_record(), "average_handle_time_seconds") is True


def test_canonical_concept_key_exact_match_is_bulk_eligible():
    record = _record(
        score=0.98,
        rationale="Source field exactly matches the canonical concept key.",
    )
    assert is_bulk_approval_candidate(record, "average_handle_time_seconds") is True


def test_partial_token_overlap_is_not_bulk_eligible():
    record = _record(
        score=0.75,
        rationale="Partial token overlap (75%); review the meaning manually.",
    )
    assert is_bulk_approval_candidate(record, "average_handle_time_seconds") is False


def test_ambiguous_suggestion_is_not_bulk_eligible():
    assert is_bulk_approval_candidate(
        _record(status="ambiguous"), "average_handle_time_seconds"
    ) is False


def test_type_incompatible_suggestion_is_not_bulk_eligible():
    assert is_bulk_approval_candidate(
        _record(compatible=False), "average_handle_time_seconds"
    ) is False


def test_low_score_suggestion_is_not_bulk_eligible():
    assert is_bulk_approval_candidate(
        _record(score=0.89), "average_handle_time_seconds"
    ) is False


def test_non_top_or_different_concept_is_not_bulk_eligible():
    assert is_bulk_approval_candidate(
        _record(), "customer_satisfaction_score"
    ) is False


def test_bulk_ids_require_nonempty_unique_positive_integers():
    assert _validate_bulk_mapping_ids([3, 1, 2]) == [3, 1, 2]
    for invalid in ([], [1, 1], [0], [-1], [True], "1,2"):
        try:
            _validate_bulk_mapping_ids(invalid)  # type: ignore[arg-type]
        except InvalidMappingReview:
            pass
        else:
            raise AssertionError(f"Expected invalid mapping IDs to be rejected: {invalid!r}")


def test_bulk_ids_are_bounded_to_one_hundred_per_transaction():
    try:
        _validate_bulk_mapping_ids(list(range(1, 102)))
    except InvalidMappingReview as exc:
        assert "100" in str(exc)
    else:
        raise AssertionError("Expected more than 100 IDs to be rejected")


class _FakeAuthorization:
    def __init__(self, denied: set[str] | None = None):
        self.denied = denied or set()
        self.required: list[str] = []

    def require_permission(self, context, permission_code):
        self.required.append(permission_code)
        if permission_code in self.denied:
            raise PermissionDenied(permission_code)
        return context.tenant_id


class _FakeRepository:
    def __init__(self):
        self.bulk_call = None

    def review_mappings_bulk(self, context, **kwargs):
        self.bulk_call = (context, kwargs)
        return {
            "decision": "approve",
            "tenant_id": context.tenant_id,
            "concept_key": kwargs["selected_concept_key"],
            "approved_count": len(kwargs["mapping_ids"]),
            "mapping_ids": tuple(kwargs["mapping_ids"]),
        }


def test_service_requires_mapping_approve_and_delegates_bulk_action():
    auth = _FakeAuthorization()
    repo = _FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)
    evidence = {"business_definition": "Average call handling duration"}

    result = service.review_mappings_bulk(
        _context(),
        source_system_id=5,
        mapping_ids=[10, 11],
        selected_concept_key="average_handle_time_seconds",
        review_evidence=evidence,
    )

    assert auth.required == ["mapping.approve"]
    assert repo.bulk_call[1]["source_system_id"] == 5
    assert repo.bulk_call[1]["mapping_ids"] == [10, 11]
    assert result["approved_count"] == 2


def test_service_denies_bulk_action_without_mapping_approve():
    auth = _FakeAuthorization(denied={"mapping.approve"})
    repo = _FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)

    try:
        service.review_mappings_bulk(
            _context(),
            source_system_id=5,
            mapping_ids=[10],
            selected_concept_key="average_handle_time_seconds",
            review_evidence={"business_definition": "Average call handling duration"},
        )
    except PermissionDenied:
        pass
    else:
        raise AssertionError("Bulk approval must require mapping.approve")

    assert repo.bulk_call is None
