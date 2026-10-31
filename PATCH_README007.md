# AeroInsight — Evidence Engine Readiness v1

Additive patch. Uses the existing `db_airlines` database and Migration 004 registry. **No new migration and no database schema changes.**

## Files

- `src/evidence/__init__.py`
- `src/evidence/readiness.py`
- `app/pages/7_Evidence_Engine.py`
- `tests/test_evidence_readiness.py`
- `docs/evidence_engine_readiness_v1.md`

## Install

Extract the ZIP into the project root, preserving paths. Review `git status --short`.

## Test

```powershell
python -m pytest tests/test_evidence_readiness.py -q
python -m pytest -q
```

## Run

```powershell
python -m streamlit run app/main.py
```

Open **7 — Evidence Engine**. Sign in with Google and select the active company. The page uses the existing `SemanticMappingService`; it requires `mapping.view` and never trusts a tenant ID from the browser.

## Scope / limitation

This is a readiness and lineage report, not a KPI calculator. It only counts current approved mappings with a selected concept, review timestamp and non-empty review evidence. It does not read source business rows, query customer/contact data, call an LLM, or modify MySQL. A metric marked `mapping_complete` still requires separate data-quality and formula validation before calculation.

No credentials or local `.env` / `.streamlit/secrets.toml` files belong in this patch or Git.
