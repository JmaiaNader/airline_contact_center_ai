# Database Schema v1 — `db_Airlines`

**Status: design proposal for review. Not executable SQL. Do not create tables directly from this document.**

## 1. Scope and operating assumptions

- MySQL with InnoDB and `utf8mb4`.
- Reporting defaults to `Asia/Qatar`; persist event timestamps in UTC and convert only for display/reporting.
- Raw interaction data is the source of truth. Calculate KPI values deterministically in SQL/Python. Do not save duplicate KPI values in a raw interaction row.
- Initial operational reporting grain is a 30-minute interval. Raw interactions retain exact timestamps; create rollups only if measured query performance requires them.
- Initial channels: `voice`, `webchat`, `whatsapp`, `email`, and `social_media`. SLA semantics are channel-specific; do not apply live-call SLA calculations blindly to asynchronous channels.
- Supported language codes initially include `en`, `ar`, and `fr`. Employee UI language, interaction/service language, and source policy language are different concepts.
- **Market is a reporting/operational dimension** such as Qatar, USA, or UAE. In this version, it identifies the market attributed to a contact interaction for queue and KPI analysis. It is not the employee's language, the passenger's nationality, or automatically the booking origin/destination.
- If a source later uses “Market” to mean booking sales/POS market, model that separately on `bookings`; do not silently reuse the contact's operational market.
- Do not store unnecessary passenger PII. The first version uses synthetic booking references and limited booking details.
- Database migrations are reviewed and run manually by a developer/DBA, never by the LLM or Streamlit UI.

## 2. Core tables for migration 001

### `markets`

Purpose: canonical list of operational/reporting markets used to segment interactions, SLA rules, and later forecasts/workforce reporting.

- `market_code` — primary key, stable internal code; initial seeded values: `QATAR`, `USA`, `UAE`.
- `market_name` — display name, e.g. `Qatar`, `United States`, `United Arab Emirates`.
- `country_code` — nullable ISO 3166-1 alpha-2 country code where applicable, e.g. `QA`, `US`, `AE`. Keep this separate from the internal market code.
- `default_time_zone` — optional IANA time zone for market-local operational displays; the platform's default reporting time zone remains `Asia/Qatar` unless a report explicitly requests market-local time.
- `is_active` — whether the market can be selected for new records.

Market seed data is reference data and should be inserted by a reviewed seed script/migration, not by the LLM. Do not assume that every future market must map one-to-one to a country; airline business markets may later represent a region or sales territory.

### `languages`

Purpose: canonical language codes used by interactions and later policy versions/agent-language skills.

- `language_code` — primary key, short BCP-47-style code (`en`, `ar`, `fr`).
- `display_name` — readable language name.
- `is_active` — whether the code can be newly selected.

### `channels`

Purpose: normalize channel taxonomy and record whether a channel is synchronous.

- `channel_code` — primary key (`voice`, `webchat`, `whatsapp`, `email`, `social_media`).
- `display_name`.
- `is_synchronous` — indicates whether live answer/wait and Erlang C assumptions normally apply; validate exceptions per channel/queue.
- `is_active`.

### `services`

Purpose: business service/domain such as `existing_booking`, `Refund_Tickets`, or `General_ENQ`.

- `service_code` — primary key.
- `display_name`.
- `is_active`.

### `queues`

Purpose: an operational queue with a stable business code.

- `queue_id` — primary key.
- `queue_code` — unique stable code.
- `queue_name`.
- `service_code` — foreign key to `services`.
- `channel_code` — foreign key to `channels`.
- `is_active`.

A queue is associated with a channel and business service. Market is stored on each interaction because a shared queue may serve multiple markets. The actual service language is also captured on the interaction, not inferred from employee UI language or queue name.

### `bookings`

Purpose: minimum booking context required for support lookup.

- `booking_id` — primary key.
- `booking_reference` — normalized uppercase reference, unique in this initial single-source demo.
- `booking_status` — controlled value such as `confirmed`, `cancelled`, `ticketed`, or `unknown`; validate in application code.
- `scheduled_departure_utc` — nullable UTC timestamp.
- `origin_airport_code` / `destination_airport_code` — nullable IATA-style codes when available.
- `created_at_utc`, `updated_at_utc`.

Do not add passenger names, passport numbers, contact details, payment data, or full PNR contents unless an approved requirement and access-control design requires them. If multiple booking source systems are integrated later, add `source_system` and make uniqueness `(source_system, booking_reference)`. A booking sales/POS market is a separate concept from the operational market of a contact interaction and should be added as a separate field only if required.

### `contact_interactions`

**Grain: one offered contact leg to one queue.** If a contact is transferred and offered to another queue, record a separate queue leg and link it through `conversation_reference` plus `queue_leg_number`.

- `interaction_id` — primary key.
- `conversation_reference` — opaque reference grouping queue legs for the same contact; no passenger PII.
- `queue_leg_number` — positive leg sequence within a conversation.
- `market_code` — nullable foreign key to `markets`; use `NULL` only when source data does not identify the market. Never guess it.
- `channel_code` — foreign key to `channels`.
- `queue_id` — foreign key to `queues`.
- `service_language_code` — nullable foreign key to `languages`; `NULL` means unknown, not guessed.
- `booking_id` — nullable foreign key to `bookings`.
- `offered_at_utc` — required timestamp used to assign the offered contact to an interval.
- `answered_at_utc` — nullable first-answer/first-response timestamp, interpreted alongside the channel's SLA rule.
- `ended_at_utc` — nullable end timestamp.
- `abandoned_at_utc` — nullable timestamp for a true abandonment where applicable.
- `talk_seconds`, `hold_seconds`, `after_contact_work_seconds` — nullable non-negative durations; do not silently treat missing values as zero.
- `created_at_utc` — ingestion timestamp.

Application validation must ensure duration values are non-negative, timestamps are logically ordered, channel/queue compatibility is valid, and `(conversation_reference, queue_leg_number)` is unique when a conversation reference is supplied. Do not use employee response language as `service_language_code`, and do not infer `market_code` from language, airport route, or employee location unless the source's business definition explicitly says to do so.

### `sla_rules`

Purpose: versioned SLA rules scoped by queue and market so historical reports use the rule effective at the time of the interaction.

- `sla_rule_id` — primary key.
- `queue_id` — foreign key to `queues`.
- `market_code` — foreign key to `markets`.
- `measurement_mode` — controlled value: `answer_within_target` for synchronous/live work, or `first_response_within_target` for asynchronous work.
- `response_target_seconds` — response threshold in seconds.
- `target_service_level_pct` — configured operational target, numeric 0–100.
- `short_abandon_seconds` — threshold for short-abandon treatment where supported.
- `exclude_short_abandons` — whether short abandons are excluded from the eligible denominator.
- `effective_from_utc` — start of validity.
- `effective_to_utc` — nullable exclusive end of validity.
- `definition_version` — version label for governance/report annotation.

Use a uniqueness rule over `(queue_id, market_code, effective_from_utc)`. Application-level validation and tests must reject overlapping effective periods for the same queue and market. If multiple markets share the same SLA target, seed equivalent market-specific rules rather than adding ambiguous wildcard behavior in v1. For asynchronous channels, define eligible offers, responses, and closed/abandoned cases before enabling SLA reporting.

## 3. Later migrations (not in migration 001)

Implement these when the relevant feature is ready, rather than creating empty tables without a clear owner and tested use case:

- **Workforce:** pseudonymous agent references, language skills, and interval-level rostered/productive/planned/unplanned time. Add market attribution at the actual grain of the roster/assignment; an agent may support multiple markets. Keep agent PII out of analytics tables.
- **Forecasting:** `forecast_runs` (model/version, horizon, training cutoff, parameters, status) and `forecast_results` (target interval, metric, prediction, optional lower/upper bounds, queue, market, and service-language dimensions). Preserve predictions separately from actuals.
- **Policy metadata:** `policy_documents` and `policy_versions` with source language, approval state, effective dates, checksum, ingestion status, and source path/reference. Policy files stay in the document store; embeddings/chunks stay in a vector store with stable source metadata.
- **Governance:** `audit_logs` with actor/tool/action/outcome/time and minimal non-sensitive metadata, plus `evaluation_runs` for reproducible test/evaluation summaries.
- **Interval rollups:** add only after query profiling. Uniqueness must include the full grain: market, queue, channel/service (as applicable), service language, interval start, interval duration, and metric-definition/rule version.

## 4. Relationships

- `markets` 1-to-many `contact_interactions` and `sla_rules`; later it may dimension workforce assignments and forecast results.
- `services` 1-to-many `queues`.
- `channels` 1-to-many `queues` and `contact_interactions`.
- `queues` 1-to-many `contact_interactions` and `sla_rules`.
- `languages` 1-to-many `contact_interactions`; later also policy versions and agent-language skills.
- `bookings` 1-to-many `contact_interactions`; each interaction may have no booking.
- `conversation_reference` plus `queue_leg_number` orders queue legs for a transferred contact without treating a contact as belonging to only one queue.

## 5. KPI calculation contract (initial)

All KPI outputs must include the requested time window and time zone, interval grain, market filter (if supplied), channel/queue filters, service-language filter (if supplied), data coverage/warnings, and SLA rule/definition version used.

- **Offered:** count interaction legs by `offered_at_utc` within the interval.
- **Handled/answered:** count eligible interaction legs with a valid `answered_at_utc`, according to the channel definition.
- **SLA:** `answered within the versioned target / eligible offered contacts × 100`. The eligible denominator excludes short abandons only when the effective rule says to exclude them. A missing response is not an SLA success. Select the rule using the interaction's market, queue, and effective time.
- **ASA:** average `answered_at_utc - offered_at_utc` for eligible answered synchronous contacts. Do not apply this live wait formula to asynchronous channels.
- **AHT:** for handled synchronous contacts with complete duration components, `(talk_seconds + hold_seconds + after_contact_work_seconds) / count of handled contacts with all three components present`. Report component coverage; never silently convert a missing component to zero.
- **Abandon rate:** eligible abandoned contacts divided by eligible offered contacts; document the short-abandon treatment used.
- **Staffing:** Erlang C is a baseline for synchronous queue workloads under its assumptions. It is not a universal staffing model for email/social asynchronous work. Apply occupancy/shrinkage assumptions explicitly and display them with the result.

No final KPI is exposed until its definition and edge cases have automated tests. Reports should show an `Unknown / Unmapped` market bucket for records whose `market_code` is `NULL`, rather than silently excluding those records from totals.

## 6. Migration policy and review checklist

Before writing or applying migration 001, verify:

1. Current database name and server environment are correct.
2. Only the intended `db_Airlines` database is targeted.
3. Market semantics are agreed: operational/reporting market versus booking sales/POS market.
4. Seed market codes/names and mapping of source data values are agreed (`QATAR`, `USA`, `UAE` are proposed initial internal codes).
5. Exact allowed values for queue/service/channel/status fields are agreed.
6. SLA behavior is explicitly defined for live and asynchronous channels, per market where necessary.
7. Booking lookup returns only approved minimum fields.
8. Foreign keys, uniqueness constraints, indexes, nullability, and timestamp conventions are reviewed.
9. A backup/recovery plan exists for any non-empty environment.
10. SQL is reviewed and applied manually by a developer/DBA account; the runtime application account remains least-privilege.

This file is a design specification, not executable SQL. It does not instruct the application or LLM to create or drop tables automatically.
