# AeroInsight Root Cause Investigation Engine v1

## Files
- `src/analytics/root_cause_engine.py`
- `src/analytics/root_cause_repository.py`
- `tests/test_root_cause_engine.py`
- `tests/test_root_cause_repository.py`
- `docs/root_cause_investigation_v1.md`

## Install
Extract the ZIP into the project root, preserving folders.

## Test
```powershell
python -m pytest tests/test_root_cause_engine.py tests/test_root_cause_repository.py -q
```

## Safety
- Uses existing `db_airlines`; no migration.
- Repository is SELECT-only and tenant-filtered.
- Tenant ID must come from verified tenant context.
- No LLM-authored SQL or KPI formulas. The caller supplies metric specs from the centralized KPI registry; this patch does not duplicate KPI definitions.
- Results are associations, not proof of causality.
- Synthetic/non-valid quality rows produce `analysis_class=exploratory`.

This patch adds the computation and repository layer only. Streamlit page wiring is a separate next step because it must match the current project's exact page and service interfaces.
