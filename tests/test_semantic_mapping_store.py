from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.discovery.semantic_mapping_store import (
    InvalidMappingReview,
    SemanticMappingRepository,
    SemanticMappingService,
    _assessment_payload,
    _validate_evidence,
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
        email_normalized="analyst@example.test",
        display_name="Analyst",
        identity_provider_code="test_idp",
        issuer_url="https://idp.example.test",
        subject_id="subject-7",
        role_codes=frozenset({"analyst"}),
        permission_codes=frozenset({"mapping.view", "mapping.review", "mapping.approve"}),
    )


class FakeAuthorization:
    def __init__(self, *, denied: set[str] | None = None):
        self.denied = denied or set()
        self.required: list[str] = []

    def require_permission(self, context, permission_code):
        self.required.append(permission_code)
        if permission_code in self.denied:
            raise PermissionDenied(permission_code)
        return context.tenant_id


class FakeRepository:
    def __init__(self):
        self.saved = None
        self.reviewed = None

    def list_active_sources(self, tenant_id):
        return (tenant_id,)

    def save_suggestions(self, context, **kwargs):
        self.saved = (context, kwargs)
        return SimpleNamespace(saved_count=4, tenant_id=kwargs["tenant_id"])

    def list_current_mappings(self, tenant_id, source_system_id):
        return ({"tenant_id": tenant_id, "source_system_id": source_system_id},)

    def review_mapping(self, context, **kwargs):
        self.reviewed = (context, kwargs)
        return {"mapping_id": kwargs["mapping_id"], "decision": kwargs["decision"]}


def test_service_requires_mapping_review_before_persisting():
    auth = FakeAuthorization()
    repo = FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)
    profile = SimpleNamespace(schema_name="db_airlines", tables=())

    result = service.save_suggestions(_context(), source_system_id=5, profile=profile)

    assert auth.required == ["mapping.review"]
    assert repo.saved[1]["tenant_id"] == 3
    assert repo.saved[1]["source_system_id"] == 5
    assert result.saved_count == 4


def test_service_denies_persistence_without_mapping_review():
    auth = FakeAuthorization(denied={"mapping.review"})
    repo = FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)

    with pytest.raises(PermissionDenied):
        service.save_suggestions(
            _context(), source_system_id=5,
            profile=SimpleNamespace(schema_name="db_airlines", tables=()),
        )
    assert repo.saved is None


def test_service_requires_mapping_approve_before_review():
    auth = FakeAuthorization()
    repo = FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)

    result = service.review_mapping(
        _context(), mapping_id=12, decision="reject", rejection_reason="Wrong business meaning"
    )
    assert auth.required == ["mapping.approve"]
    assert repo.reviewed[1]["mapping_id"] == 12
    assert result["decision"] == "reject"


def test_service_denies_review_without_mapping_approve():
    auth = FakeAuthorization(denied={"mapping.approve"})
    repo = FakeRepository()
    service = SemanticMappingService(None, repository=repo, authorization_service=auth)

    with pytest.raises(PermissionDenied):
        service.review_mapping(
            _context(), mapping_id=12, decision="reject", rejection_reason="Wrong meaning"
        )
    assert repo.reviewed is None


def test_evidence_requires_every_concept_confirmation():
    with pytest.raises(InvalidMappingReview, match="missing"):
        _validate_evidence({"business_definition": "CSAT"}, ["business_definition", "measurement_scale"])


def test_evidence_requires_explicit_true_for_privacy_review():
    with pytest.raises(InvalidMappingReview, match="checked"):
        _validate_evidence(
            {"business_definition": "Customer comment", "privacy_review": False},
            ["business_definition", "privacy_review"],
        )


def test_evidence_rejects_oversized_values():
    with pytest.raises(InvalidMappingReview, match="2000"):
        _validate_evidence({"business_definition": "x" * 2001}, ["business_definition"])


def test_repository_rejects_tenant_context_mismatch_before_database_access():
    repo = SemanticMappingRepository(None)
    with pytest.raises(PermissionError, match="does not match"):
        repo.save_suggestions(
            _context(), tenant_id=99, source_system_id=5,
            profile=SimpleNamespace(schema_name="db_airlines", tables=()),
        )


def test_assessment_payload_preserves_human_approval_boundary():
    candidate = SimpleNamespace(
        concept_key="customer_satisfaction_score",
        display_name="Customer satisfaction score",
        fit_score=0.9,
        type_compatible=True,
        rationale=("Alias match",),
    )
    assessment = SimpleNamespace(
        status="suggested",
        source_field="survey_rating",
        inferred_type="integer",
        candidates=(candidate,),
        limitations=("Needs human confirmation",),
    )
    payload = _assessment_payload(SimpleNamespace(mapping=assessment))
    assert payload["requires_human_approval"] is True
    assert payload["candidates"][0]["concept_key"] == "customer_satisfaction_score"
    assert payload["candidates"][0]["type_compatible"] is True


class _FakeMappingResult:
    def __init__(self, *, tuple_row=None, mapping_row=None):
        self.tuple_row = tuple_row
        self.mapping_row = mapping_row

    def first(self):
        return self.tuple_row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.mapping_row

    def one(self):
        if self.mapping_row is None:
            raise AssertionError("Expected one mapping row")
        return self.mapping_row


class _FakeMappingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "SELECT source_system_id" in sql and "FROM source_systems" in sql:
            # The source lookup intentionally uses .first(); this path only checks existence.
            return _FakeMappingResult(tuple_row=(5,))
        if "SELECT concept_version" in sql and "FROM semantic_concepts" in sql:
            # SQLAlchemy .first() exposes a tuple-like Row; .mappings() exposes keys.
            return _FakeMappingResult(
                tuple_row=(3,), mapping_row={"concept_version": 3}
            )
        if "SELECT mapping_id, mapping_version" in sql:
            return _FakeMappingResult(mapping_row=None)
        if "SELECT COALESCE(MAX(mapping_version)" in sql:
            return _FakeMappingResult(mapping_row={"max_version": 0})
        return _FakeMappingResult()


class _FakeBeginContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeMappingEngine:
    def __init__(self):
        self.connection = _FakeMappingConnection()

    def begin(self):
        return _FakeBeginContext(self.connection)


def test_save_suggestions_reads_concept_version_as_mapping_row():
    """Regression: SQLAlchemy Row from .first() is tuple-like, not string-keyed."""
    candidate = SimpleNamespace(
        concept_key="customer_satisfaction_score",
        display_name="Customer satisfaction score",
        fit_score=0.94,
        type_compatible=True,
        rationale=("Alias match",),
    )
    assessment = SimpleNamespace(
        status="suggested",
        source_field="survey_rating",
        inferred_type="integer",
        candidates=(candidate,),
        limitations=("Confirm scale and population",),
    )
    column = SimpleNamespace(column_name="survey_rating", mapping=assessment)
    table = SimpleNamespace(table_name="customer_feedback", columns=(column,))
    profile = SimpleNamespace(schema_name="db_airlines", tables=(table,))

    engine = _FakeMappingEngine()
    repository = SemanticMappingRepository(engine)
    summary = repository.save_suggestions(
        _context(), tenant_id=3, source_system_id=5, profile=profile
    )

    assert summary.saved_count == 1
    insert_calls = [
        (sql, params)
        for sql, params in engine.connection.statements
        if "INSERT INTO tenant_source_field_mappings" in sql
    ]
    assert len(insert_calls) == 1
    assert insert_calls[0][1]["suggested_concept_version"] == 3
