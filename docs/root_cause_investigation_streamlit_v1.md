# AeroInsight Root Cause Investigation — Streamlit Integration v1

## What this patch adds
- `app/pages/11_Root_Cause_Investigation.py`: UI for comparing a baseline window with a non-overlapping current window.
- `src/analytics/root_cause_service.py`: orchestration layer that obtains tenant ID from `AuthenticatedTenantContext`, derives numerator/denominator from the central `KPI_DEFINITIONS`, and runs the existing deterministic root-cause algorithm.
- Updated `src/analytics/root_cause_repository.py`: read-only SQL is scoped by authenticated tenant, selected active source ID, explicit UTC dates, and loaded ingestion batches only.

## Database
Uses the existing `db_airlines` database and existing `historical_interval_metrics`, `source_systems`, and `ingestion_batches` tables. No migration or write operation is added.

## Authorization
The page requires `kpi.view`. The tenant ID is derived with `context.require_permission("kpi.view")`; it is never accepted from a widget. Sources are listed through `KPIAnalysisService.list_sources(context)` and the query binds both tenant ID and source ID.

## Analysis
Supported ratio KPIs are sourced from `src/analytics/kpi_definitions.py`:
- Service Level: lower is adverse
- AHT: higher is adverse
- ASA: higher is adverse
- Abandonment Rate: higher is adverse
- Answer Rate: lower is adverse

Formula fields and numerator/denominator are not duplicated. The service only adds adverse-direction metadata. Baseline and current windows are UTC, date-inclusive, and must not overlap. Only rows belonging to loaded interval ingestion batches are used.

The engine ranks adverse segment movements by adverse change multiplied by current exposure share. Findings are associations, not proof of causality. Non-valid quality statuses make the report exploratory. Synthetic demo sources are explicitly labelled.

## Install
Extract the ZIP into the project root, preserving folder paths.

## Tests
```powershell
python -m pytest tests/test_root_cause_engine.py tests/test_root_cause_repository.py tests/test_root_cause_service.py -q
```
Then run the full suite:
```powershell
python -m pytest -q
```

## Run
```powershell
python -m streamlit run app/main.py
```
Open `11 — Root Cause Investigation`.

## Important
This patch adds the Streamlit wiring for the existing root-cause engine. It does not prove causal relationships, modify KPI formulas, write to MySQL, or add a migration.
