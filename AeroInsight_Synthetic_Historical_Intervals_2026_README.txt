AeroInsight Synthetic Historical Interval Dataset - 2026

SQL file: AeroInsight_Synthetic_Historical_Intervals_2026.sql

Target: existing db_airlines database
Period: 2026-01-01 00:00 UTC through 2026-10-31 23:45 UTC
Grain: 15-minute intervals, 24x7
Segments: 8 market/channel/language combinations
Expected rows: 233,472

IMPORTANT: This is deterministic SYNTHETIC DEMO DATA. It is not actual airline
operational history and must not be presented as real CSAT/SLA/AHT performance.
Rows are marked quality_status='warning' and production_eligible=false in
quality_notes_json. The demo SLA denominator is offered_contacts; this does not
change AeroInsight's canonical KPI definition.

No new database, permanent table, or migration is created. The script uses the
existing tenants, source_systems, ingestion_batches, audit_events, markets,
channels, languages and historical_interval_metrics tables. It leaves
service_code and queue_id NULL because services/queues were previously empty.

Execution:
1. Open the .sql file in MySQL Workbench.
2. Verify that the target schema is db_airlines.
3. Execute the script once.
4. Review the final three result grids. Expected rows: 233472. Status: loaded.

The script is designed to be re-runnable for this same batch: it reuses the same
source and batch, and inserts only missing source_row_number values. Do not edit
the generator's date range or parameters while keeping the same version/hash;
use a new source/batch version if you later change the generated dataset.
