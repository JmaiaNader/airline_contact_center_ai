# AeroInsight Evidence Engine — Readiness v1

## Purpose

This first Evidence Engine milestone creates a governed readiness view over already-approved semantic mappings. It does **not** calculate KPIs or read customer/contact rows.

## Data flow

1. OIDC verifies the person and creates a server-side `AuthenticatedTenantContext`.
2. `SemanticMappingService.list_sources()` enforces `mapping.view` and lists only sources belonging to the active tenant.
3. `SemanticMappingService.list_current_mappings()` retrieves current mappings for the selected tenant/source.
4. `build_readiness_report()` counts only records whose `mapping_status` is `approved`, whose selected concept and review timestamp exist, and whose review-evidence JSON is non-empty.
5. The page shows concept coverage for CSAT, NPS, AHT, Service Level, offered/handled contacts, and a combined contact-volume capability.

## Safety and correctness boundaries

- No client-supplied `tenant_id` is accepted. Tenant scope comes from the server-resolved authentication context.
- Pending, ambiguous, rejected, malformed or incomplete approvals never contribute to coverage.
- The page reads mapping metadata only. It does not query contact/customer/passenger rows, execute generated SQL, call an LLM, or change database state.
- `mapping_complete` means the required concepts have approved field mappings. It does **not** mean a KPI is analytically ready or that a KPI value may be calculated.
- Before KPI execution, a separate deterministic validation stage must verify source-row availability, source grain, population, units, timezone, time window, formula, denominator, thresholds, exclusions and data quality.
- Export contains only mapping lineage metadata, not source values, review evidence, credentials or user tokens.

## Database

No migration is required. This page uses existing Migration 004 tables through the existing `SemanticMappingService` and `db_airlines` connection.

## Run

```powershell
python -m streamlit run app/main.py
```

Open **7 — Evidence Engine**. Sign in through Google and select the active company. Users need `mapping.view`. If no approved mappings exist, the page shows zero approved coverage and directs the reviewer to the Semantic Mapping page; it does not invent readiness.

## Next milestone

After the source is connected to actual operational records and mappings are approved, implement deterministic source profiling and KPI execution contracts. Every resulting claim must carry its source field lineage, mapping version, time window and calculation definition.
