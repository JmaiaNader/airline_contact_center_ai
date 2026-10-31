from __future__ import annotations

from types import SimpleNamespace

from src.discovery.semantic_mapping_store import (
    SemanticMappingService,
    is_safe_auto_approval_candidate,
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
        identity_provider_code="google_oidc",
        issuer_url="https://accounts.google.com",
        subject_id="google-subject-7",
        role_codes=frozenset({"company_admin"}),
        permission_codes=frozenset({"mapping.view", "mapping.review", "mapping.approve"}),
    )


def _record(*, mapping_id=30, concept="contact_reference", primary_key=True, nullable=False, score=0.94):
    return {
        "mapping_id": mapping_id,
        "mapping_status": "suggested",
        "suggested_concept_key": concept,
        "source_schema_name": "db_airlines",
        "source_table_name": "contact_interactions",
        "source_column_name": "interaction_id",
        "candidate_details_json": {
            "source_metadata": {"is_primary_key": primary_key, "nullable": nullable},
            "candidates": [
                {
                    "concept_key": concept,
                    "fit_score": score,
                    "type_compatible": True,
                    "rationale": ["Source field exactly matches a governed alias."],
                }
            ],
        },
    }


def test_exact_contact_reference_primary_key_is_safe_for_fast_approval():
    assert is_safe_auto_approval_candidate(_record(), "contact_reference") is True


def test_contact_reference_without_primary_key_is_not_auto_approved():
    assert is_safe_auto_approval_candidate(_record(primary_key=False), "contact_reference") is False


def test_nullable_contact_reference_is_not_auto_approved():
    assert is_safe_auto_approval_candidate(_record(nullable=True), "contact_reference") is False


def test_kpi_exact_match_is_never_auto_approved():
    assert is_safe_auto_approval_candidate(
        _record(concept="customer_satisfaction_score"), "customer_satisfaction_score"
    ) is False


def test_low_score_exact_match_is_not_auto_approved():
    assert is_safe_auto_approval_candidate(_record(score=0.89), "contact_reference") is False


class _FakeAuthorization:
    def __init__(self, denied=None):
        self.denied = set(denied or ())
        self.required = []

    def require_permission(self, context, permission_code):
        self.required.append(permission_code)
        if permission_code in self.denied:
            raise PermissionDenied(permission_code)
        return context.tenant_id


class _FakeRepository:
    def __init__(self):
        self.saved = False
        self.bulk_calls = []

    def save_suggestions(self, context, **kwargs):
        self.saved = True
        return SimpleNamespace(saved_count=12)

    def list_current_mappings(self, tenant_id, source_system_id):
        return (
            _record(),
            _record(mapping_id=31, concept="customer_satisfaction_score", primary_key=False),
        )

    def get_concept_approval_fields(self, concept_key):
        assert concept_key == "contact_reference"
        return ("business_definition", "uniqueness_scope", "privacy_review")

    def review_mappings_bulk(self, context, **kwargs):
        self.bulk_calls.append(kwargs)
        ids = tuple(kwargs["mapping_ids"])
        return {"approved_count": len(ids), "mapping_ids": ids}


def test_one_action_saves_all_suggestions_and_approves_only_safe_exact_ids():
    auth = _FakeAuthorization()
    repo = _FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)

    result = service.save_and_approve_safe_exact_matches(
        _context(),
        source_system_id=5,
        profile=SimpleNamespace(schema_name="db_airlines", tables=()),
    )

    assert repo.saved is True
    assert auth.required == ["mapping.review", "mapping.approve"]
    assert len(repo.bulk_calls) == 1
    call = repo.bulk_calls[0]
    assert call["mapping_ids"] == [30]
    assert call["selected_concept_key"] == "contact_reference"
    assert call["review_evidence"]["privacy_review"] is True
    assert call["review_mode"] == "company_admin_one_click_exact_primary_key_approval"
    assert result == {
        "saved_count": 12,
        "approved_count": 1,
        "approved_mapping_ids": (30,),
        "pending_count": 1,
        "source_system_id": 5,
        "tenant_id": 3,
    }


def test_one_action_requires_both_save_and_approve_permissions_before_writing():
    auth = _FakeAuthorization(denied={"mapping.approve"})
    repo = _FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)

    try:
        service.save_and_approve_safe_exact_matches(
            _context(),
            source_system_id=5,
            profile=SimpleNamespace(schema_name="db_airlines", tables=()),
        )
    except PermissionDenied:
        pass
    else:
        raise AssertionError("Expected mapping.approve permission denial")

    assert repo.saved is False
    assert repo.bulk_calls == []
