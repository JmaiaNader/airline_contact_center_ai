"""Tenant-authorized persistence and review for deterministic semantic mappings.

All writes require a server-resolved AuthenticatedTenantContext and an exact RBAC
permission. Source fields and concept candidates are metadata only; this module never
reads business rows or sends data to an LLM.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import Engine, text

from src.discovery.mysql_schema import DatabaseSchemaProfile
from src.harness.auth_models import AuthenticatedTenantContext
from src.harness.authorization_service import AuthorizationService

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_ALLOWED_DECISIONS = {"approve", "reject"}
_ALLOWED_EVIDENCE_TYPES = (str, int, float, bool)


class SemanticMappingError(RuntimeError):
    """Base exception for semantic mapping persistence or review failures."""


class MappingNotFound(SemanticMappingError):
    """Mapping is missing or is not visible in the active tenant."""


class InvalidMappingReview(SemanticMappingError):
    """Review decision or evidence is invalid."""


@dataclass(frozen=True, slots=True)
class SourceSystemSummary:
    source_system_id: int
    source_code: str
    display_name: str
    source_type: str
    source_status: str


@dataclass(frozen=True, slots=True)
class MappingSaveSummary:
    tenant_id: int
    source_system_id: int
    saved_count: int


def _json_value(value: Any) -> Any:
    """Normalize SQLAlchemy/MySQL JSON values into ordinary Python data."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _assessment_payload(column: Any) -> dict[str, Any]:
    assessment = column.mapping
    candidates = [
        {
            "concept_key": candidate.concept_key,
            "display_name": candidate.display_name,
            "fit_score": float(candidate.fit_score),
            "type_compatible": bool(candidate.type_compatible),
            "rationale": list(candidate.rationale),
        }
        for candidate in assessment.candidates
    ]
    return {
        "status": assessment.status,
        "source_field": assessment.source_field,
        "inferred_type": assessment.inferred_type,
        "requires_human_approval": True,
        "candidates": candidates,
        "limitations": list(assessment.limitations),
    }


def _validate_evidence(evidence: Mapping[str, Any], required_fields: list[str]) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise InvalidMappingReview("Review evidence must be a key/value mapping.")
    normalized: dict[str, Any] = {}
    for key in required_fields:
        if key not in evidence:
            raise InvalidMappingReview(f"Required review evidence is missing: {key}.")
        value = evidence[key]
        if not isinstance(value, _ALLOWED_EVIDENCE_TYPES):
            raise InvalidMappingReview(f"Review evidence '{key}' must be text, numeric, or boolean metadata.")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise InvalidMappingReview(f"Required review evidence is empty: {key}.")
            if len(value) > 2000:
                raise InvalidMappingReview(f"Review evidence '{key}' exceeds 2000 characters.")
        if isinstance(value, bool) and value is not True:
            raise InvalidMappingReview(f"Required confirmation '{key}' must be explicitly checked.")
        normalized[key] = value
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > 8192:
        raise InvalidMappingReview("Review evidence exceeds the 8 KB limit.")
    return normalized


def _insert_audit_event(
    connection: Any,
    context: AuthenticatedTenantContext,
    *,
    action_code: str,
    target_reference: str,
    details: dict[str, Any],
) -> None:
    serialized = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > 4096:
        raise ValueError("Audit metadata exceeds the 4 KB limit.")
    connection.execute(
        text(
            """
            INSERT INTO audit_events (
                tenant_id, actor_membership_id, action_code,
                target_type, target_reference, outcome_code, event_details_json
            ) VALUES (
                :tenant_id, :membership_id, :action_code,
                'semantic_mapping', :target_reference, 'success', :details
            )
            """
        ),
        {
            "tenant_id": context.tenant_id,
            "membership_id": context.membership_id,
            "action_code": action_code,
            "target_reference": target_reference[:128],
            "details": serialized,
        },
    )


class SemanticMappingRepository:
    """Parameterized SQL repository. Every query is scoped to the context tenant."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_active_sources(self, tenant_id: int) -> tuple[SourceSystemSummary, ...]:
        statement = text(
            """
            SELECT source_system_id, source_code, display_name, source_type, source_status
            FROM source_systems
            WHERE tenant_id = :tenant_id AND source_status = 'active'
            ORDER BY display_name, source_system_id
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"tenant_id": tenant_id}).mappings().all()
        return tuple(
            SourceSystemSummary(
                source_system_id=int(row["source_system_id"]),
                source_code=str(row["source_code"]),
                display_name=str(row["display_name"]),
                source_type=str(row["source_type"]),
                source_status=str(row["source_status"]),
            )
            for row in rows
        )

    def save_suggestions(
        self,
        context: AuthenticatedTenantContext,
        *,
        tenant_id: int,
        source_system_id: int,
        profile: DatabaseSchemaProfile,
    ) -> MappingSaveSummary:
        if tenant_id != context.tenant_id:
            raise PermissionError("Tenant context does not match the requested tenant.")
        if not isinstance(source_system_id, int) or isinstance(source_system_id, bool) or source_system_id <= 0:
            raise ValueError("source_system_id must be a positive integer.")
        if not _IDENTIFIER.fullmatch(profile.schema_name):
            raise ValueError("Discovered schema name is invalid.")

        saved_count = 0
        with self._engine.begin() as connection:
            source = connection.execute(
                text(
                    """
                    SELECT source_system_id
                    FROM source_systems
                    WHERE tenant_id = :tenant_id
                      AND source_system_id = :source_system_id
                      AND source_status = 'active'
                    FOR UPDATE
                    """
                ),
                {"tenant_id": tenant_id, "source_system_id": source_system_id},
            ).first()
            if source is None:
                raise MappingNotFound("Active source system was not found in the current company.")

            for table in profile.tables:
                if not _IDENTIFIER.fullmatch(table.table_name):
                    raise ValueError("Discovered table name is invalid.")
                for column in table.columns:
                    if not _IDENTIFIER.fullmatch(column.column_name):
                        raise ValueError("Discovered column name is invalid.")
                    payload = _assessment_payload(column)
                    top = payload["candidates"][0] if payload["candidates"] else None
                    suggested_key = None
                    suggested_version = None
                    fit_score = None
                    type_compatible = None
                    if payload["status"] == "suggested" and top and top["type_compatible"]:
                        suggested_key = top["concept_key"]
                        concept_row = connection.execute(
                            text(
                                """
                                SELECT concept_version
                                FROM semantic_concepts
                                WHERE concept_key = :concept_key AND concept_status = 'active'
                                ORDER BY concept_version DESC LIMIT 1
                                """
                            ),
                            {"concept_key": suggested_key},
                        ).first()
                        if concept_row is not None:
                            suggested_version = int(concept_row["concept_version"])
                        fit_score = top["fit_score"]
                        type_compatible = True
                    elif top:
                        fit_score = top["fit_score"]
                        type_compatible = bool(top["type_compatible"])

                    current = connection.execute(
                        text(
                            """
                            SELECT mapping_id, mapping_version
                            FROM tenant_source_field_mappings
                            WHERE tenant_id = :tenant_id
                              AND source_system_id = :source_system_id
                              AND source_schema_name = :schema_name
                              AND source_table_name = :table_name
                              AND source_column_name = :column_name
                              AND is_current = 1
                            FOR UPDATE
                            """
                        ),
                        {
                            "tenant_id": tenant_id,
                            "source_system_id": source_system_id,
                            "schema_name": profile.schema_name,
                            "table_name": table.table_name,
                            "column_name": column.column_name,
                        },
                    ).mappings().one_or_none()
                    if current:
                        next_version = int(current["mapping_version"]) + 1
                        connection.execute(
                            text(
                                """
                                UPDATE tenant_source_field_mappings
                                SET is_current = 0, mapping_status = 'superseded'
                                WHERE tenant_id = :tenant_id AND mapping_id = :mapping_id
                                """
                            ),
                            {"tenant_id": tenant_id, "mapping_id": int(current["mapping_id"])},
                        )
                    else:
                        version_row = connection.execute(
                            text(
                                """
                                SELECT COALESCE(MAX(mapping_version), 0) AS max_version
                                FROM tenant_source_field_mappings
                                WHERE tenant_id = :tenant_id
                                  AND source_system_id = :source_system_id
                                  AND source_schema_name = :schema_name
                                  AND source_table_name = :table_name
                                  AND source_column_name = :column_name
                                """
                            ),
                            {
                                "tenant_id": tenant_id,
                                "source_system_id": source_system_id,
                                "schema_name": profile.schema_name,
                                "table_name": table.table_name,
                                "column_name": column.column_name,
                            },
                        ).mappings().one()
                        next_version = int(version_row["max_version"]) + 1

                    connection.execute(
                        text(
                            """
                            INSERT INTO tenant_source_field_mappings (
                                tenant_id, source_system_id, source_schema_name,
                                source_table_name, source_column_name, mapping_version,
                                mapping_status, suggested_concept_key, suggested_concept_version,
                                fit_score, type_compatible, candidate_details_json,
                                created_by_membership_id, is_current
                            ) VALUES (
                                :tenant_id, :source_system_id, :schema_name,
                                :table_name, :column_name, :mapping_version,
                                :mapping_status, :suggested_concept_key, :suggested_concept_version,
                                :fit_score, :type_compatible, :candidate_details_json,
                                :membership_id, 1
                            )
                            """
                        ),
                        {
                            "tenant_id": tenant_id,
                            "source_system_id": source_system_id,
                            "schema_name": profile.schema_name,
                            "table_name": table.table_name,
                            "column_name": column.column_name,
                            "mapping_version": next_version,
                            "mapping_status": payload["status"],
                            "suggested_concept_key": suggested_key,
                            "suggested_concept_version": suggested_version,
                            "fit_score": fit_score,
                            "type_compatible": type_compatible,
                            "candidate_details_json": json.dumps(payload, ensure_ascii=False),
                            "membership_id": context.membership_id,
                        },
                    )
                    saved_count += 1

            _insert_audit_event(
                connection,
                context,
                action_code="semantic_mapping.suggestions_saved",
                target_reference=str(source_system_id),
                details={
                    "source_system_id": source_system_id,
                    "schema_name": profile.schema_name,
                    "mapping_count": saved_count,
                },
            )

        return MappingSaveSummary(tenant_id, source_system_id, saved_count)

    def get_concept_approval_fields(self, concept_key: str) -> tuple[str, ...]:
        statement = text(
            """
            SELECT required_approval_fields_json
            FROM semantic_concepts
            WHERE concept_key = :concept_key AND concept_status = 'active'
            ORDER BY concept_version DESC LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"concept_key": concept_key}).mappings().one_or_none()
        if row is None:
            raise MappingNotFound("Active semantic concept was not found.")
        return tuple(_json_value(row["required_approval_fields_json"]) or ())

    def list_current_mappings(self, tenant_id: int, source_system_id: int) -> tuple[dict[str, Any], ...]:
        statement = text(
            """
            SELECT mapping_id, source_schema_name, source_table_name, source_column_name,
                   mapping_version, mapping_status, suggested_concept_key,
                   selected_concept_key, fit_score, type_compatible,
                   candidate_details_json, review_evidence_json, rejection_reason,
                   created_at_utc, reviewed_at_utc
            FROM tenant_source_field_mappings
            WHERE tenant_id = :tenant_id
              AND source_system_id = :source_system_id
              AND is_current = 1
            ORDER BY source_table_name, source_column_name
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement, {"tenant_id": tenant_id, "source_system_id": source_system_id}
            ).mappings().all()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["candidate_details_json"] = _json_value(item.get("candidate_details_json"))
            item["review_evidence_json"] = _json_value(item.get("review_evidence_json"))
            results.append(item)
        return tuple(results)

    def review_mapping(
        self,
        context: AuthenticatedTenantContext,
        *,
        mapping_id: int,
        decision: str,
        selected_concept_key: str | None = None,
        review_evidence: Mapping[str, Any] | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        if decision not in _ALLOWED_DECISIONS:
            raise InvalidMappingReview("Decision must be 'approve' or 'reject'.")
        if isinstance(mapping_id, bool) or not isinstance(mapping_id, int) or mapping_id <= 0:
            raise ValueError("mapping_id must be a positive integer.")
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT * FROM tenant_source_field_mappings
                    WHERE tenant_id = :tenant_id AND mapping_id = :mapping_id AND is_current = 1
                    FOR UPDATE
                    """
                ),
                {"tenant_id": context.tenant_id, "mapping_id": mapping_id},
            ).mappings().one_or_none()
            if row is None:
                raise MappingNotFound("Current mapping was not found in the active company.")
            payload = _json_value(row["candidate_details_json"]) or {}

            if decision == "approve":
                if row["mapping_status"] not in {"suggested", "ambiguous"}:
                    raise InvalidMappingReview("Only suggested or ambiguous mappings can be approved.")
                if not selected_concept_key or len(selected_concept_key) > 100:
                    raise InvalidMappingReview("Select one reviewed semantic concept.")
                candidates = payload.get("candidates", [])
                selected = next(
                    (candidate for candidate in candidates if candidate.get("concept_key") == selected_concept_key),
                    None,
                )
                if not selected or selected.get("type_compatible") is not True:
                    raise InvalidMappingReview("Selected concept is not a compatible candidate for this field.")
                concept = connection.execute(
                    text(
                        """
                        SELECT concept_version, required_approval_fields_json
                        FROM semantic_concepts
                        WHERE concept_key = :concept_key AND concept_status = 'active'
                        ORDER BY concept_version DESC LIMIT 1
                        """
                    ),
                    {"concept_key": selected_concept_key},
                ).mappings().one_or_none()
                if concept is None:
                    raise InvalidMappingReview("Selected semantic concept is not active.")
                required = _json_value(concept["required_approval_fields_json"])
                evidence = _validate_evidence(review_evidence or {}, list(required))
                connection.execute(
                    text(
                        """
                        UPDATE tenant_source_field_mappings
                        SET mapping_status = 'approved',
                            selected_concept_key = :concept_key,
                            selected_concept_version = :concept_version,
                            review_evidence_json = :evidence,
                            reviewed_by_membership_id = :membership_id,
                            reviewed_at_utc = CURRENT_TIMESTAMP(6),
                            rejection_reason = NULL
                        WHERE tenant_id = :tenant_id AND mapping_id = :mapping_id
                        """
                    ),
                    {
                        "concept_key": selected_concept_key,
                        "concept_version": int(concept["concept_version"]),
                        "evidence": json.dumps(evidence, ensure_ascii=False),
                        "membership_id": context.membership_id,
                        "tenant_id": context.tenant_id,
                        "mapping_id": mapping_id,
                    },
                )
                action_code = "semantic_mapping.approved"
                audit_details = {"mapping_id": mapping_id, "concept_key": selected_concept_key}
            else:
                reason = (rejection_reason or "").strip()
                if not reason:
                    raise InvalidMappingReview("A rejection reason is required.")
                if len(reason) > 1000:
                    raise InvalidMappingReview("Rejection reason exceeds 1000 characters.")
                connection.execute(
                    text(
                        """
                        UPDATE tenant_source_field_mappings
                        SET mapping_status = 'rejected',
                            rejection_reason = :reason,
                            reviewed_by_membership_id = :membership_id,
                            reviewed_at_utc = CURRENT_TIMESTAMP(6)
                        WHERE tenant_id = :tenant_id AND mapping_id = :mapping_id
                        """
                    ),
                    {
                        "reason": reason,
                        "membership_id": context.membership_id,
                        "tenant_id": context.tenant_id,
                        "mapping_id": mapping_id,
                    },
                )
                action_code = "semantic_mapping.rejected"
                audit_details = {"mapping_id": mapping_id, "reason_code": "human_rejected"}

            _insert_audit_event(
                connection,
                context,
                action_code=action_code,
                target_reference=str(mapping_id),
                details=audit_details,
            )

        return {"mapping_id": mapping_id, "decision": decision, "tenant_id": context.tenant_id}


class SemanticMappingService:
    """Enforce RBAC before calling the tenant-scoped mapping repository."""

    def __init__(
        self,
        engine: Engine,
        *,
        repository: SemanticMappingRepository | None = None,
        authorization_service: AuthorizationService | None = None,
    ) -> None:
        self._repository = repository or SemanticMappingRepository(engine)
        self._authorization = authorization_service or AuthorizationService(engine)

    def list_sources(self, context: AuthenticatedTenantContext) -> tuple[SourceSystemSummary, ...]:
        tenant_id = self._authorization.require_permission(context, "mapping.view")
        return self._repository.list_active_sources(tenant_id)

    def save_suggestions(
        self,
        context: AuthenticatedTenantContext,
        *,
        source_system_id: int,
        profile: DatabaseSchemaProfile,
    ) -> MappingSaveSummary:
        tenant_id = self._authorization.require_permission(context, "mapping.review")
        return self._repository.save_suggestions(
            context,
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            profile=profile,
        )

    def get_concept_approval_fields(
        self, context: AuthenticatedTenantContext, *, concept_key: str
    ) -> tuple[str, ...]:
        self._authorization.require_permission(context, "mapping.view")
        return self._repository.get_concept_approval_fields(concept_key)

    def list_current_mappings(
        self, context: AuthenticatedTenantContext, *, source_system_id: int
    ) -> tuple[dict[str, Any], ...]:
        tenant_id = self._authorization.require_permission(context, "mapping.view")
        return self._repository.list_current_mappings(tenant_id, source_system_id)

    def review_mapping(
        self,
        context: AuthenticatedTenantContext,
        *,
        mapping_id: int,
        decision: str,
        selected_concept_key: str | None = None,
        review_evidence: Mapping[str, Any] | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        self._authorization.require_permission(context, "mapping.approve")
        return self._repository.review_mapping(
            context,
            mapping_id=mapping_id,
            decision=decision,
            selected_concept_key=selected_concept_key,
            review_evidence=review_evidence,
            rejection_reason=rejection_reason,
        )
