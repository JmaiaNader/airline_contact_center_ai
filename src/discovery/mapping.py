from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from src.discovery.catalog import DEFAULT_SEMANTIC_CATALOG, SemanticConcept, normalize_name
from src.discovery.profiling import FieldProfile


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    concept_key: str
    display_name: str
    fit_score: float
    type_compatible: bool
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappingAssessment:
    source_field: str
    inferred_type: str
    status: str  # suggested | ambiguous | unmapped | type_mismatch
    candidates: tuple[MappingCandidate, ...]
    requires_human_approval: bool = True
    limitations: tuple[str, ...] = (
        "A column name and profile do not prove business equivalence.",
        "Confirm definition, unit/scale, population, grain, time window, and exclusions where applicable.",
    )


@dataclass(frozen=True, slots=True)
class MappingApproval:
    tenant_id: str
    source_id: str
    source_field: str
    canonical_concept: str
    approved_by: str
    approved_at_utc: str
    confirmed_fields: tuple[str, ...]


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _compatible(source_type: str, concept: SemanticConcept) -> bool:
    if source_type == "empty":
        return False
    if source_type == "mixed":
        return False
    expected = set(concept.expected_types)
    if "identifier" in expected and source_type in {"text", "integer"}:
        return True
    if "number" in expected and source_type in {"integer", "number"}:
        return True
    return source_type in expected


def _name_fit(source_name: str, concept: SemanticConcept) -> tuple[float, str]:
    normalized_source = normalize_name(source_name)
    normalized_key = normalize_name(concept.key)
    aliases = tuple(normalize_name(alias) for alias in concept.aliases)
    if normalized_source == normalized_key:
        return 0.96, "Source field exactly matches the canonical concept key."
    if normalized_source in aliases:
        return 0.90, "Source field exactly matches a governed alias."

    source_tokens = _tokens(source_name)
    if not source_tokens:
        return 0.0, "Source field name has no usable tokens."

    best_overlap = 0.0
    for alias in (*aliases, normalized_key):
        alias_tokens = _tokens(alias)
        if not alias_tokens:
            continue
        overlap = len(source_tokens & alias_tokens) / max(len(source_tokens), len(alias_tokens))
        best_overlap = max(best_overlap, overlap)
    if best_overlap < 0.5:
        return 0.0, "No sufficient lexical overlap with the governed catalog."
    score = 0.45 + (0.30 * best_overlap)
    return score, f"Partial token overlap ({best_overlap:.0%}); review the meaning manually."


def assess_field_mapping(
    field: FieldProfile,
    *,
    catalog: Sequence[SemanticConcept] = DEFAULT_SEMANTIC_CATALOG,
    ambiguity_margin: float = 0.08,
    minimum_suggestion_score: float = 0.52,
) -> MappingAssessment:
    """Return explainable mapping candidates. No mapping is accepted automatically.

    `fit_score` is a heuristic ranking score, not a calibrated probability.
    """
    if not 0 <= ambiguity_margin <= 1:
        raise ValueError("ambiguity_margin must be between 0 and 1.")
    if not 0 <= minimum_suggestion_score <= 1:
        raise ValueError("minimum_suggestion_score must be between 0 and 1.")

    candidates: list[MappingCandidate] = []
    for concept in catalog:
        name_score, name_reason = _name_fit(field.name, concept)
        if name_score <= 0:
            continue
        compatible = _compatible(field.inferred_type, concept)
        score = min(0.98, name_score + (0.04 if compatible else -0.28))
        rationale = [name_reason]
        if compatible:
            rationale.append(f"Observed type '{field.inferred_type}' is compatible with the catalog expectation.")
        else:
            rationale.append(
                f"Observed type '{field.inferred_type}' is not compatible with expected type(s): "
                f"{', '.join(concept.expected_types)}."
            )
        candidates.append(
            MappingCandidate(
                concept_key=concept.key,
                display_name=concept.display_name,
                fit_score=round(max(0.0, score), 3),
                type_compatible=compatible,
                rationale=tuple(rationale),
            )
        )

    candidates.sort(key=lambda item: (-item.fit_score, item.concept_key))
    candidates = [item for item in candidates if item.fit_score >= minimum_suggestion_score]
    if not candidates:
        return MappingAssessment(field.name, field.inferred_type, "unmapped", ())

    top = candidates[0]
    if not top.type_compatible:
        status = "type_mismatch"
    elif len(candidates) > 1 and (top.fit_score - candidates[1].fit_score) <= ambiguity_margin:
        status = "ambiguous"
    else:
        status = "suggested"

    return MappingAssessment(
        source_field=field.name,
        inferred_type=field.inferred_type,
        status=status,
        candidates=tuple(candidates[:5]),
    )


def approve_mapping(
    assessment: MappingAssessment,
    *,
    tenant_id: str,
    source_id: str,
    canonical_concept: str,
    approved_by: str,
    confirmations: Mapping[str, bool],
    catalog: Sequence[SemanticConcept] = DEFAULT_SEMANTIC_CATALOG,
) -> MappingApproval:
    """Create an auditable approval only after tenant/source and required checks are supplied."""
    for label, value in (("tenant_id", tenant_id), ("source_id", source_id), ("approved_by", approved_by)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string.")

    candidate_by_key = {candidate.concept_key: candidate for candidate in assessment.candidates}
    if assessment.status in {"unmapped", "type_mismatch"}:
        raise ValueError(f"Cannot approve a mapping with status '{assessment.status}'. Resolve the data issue first.")
    selected_candidate = candidate_by_key.get(canonical_concept)
    if selected_candidate is None:
        raise ValueError("The selected concept is not one of the reviewed candidates for this field.")
    if not selected_candidate.type_compatible:
        raise ValueError("The selected candidate has an incompatible data type; resolve the data issue first.")

    concept_by_key = {concept.key: concept for concept in catalog}
    concept = concept_by_key.get(canonical_concept)
    if concept is None:
        raise ValueError("The selected concept is not present in the active semantic catalog.")

    missing = [key for key in concept.required_approval_fields if confirmations.get(key) is not True]
    if missing:
        raise ValueError("Human review is incomplete. Confirm these fields before approval: " + ", ".join(missing))

    return MappingApproval(
        tenant_id=tenant_id.strip(),
        source_id=source_id.strip(),
        source_field=assessment.source_field,
        canonical_concept=canonical_concept,
        approved_by=approved_by.strip(),
        approved_at_utc=datetime.now(timezone.utc).isoformat(),
        confirmed_fields=tuple(concept.required_approval_fields),
    )
