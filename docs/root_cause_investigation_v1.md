# AeroInsight Root Cause Investigation Engine v1

## Scope

This is a deterministic, read-only analysis layer over `historical_interval_metrics`.
It compares two caller-supplied periods and ranks segment movements by KPI deterioration
and current-period exposure. It is an investigation aid, not a causal inference engine.

The engine does not own or duplicate KPI formulas. The caller must pass the relevant
`MetricDefinition` obtained from the existing central KPI registry (`src/analytics/kpi_definitions.py`).

## Supported metrics

- `sla`: use the central registry definition for SLA.
- `aht`: use the central registry definition for AHT.
- `asa`: use the central registry definition for ASA.
- Additional metrics can be passed from the same central registry.

All calculations aggregate the numerator and denominator fields specified by the central
registry first. Row-level rates are never averaged. Division by zero is rejected. Negative or non-finite values are rejected.

## Segment dimensions

`market_code`, `channel_code`, `service_code`, `service_language_code`.
Segments need at least the configured denominator in both periods. Findings are ranked
by adverse segment movement multiplied by current exposure share. Only segments whose
metric worsened are returned.

## Tenant security

`load_interval_rows` requires a positive tenant ID and binds it in a parameterized SQL
predicate. The caller must derive that tenant ID from a verified `AuthenticatedTenantContext`;
never from a Streamlit widget or arbitrary request parameter. It uses timezone-aware datetime
boundaries and reads only aggregate interval rows.

## Quality and interpretation

If any input row has a `quality_status` other than `valid`, the report is marked
`exploratory`. Synthetic demo data should therefore not be represented as production
performance. The report always sets `causal_claim=false`. A high-ranked segment is an
association warranting investigation, not proof of root cause.

## Integration boundary

This patch adds the pure analysis engine and the read-only repository loader. It deliberately
does not change or duplicate the existing KPI definitions, database schema, OIDC, authorization, or
Streamlit pages. The next integration step should call `load_interval_rows` using the
existing verified tenant context, pass separate baseline/current windows to
`investigate_root_causes`, and render the returned report.
