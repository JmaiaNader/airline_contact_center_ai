"""Deterministic readiness assessment based only on current approved mappings.

This module does not query source/business rows and does not calculate KPIs. It answers
one narrower question: does the selected tenant/source have reviewed mappings for the
canonical concepts required by each initial contact-centre metric?
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CORE_METRIC_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "csat": ("customer_satisfaction_score",),
    "nps": ("net_promoter_score",),
    "aht": ("average_handle_time_seconds",),
    "service_level": ("service_level_pct",),
    "offered_contacts": ("offered_contacts",),
    "handled_contacts": ("handled_contacts",),
    "contact_volume_pair": ("offered_contacts", "handled_contacts"),
}

METRIC_LABELS: dict[str, str] = {
    "csat": "Customer Satisfaction (CSAT)",
    "nps": "Net Promoter Score (NPS)",
    "aht": "Average Handle Time (AHT)",
    "service_level": "Service Level",
    "offered_contacts": "Offered Contacts",
    "handled_contacts": "Handled Contacts",
    "contact_volume_pair": "Contact Volume (offered + handled)",
}

_VALID_APPROVED_STATUSES = {"approved"}
_PENDING_STATUSES = {"suggested", "ambiguous", "unmapped", "type_mismatch"}


@dataclass(frozen=True, slots=True)
class ApprovedFieldBinding:
    mapping_id: int
    source_table: str
    source_column: str
    mapping_version: int
    concept_key: str
    reviewed_at_utc: str


@dataclass(frozen=True, slots=True)
class MetricReadiness:
    metric_key: str
    display_name: str
    required_concepts: tuple[str, ...]
    mapped_concepts: tuple[str, ...]
    missing_concepts: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class EvidenceReadinessReport:
    total_mappings: int
    approved_mappings: int
    pending_mappings: int
    rejected_mappings: int
    invalid_approval_records: int
    approved_concepts: tuple[str, ...]
    approved_bindings: tuple[ApprovedFieldBinding, ...]
    metric_readiness: tuple[MetricReadiness, ...]


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _valid_approval_record(row: Mapping[str, Any]) -> bool:
    concept_key = row.get("selected_concept_key")
    reviewed_at = row.get("reviewed_at_utc")
    evidence = _as_mapping(row.get("review_evidence_json"))
    return (
        isinstance(concept_key, str)
        and bool(concept_key.strip())
        and reviewed_at is not None
        and evidence is not None
        and bool(evidence)
    )


def build_readiness_report(
    records: Sequence[Mapping[str, Any]],
    *,
    metric_requirements: Mapping[str, tuple[str, ...]] = CORE_METRIC_REQUIREMENTS,
) -> EvidenceReadinessReport:
    """Build a conservative report from tenant-scoped current mapping records.

    Only rows with `mapping_status='approved'`, a selected concept, review timestamp,
    and non-empty review evidence contribute to readiness. Suggested, ambiguous,
    rejected, superseded, malformed or incomplete rows never count as approved evidence.
    The caller must obtain records through SemanticMappingService using a verified
    AuthenticatedTenantContext; this function accepts no tenant ID from the UI.
    """
    approved: list[ApprovedFieldBinding] = []
    pending = 0
    rejected = 0
    invalid = 0

    for row in records:
        if not isinstance(row, Mapping):
            invalid += 1
            continue
        status = str(row.get("mapping_status") or "").lower()
        if status in _VALID_APPROVED_STATUSES:
            if not _valid_approval_record(row):
                invalid += 1
                continue
            try:
                mapping_id = int(row["mapping_id"])
                version = int(row["mapping_version"])
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            if mapping_id <= 0 or version <= 0:
                invalid += 1
                continue
            approved.append(
                ApprovedFieldBinding(
                    mapping_id=mapping_id,
                    source_table=str(row.get("source_table_name") or ""),
                    source_column=str(row.get("source_column_name") or ""),
                    mapping_version=version,
                    concept_key=str(row["selected_concept_key"]),
                    reviewed_at_utc=str(row["reviewed_at_utc"]),
                )
            )
        elif status in _PENDING_STATUSES:
            pending += 1
        elif status == "rejected":
            rejected += 1

    approved_concepts = tuple(sorted({item.concept_key for item in approved}))
    concept_set = set(approved_concepts)
    metrics: list[MetricReadiness] = []
    for metric_key, required in metric_requirements.items():
        mapped = tuple(concept for concept in required if concept in concept_set)
        missing = tuple(concept for concept in required if concept not in concept_set)
        metrics.append(
            MetricReadiness(
                metric_key=metric_key,
                display_name=METRIC_LABELS.get(metric_key, metric_key.replace("_", " ").title()),
                required_concepts=tuple(required),
                mapped_concepts=mapped,
                missing_concepts=missing,
                status="mapping_complete" if not missing else "mapping_incomplete",
            )
        )

    approved.sort(key=lambda item: (item.source_table, item.source_column, item.mapping_id))
    return EvidenceReadinessReport(
        total_mappings=len(records),
        approved_mappings=len(approved),
        pending_mappings=pending,
        rejected_mappings=rejected,
        invalid_approval_records=invalid,
        approved_concepts=approved_concepts,
        approved_bindings=tuple(approved),
        metric_readiness=tuple(metrics),
    )


def export_approved_mappings_csv(bindings: Sequence[ApprovedFieldBinding]) -> str:
    """Export a metadata-only register; never includes credentials or source-row values."""
    output = io.StringIO(newline="")
    fields = (
        "mapping_id",
        "source_table",
        "source_column",
        "mapping_version",
        "concept_key",
        "reviewed_at_utc",
    )
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for item in bindings:
        writer.writerow(
            {
                "mapping_id": item.mapping_id,
                "source_table": item.source_table,
                "source_column": item.source_column,
                "mapping_version": item.mapping_version,
                "concept_key": item.concept_key,
                "reviewed_at_utc": item.reviewed_at_utc,
            }
        )
    return output.getvalue()
