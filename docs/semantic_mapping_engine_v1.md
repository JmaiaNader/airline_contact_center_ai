# AeroInsight — Semantic Mapping & Approval Engine v1

## Scope

Stage 3 turns the deterministic mapping suggestions from Data Discovery into a governed, tenant-scoped, versioned review workflow.

It is deliberately **LLM-free**. Column names and SQL types can rank candidate concepts, but the ranking score is a heuristic—not a probability and not proof of business equivalence.

## Database migration

`database/migrations/004_semantic_mapping_registry.sql` targets the existing `db_airlines` database and creates:

- `semantic_concepts`: shared, versioned canonical concept definitions and the evidence required for approval.
- `tenant_source_field_mappings`: tenant/source/field mapping history, candidate details, version, approval/rejection status, creator/reviewer membership and evidence.

The migration also registers `db_airlines_metadata` as a development MySQL metadata source for `demo_airline`, if it does not already exist. It stores no credentials or connection strings.

Run `004_preflight.sql`, execute Migration 004 once, then run `004_postflight.sql`. MySQL DDL implicitly commits. If execution fails part-way, inspect the resulting objects; do not rerun the migration blindly.

## Tenant isolation and permissions

- Every mapping row contains `tenant_id` and `source_system_id`.
- A composite foreign key guarantees that the source belongs to that same tenant.
- Creator and reviewer membership references are composite `(tenant_id, membership_id)` foreign keys.
- Every repository query filters by the server-resolved `AuthenticatedTenantContext.tenant_id`.
- Generating/persisting suggestions requires `mapping.review`.
- Viewing source mapping records requires `mapping.view`.
- Approving/rejecting a mapping requires `mapping.approve`.
- Approval/rejection and its `audit_events` record are written in the same database transaction.
- The repository rejects UI-provided tenant identifiers; it accepts the tenant only from the verified context.

OIDC login and first-user provisioning must be configured before an operator can obtain this context. Without that verified context, the Streamlit page remains preview-only; it never invents a tenant or user.

## Versioning

Each source field is identified by tenant, source system, schema, table and column. Every newly generated scan increments `mapping_version`. The previous current record is retained as `superseded`; only one current row per source field is allowed by a generated-column unique key.

Approval records:

- selected concept and concept version,
- reviewer membership and timestamp,
- required semantic evidence (definition, scale/unit, population, grain, formula/denominator/threshold/time window/exclusions/privacy as appropriate),
- an audit event.

Rejecting a suggestion requires a human-readable reason. An approved mapping is not silently overwritten: a later scan creates a new version and retains the earlier approval in history.

## Data handling boundary

This stage reads schema metadata, not customer/contact rows. It stores field names, concept candidates, rationale and business-definition evidence. Do not put passenger/customer records, booking references, emails, phone numbers, tokens, API keys or passwords into review evidence.

No LLM is called. No arbitrary SQL is generated from the model. Future source connectors must use their own approved connection configuration and tenant boundaries.

## Current limitation

The development database is the platform database `db_airlines`. Its schema discovery is useful to test the engine but is not the same as connecting a company's external production data warehouse. External database, CSV and Excel ingestion connectors will be added as separate controlled source adapters.
