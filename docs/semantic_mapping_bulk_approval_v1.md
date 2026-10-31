# Semantic Mapping Bulk Approval v1

## Objective
Reduce repetitive human review while preserving tenant isolation, explicit authorization, semantic evidence, and per-mapping auditability.

## Workflow
1. Schema discovery generates deterministic suggestions.
2. Suggestions are persisted per tenant/source/schema/table/column and mapping version.
3. The review UI groups only exact, unambiguous and type-compatible top matches by semantic concept.
4. The reviewer inspects the field list and may remove individual rows from the selected group.
5. The reviewer supplies the active concept's required approval evidence once for the group.
6. The reviewer explicitly confirms that this same evidence/business definition applies to every selected field.
7. The batch is approved atomically. Every mapping row is updated independently and receives an audit event.
8. Partial, ambiguous, low-score, and non-exact suggestions remain in individual review.

## Eligibility policy
- `mapping_status == 'suggested'`
- top candidate concept equals the group concept
- `type_compatible is True`
- `fit_score >= 0.90`
- rationale contains an exact canonical-key or governed-alias match marker

The score remains a heuristic rank, not a calibrated probability. This policy only reduces the candidate set; it does not approve anything automatically.

## Authorization and transaction semantics
The service requires `mapping.approve`. The repository scopes lookups to the authenticated tenant and locks every selected current mapping. It validates all selected records, the active concept, and required evidence before applying updates. All updates and audit rows share a single transaction. Any invalid/stale/cross-tenant selection causes a rollback of the batch.

A maximum of 100 mappings is allowed per batch. Each mapping stores selected concept/version, evidence, reviewer membership and UTC review timestamp. Each mapping receives its own `audit_events` entry, with a common `batch_reference` in the JSON details.

## Persistence
Uses the existing `semantic_concepts`, `tenant_source_field_mappings`, `tenant_memberships`, and `audit_events` tables in `db_airlines`. No migration is required.

## Boundaries
- No automatic LLM approval.
- No bulk approval of ambiguous, partial lexical, type-incompatible, or low-score candidates.
- Shared evidence is only valid when the reviewer confirms it genuinely applies to all selected fields.
- KPI concepts still require business definition, scale/unit, grain, population, time window, formulas/denominators and exclusions according to the concept's required fields.
