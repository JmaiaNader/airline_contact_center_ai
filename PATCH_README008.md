# AeroInsight — Deterministic KPI Engine v1

Additive patch for the existing `airline_contact_center_ai` project.

## Files

- `src/analytics/__init__.py`
- `src/analytics/kpi_definitions.py` — the single executable source of truth for KPI formulas.
- `src/analytics/kpi_engine.py` — tenant-scoped, read-only aggregation and deterministic calculations.
- `app/pages/9_KPI_Analysis.py` — Streamlit KPI results, trends and data-quality view.
- `tests/test_kpi_engine.py`
- `docs/deterministic_kpi_engine_v1.md`

## Database impact

No SQL migration is included. No database objects or rows are changed. The engine reads
from the existing `db_airlines.historical_interval_metrics`, `ingestion_batches` and
`source_systems` tables. It requires an authenticated tenant context with `kpi.view`.

## KPI rules

Formulas live only in `src/analytics/kpi_definitions.py`. Ratios are calculated from
summed numerators and denominators, never by averaging interval percentages. Source-
reported averages/percentages are ignored for canonical KPIs. Targets are separate
from formulas and remain unset by default.

The generated 2026 data is synthetic. The UI labels it clearly and marks results as
not production-eligible. This patch does not relabel or modify the underlying rows.

## Install

Extract the ZIP into the project root, preserving folder structure. It adds the KPI
analysis page and analytics modules without replacing existing authentication,
configuration, discovery, ingestion or semantic mapping files.

## Test

```powershell
python -m pytest tests/test_kpi_engine.py -q
python -m pytest -q
```

## Run

```powershell
python -m streamlit run app/main.py
```

Open `9 — KPI Analysis`.
