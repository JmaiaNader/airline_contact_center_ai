# AeroInsight Deterministic KPI Engine v1

## Purpose

This stage calculates contact-centre KPIs from the existing canonical
`db_airlines.historical_interval_metrics` table. It is read-only and requires a
server-resolved `AuthenticatedTenantContext` with `kpi.view`.

## Single source of truth

Executable KPI definitions are centralized in:

- `src/analytics/kpi_definitions.py`

Pages and future services must consume `KPI_DEFINITIONS`; they must not duplicate
formula arithmetic. KPI targets are separate from formulas. A missing target remains
unconfigured and must never change the calculation.

## Canonical formulas

| KPI | Formula | Unit |
|---|---|---|
| Offered Contacts | `SUM(offered_contacts)` | contacts |
| Answered Contacts | `SUM(answered_contacts)` | contacts |
| Handled Contacts | `SUM(handled_contacts)` | contacts |
| Abandoned Contacts | `SUM(abandoned_contacts)` | contacts |
| Service Level | `100 * SUM(answered_within_threshold_contacts) / SUM(sla_eligible_contacts)` | % |
| AHT | `SUM(total_handle_seconds) / SUM(handled_contacts)` | seconds |
| ASA | `SUM(total_answer_wait_seconds) / SUM(answered_contacts)` | seconds |
| Abandonment Rate | `100 * SUM(abandoned_contacts) / SUM(offered_contacts)` | % |
| Answer Rate | `100 * SUM(answered_contacts) / SUM(offered_contacts)` | % |

Ratios are weighted across the selected period and filters. The engine never averages
interval percentages or source-reported averages. `source_reported_aht_seconds`,
`source_reported_asa_seconds`, and `source_reported_sla_percent` are not used as
canonical calculation inputs.

The Service Level denominator is the stored `sla_eligible_contacts` field. The
engine does not change that field or assume a new SLA target. Tenant targets are
separate configuration and are currently unconfigured by default.

## Data scope and security

- Tenant ID is obtained only from `AuthenticatedTenantContext`; it is never accepted
  from a widget or query parameter.
- Source IDs are checked against the active tenant before analysis.
- SQL values are bound parameters. Trend expressions are selected from a fixed
  `day` / `month` allow-list.
- Only aggregate query results are returned to the UI; the engine does not expose
  contact-, passenger-, agent-, booking- or customer-level rows.
- The engine is read-only. No Migration, INSERT, UPDATE or DELETE is part of this patch.

## Synthetic demo data

The 2026 demo interval dataset is explicitly synthetic and has
`production_eligible=false` in its ingestion metadata and `quality_status='warning'`.
The engine still calculates results so the dashboard can be exercised, but it labels
all such results as synthetic demo and `production_eligible=false`. They must not be
reported as actual airline performance.

## Unsupported metrics

CSAT, NPS, FCR, occupancy, forecast accuracy and agent-level measures are not derived
from this table. They need separate approved sources and/or additional canonical
fields. The engine reports this limitation rather than inventing values.

## Run

```powershell
python -m pytest tests/test_kpi_engine.py -q
python -m pytest -q
python -m streamlit run app/main.py
```

Open page `9 — KPI Analysis`, choose a loaded source, select UTC date range and optional
market/channel/language filters, then inspect KPIs, trend and data-quality checks.
