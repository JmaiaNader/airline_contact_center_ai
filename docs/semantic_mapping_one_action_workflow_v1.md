# AeroInsight — One-action Semantic Mapping Workflow v1

## Purpose
Replace the multi-form mapping approval screen with one Company Admin action that persists all current metadata suggestions and approves only a narrow, deterministic safe subset.

## One action
`Save & approve safe exact matches` calls the tenant-authorized service. It requires both `mapping.review` and `mapping.approve`, saves the current schema profile, then examines current mappings for the selected tenant and source.

## Auto-approval boundary
Only `contact_reference` is eligible in this version, and only when:
- status is `suggested`;
- the first candidate is an exact canonical-key or governed-alias match;
- data type is compatible;
- fit score is at least 0.90;
- the discovered source column is a non-null primary key.

This is a source-local identifier mapping. The stored uniqueness evidence explicitly limits uniqueness to the source table and makes no cross-source or cross-tenant uniqueness claim. The admin's one-click action records the privacy-review acknowledgement for metadata mapping only; it does not authorize reading or exposing source values.

KPI and business measure concepts (CSAT, NPS, QA, AHT, SLA, Offered, Handled) are persisted as suggestions but remain pending. Names alone cannot establish scale, formula, denominator, threshold, grain, population, exclusions or time window. Free-text feedback also remains pending due to privacy classification requirements.

## Persistence and audit
- All mappings are scoped to the authenticated tenant and selected source.
- The schema profile is metadata-only; no source business rows are queried.
- The approval path uses the existing mapping review transaction and records reviewer membership, UTC timestamp, concept version and audit event.
- Repeated saves are idempotent when the discovered payload is unchanged; current approved/rejected records are not reset or re-versioned.
- No schema migration is required. Existing `db_airlines` Migration 004 tables are used.

## Files
- `app/pages/6_Semantic_Mapping.py`
- `src/discovery/semantic_mapping_store.py`
- `tests/test_semantic_mapping_fast_approval.py`

## Install
Extract the ZIP at the repository root, preserving paths. No SQL script or new database is required.

## Test
```powershell
python -m pytest tests/test_semantic_mapping_store.py tests/test_semantic_mapping_bulk_approval.py tests/test_semantic_mapping_fast_approval.py -q
python -m pytest -q
```
