"""Tenant-authorized persistence and review for deterministic semantic mappings.

All writes require a server-resolved AuthenticatedTenantContext and an exact RBAC
permission. Source fields and concept candidates are metadata only; this module never
reads business rows or sends data to an LLM.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import Engine, bindparam, text

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
        "source_metadata": {
            "is_primary_key": bool(getattr(column, "is_primary_key", False)),
            "is_indexed": bool(getattr(column, "is_indexed", False)),
            "nullable": bool(getattr(column, "nullable", True)),
            "foreign_key_targets": list(getattr(column, "foreign_key_targets", ()) or ()),
        },
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


_BULK_APPROVAL_MIN_FIT_SCORE = 0.90
_MAX_BULK_APPROVAL_ITEMS = 100


def _validate_bulk_mapping_ids(mapping_ids: Sequence[int]) -> list[int]:
    """Validate a bounded, unique set of mapping IDs for one atomic bulk action."""
    if isinstance(mapping_ids, (str, bytes)) or not isinstance(mapping_ids, Sequence):
        raise InvalidMappingReview("Bulk mapping IDs must be a list or tuple of integers.")
    ids = list(mapping_ids)
    if not ids:
        raise InvalidMappingReview("Select at least one mapping for bulk approval.")
    if len(ids) > _MAX_BULK_APPROVAL_ITEMS:
        raise InvalidMappingReview(
            f"Bulk approval is limited to {_MAX_BULK_APPROVAL_ITEMS} mappings per transaction."
        )
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in ids):
        raise InvalidMappingReview("Every mapping ID must be a positive integer.")
    if len(set(ids)) != len(ids):
        raise InvalidMappingReview("Duplicate mapping IDs are not allowed in a bulk approval.")
    return ids


def is_bulk_approval_candidate(record: Mapping[str, Any], concept_key: str) -> bool:
    """Return True only for an exact, type-compatible, unambiguous top candidate.

    This is an eligibility filter, not an approval. The human reviewer must still
    inspect the displayed fields, supply concept evidence, and explicitly submit
    the group approval. Partial lexical matches and ambiguous suggestions remain
    in the individual review queue.
    """
    if record.get("mapping_status") != "suggested":
        return False
    details = _json_value(record.get("candidate_details_json")) or {}
    candidates = details.get("candidates", []) if isinstance(details, dict) else []
    if not candidates or not isinstance(candidates, list):
        return False
    top = candidates[0]
    if not isinstance(top, dict):
        return False
    if top.get("concept_key") != concept_key or top.get("type_compatible") is not True:
        return False
    try:
        score = float(top.get("fit_score"))
    except (TypeError, ValueError):
        return False
    if score < _BULK_APPROVAL_MIN_FIT_SCORE:
        return False
    rationale = top.get("rationale") or []
    if not isinstance(rationale, (list, tuple)):
        return False
    exact_markers = (
        "exactly matches the canonical concept key",
        "exactly matches a governed alias",
    )
    return any(
        any(marker in str(reason).lower() for marker in exact_markers)
        for reason in rationale
    )


def is_safe_auto_approval_candidate(record: Mapping[str, Any], concept_key: str) -> bool:
    """Strict, metadata-backed fast path for the source-local contact identifier only.

    KPI concepts (CSAT, NPS, AHT, SLA, offered/handled counts) are deliberately
    excluded because names cannot establish scales, denominators, formulas or grain.
    Contact references qualify only when the source column is an actual primary key.
    """
    if concept_key != "contact_reference":
        return False
    if not is_bulk_approval_candidate(record, concept_key):
        return False
    details = _json_value(record.get("candidate_details_json")) or {}
    metadata = details.get("source_metadata", {}) if isinstance(details, dict) else {}
    return (
        isinstance(metadata, dict)
        and metadata.get("is_primary_key") is True
        and metadata.get("nullable") is False
    )


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
                        ).mappings().one_or_none()
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
                            SELECT mapping_id, mapping_version, mapping_status,
                                   suggested_concept_key, suggested_concept_version,
                                   fit_score, type_compatible, candidate_details_json
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
                        current_payload = _json_value(current.get("candidate_details_json"))
                        current_score = current.get("fit_score")
                        score_matches = (
                            fit_score is None and current_score is None
                        ) or (
                            fit_score is not None
                            and current_score is not None
                            and round(float(current_score), 3) == round(float(fit_score), 3)
                        )
                        current_is_identical = (
                            current_payload == payload
                            and current.get("suggested_concept_key") == suggested_key
                            and current.get("suggested_concept_version") == suggested_version
                            and score_matches
                            and (None if current.get("type_compatible") is None else bool(current.get("type_compatible")))
                                == type_compatible
                        )
                        # Repeated clicks must not create duplicate versions or reset an
                        # already approved/rejected mapping when the discovered metadata is unchanged.
                        if current_is_identical:
                            saved_count += 1
                            continue
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


    def review_mappings_bulk(
        self,
        context: AuthenticatedTenantContext,
        *,
        source_system_id: int,
        mapping_ids: Sequence[int],
        selected_concept_key: str,
        review_evidence: Mapping[str, Any],
        review_mode: str = "explicit_human_bulk_approval",
    ) -> dict[str, Any]:
        """Approve an explicitly selected source group in one atomic transaction.

        Eligibility is revalidated server-side for every row. Each mapping receives
        its own reviewer/timestamp and audit event; any invalid item rolls back the
        complete group. Shared evidence is stored per mapping and must be confirmed
        by the reviewer as applicable to every selected field in the group.
        """
        ids = _validate_bulk_mapping_ids(mapping_ids)
        if isinstance(source_system_id, bool) or not isinstance(source_system_id, int) or source_system_id <= 0:
            raise InvalidMappingReview("source_system_id must be a positive integer.")
        if not isinstance(selected_concept_key, str) or not selected_concept_key.strip() or len(selected_concept_key) > 100:
            raise InvalidMappingReview("Select one valid semantic concept for the group.")
        selected_concept_key = selected_concept_key.strip()

        select_statement = text(
            """
            SELECT mapping_id, mapping_status, candidate_details_json
            FROM tenant_source_field_mappings
            WHERE tenant_id = :tenant_id
              AND source_system_id = :source_system_id
              AND mapping_id IN :mapping_ids
              AND is_current = 1
            ORDER BY mapping_id
            FOR UPDATE
            """
        ).bindparams(bindparam("mapping_ids", expanding=True))

        with self._engine.begin() as connection:
            rows = connection.execute(
                select_statement,
                {
                    "tenant_id": context.tenant_id,
                    "source_system_id": source_system_id,
                    "mapping_ids": ids,
                },
            ).mappings().all()
            if len(rows) != len(ids):
                raise MappingNotFound(
                    "One or more selected mappings are missing, stale, or outside the active company."
                )

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
            required_fields = _json_value(concept["required_approval_fields_json"]) or []
            evidence = _validate_evidence(review_evidence or {}, list(required_fields))

            # Validate the whole group before writing the first row.
            for row in rows:
                record = dict(row)
                record["candidate_details_json"] = _json_value(record.get("candidate_details_json"))
                if not is_bulk_approval_candidate(record, selected_concept_key):
                    raise InvalidMappingReview(
                        f"Mapping {int(row['mapping_id'])} is not eligible for bulk approval. "
                        "Only exact, unambiguous, type-compatible matches can be bulk-approved."
                    )

            batch_reference = uuid4().hex
            approved_ids: list[int] = []
            for row in rows:
                mapping_id = int(row["mapping_id"])
                result = connection.execute(
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
                        WHERE tenant_id = :tenant_id
                          AND source_system_id = :source_system_id
                          AND mapping_id = :mapping_id
                          AND is_current = 1
                          AND mapping_status = 'suggested'
                        """
                    ),
                    {
                        "concept_key": selected_concept_key,
                        "concept_version": int(concept["concept_version"]),
                        "evidence": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                        "membership_id": context.membership_id,
                        "tenant_id": context.tenant_id,
                        "source_system_id": source_system_id,
                        "mapping_id": mapping_id,
                    },
                )
                if result.rowcount != 1:
                    raise InvalidMappingReview(
                        f"Mapping {mapping_id} changed during review; no mappings in this batch were committed."
                    )
                _insert_audit_event(
                    connection,
                    context,
                    action_code="semantic_mapping.bulk_approved",
                    target_reference=str(mapping_id),
                    details={
                        "batch_reference": batch_reference,
                        "source_system_id": source_system_id,
                        "mapping_id": mapping_id,
                        "concept_key": selected_concept_key,
                        "review_mode": review_mode,
                        "shared_evidence_applied": True,
                    },
                )
                approved_ids.append(mapping_id)

        return {
            "decision": "approve",
            "tenant_id": context.tenant_id,
            "source_system_id": source_system_id,
            "concept_key": selected_concept_key,
            "batch_reference": batch_reference,
            "approved_count": len(approved_ids),
            "mapping_ids": tuple(approved_ids),
        }

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


    def save_and_approve_safe_exact_matches(
        self,
        context: AuthenticatedTenantContext,
        *,
        source_system_id: int,
        profile: DatabaseSchemaProfile,
    ) -> dict[str, Any]:
        """Persist the latest schema suggestions and approve the safe exact PK match.

        This is the one-action workflow requested for the Company Admin. It requires
        both review and approve permissions, persists every field suggestion, then
        approves only exact, unambiguous, type-compatible `contact_reference` matches
        whose source column is a non-null primary key. KPI/business mappings remain
        pending for later governed definition; no KPI formula is inferred or approved.
        """
        tenant_id = self._authorization.require_permission(context, "mapping.review")
        self._authorization.require_permission(context, "mapping.approve")
        saved = self._repository.save_suggestions(
            context,
            tenant_id=tenant_id,
            source_system_id=source_system_id,
            profile=profile,
        )
        records = self._repository.list_current_mappings(tenant_id, source_system_id)
        eligible = [
            item for item in records
            if is_safe_auto_approval_candidate(
                item,
                str(item.get("suggested_concept_key") or ""),
            )
        ]
        approved_count = 0
        approved_ids: list[int] = []
        if eligible:
            # Contact-reference evidence is specific to the governed identifier concept.
            # Existing bulk repository API requires a shared evidence object per concept.
            # The evidence text is source-table scoped and all selected fields are PKs.
            shared_evidence = {
                "business_definition": (
                    "Governed Contact Reference: source-local identifier for a contact or interaction; "
                    "approved by the authenticated Company Admin using the explicit exact-match action."
                ),
                "uniqueness_scope": (
                    "Every selected source field is a non-null primary key in its own source table. "
                    "Uniqueness is table-local; no cross-source or cross-tenant uniqueness is asserted."
                ),
                "privacy_review": True,
                "approval_basis": "company_admin_explicit_bulk_exact_primary_key_approval",
                "data_access_scope": "Metadata mapping only; no source values were read or authorized.",
            }
            # Fail closed if a future catalog change adds another required field.
            required_fields = self._repository.get_concept_approval_fields("contact_reference")
            missing = [field for field in required_fields if field not in shared_evidence]
            if missing:
                raise InvalidMappingReview(
                    "Contact-reference approval policy needs an update for: " + ", ".join(missing)
                )
            ids = [int(item["mapping_id"]) for item in eligible]
            result = self._repository.review_mappings_bulk(
                context,
                source_system_id=source_system_id,
                mapping_ids=ids,
                selected_concept_key="contact_reference",
                review_evidence=shared_evidence,
                review_mode="company_admin_one_click_exact_primary_key_approval",
            )
            approved_count = int(result["approved_count"])
            approved_ids.extend(int(value) for value in result["mapping_ids"])
        pending_count = sum(
            1 for item in records
            if item.get("mapping_status") in {"suggested", "ambiguous"}
            and int(item["mapping_id"]) not in approved_ids
        )
        return {
            "saved_count": int(saved.saved_count),
            "approved_count": approved_count,
            "approved_mapping_ids": tuple(approved_ids),
            "pending_count": pending_count,
            "source_system_id": source_system_id,
            "tenant_id": tenant_id,
        }

    def review_mappings_bulk(
        self,
        context: AuthenticatedTenantContext,
        *,
        source_system_id: int,
        mapping_ids: Sequence[int],
        selected_concept_key: str,
        review_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Require RBAC and delegate tenant/source-scoped bulk approval."""
        self._authorization.require_permission(context, "mapping.approve")
        return self._repository.review_mappings_bulk(
            context,
            source_system_id=source_system_id,
            mapping_ids=mapping_ids,
            selected_concept_key=selected_concept_key,
            review_evidence=review_evidence,
        )

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
