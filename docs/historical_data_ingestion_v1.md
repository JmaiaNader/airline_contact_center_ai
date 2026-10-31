# Historical Data Ingestion v1

## Purpose

Load aggregated contact-centre interval metrics into the existing `historical_interval_metrics` table in `db_airlines`. This patch adds no migration and does not change the database schema.

## Access control

The Streamlit page requires a server-resolved `AuthenticatedTenantContext` and `data_source.manage`. Tenant ID, source system ID, ingestion batch ID, quality status, and source row number are assigned by the backend; they are not accepted from the CSV.

## CSV format

Required columns:

- `interval_start_utc`: ISO-8601 timestamp with timezone; use `Z` for UTC. Non-zero offsets are converted to UTC.
- `interval_seconds`: positive whole number (for example, 900 for 15 minutes).
- `channel_code`: existing shared channel code in `channels`.

Optional dimensions:

- `market_code`: existing shared market code.
- `service_code`: existing service code belonging to the active tenant.
- `queue_id`: existing queue ID belonging to the active tenant and matching the row's channel/service.
- `service_language_code`: existing language code.

Optional aggregate measures:

- `offered_contacts`, `answered_contacts`, `handled_contacts`, `abandoned_contacts`
- `sla_eligible_contacts`, `answered_within_threshold_contacts`
- `total_handle_seconds`, `total_answer_wait_seconds`
- `source_reported_aht_seconds`, `source_reported_asa_seconds`, `source_reported_sla_percent`

Source-reported averages and percentages are retained for reconciliation only. Canonical KPI results must be recalculated from governed numerators/denominators and central KPI definitions.

## Server-controlled fields

The importer sets `tenant_id`, `source_system_id`, `ingestion_batch_id`, `source_row_number`, `quality_status='unreviewed'`, `quality_notes_json`, and `created_at_utc`. These columns must not appear in the CSV.

## Validation and safety

- UTF-8 CSV, maximum 25 MB and 100,000 records.
- All rows are validated before writing. Any validation issue rejects the entire file; no partial metric rows are loaded.
- Only allow-listed aggregate fields are accepted. Customer or passenger identifiers and personal-data columns are rejected as unsupported headers.
- Values are checked for integer/decimal ranges, positive interval length, SLA numerator <= denominator, known reference codes, tenant-scoped services and queues, and queue/channel/service consistency.
- The importer creates an idempotent source registry entry `contact_center_historical_csv` of type `csv` for the active tenant if it does not exist.
- Each file receives a SHA-256 fingerprint. An identical file cannot be imported twice for the same tenant/source.
- Each successful file creates an `ingestion_batches` row and inserts all metric records in one DB transaction, then writes an audit event.
- Imported metric rows start as `quality_status='unreviewed'`. Basic import validation is not the same as business-data certification.
- Database timestamps are stored as UTC. Session timezone remains `+00:00`.

## Existing development reference data

The current `markets`, `languages`, and `channels` catalogs are used for FK validation. The user's current development database has zero `services` and zero `queues` rows; therefore leave `service_code` and `queue_id` blank until those tenant reference records have been configured.

## Run

```powershell
python -m pytest tests/test_historical_ingestion.py -q
python -m pytest -q
python -m streamlit run app/main.py
```

Open **8 — Historical Data Ingestion**, download the template, upload an aggregated interval export, validate it, and then explicitly import it. The page does not generate synthetic metrics or claim that imported values are production data.
