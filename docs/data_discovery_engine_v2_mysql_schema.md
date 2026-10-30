# AeroInsight Data Discovery Engine — Stage 2 (MySQL schema metadata)

## Purpose

Extend the existing deterministic CSV profiler and semantic mapper with a read-only connector for the configured relational database. The current development database is `db_airlines`.

## What this stage does

- Uses SQLAlchemy inspection APIs to enumerate tables, columns, SQL types, nullability, primary keys, indexes, and foreign-key targets.
- Runs the discovery against the schema name loaded from trusted application settings (`DB_NAME`), not a schema name submitted by a user interface.
- Converts SQLAlchemy types into the existing governed type vocabulary and reuses `assess_field_mapping` to suggest semantic concepts.
- Displays metadata and heuristic mapping suggestions in the Streamlit Data Discovery page.

## What this stage does not do

- It does not select business rows, comments, passenger information, booking references, or other customer data.
- It does not write to MySQL, create source-system records, create mapping approvals, or execute generated SQL.
- It does not call an LLM. Mapping scores remain heuristic rankings and never prove business equivalence.
- It does not make a tenant access decision. This page is intended for a local developer inspecting the configured development schema. Before exposing discovery to multiple production tenants, the connector must be invoked through a server-resolved `AuthenticatedTenantContext`, checked for the relevant permission, and scoped to the tenant's registered source.

## Run

From the project root with `.venv` active:

```powershell
python -m pytest tests/test_mysql_schema_discovery.py -q
streamlit run app/main.py
```

Open **Data Discovery** from Streamlit's multipage navigation and select **Inspect database schema**.

## Security boundary

The only schema allowed is the exact schema configured in `DB_NAME` (currently `db_airlines`). Schema names are validated and compared against the trusted setting. Optional table filters are checked against tables returned by SQLAlchemy's inspector. The implementation uses no user-provided SQL identifiers and does not read source-table records.

## Next stage

Add a tenant-authorized source registry and a versioned `source_field_mappings` store. Persisting and approving mappings must require `mapping.review` / `mapping.approve`, record the reviewer membership, and write an audit event transactionally. This must be integrated only after OIDC identity resolution and tenant membership provisioning are configured.
