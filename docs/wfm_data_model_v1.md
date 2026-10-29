# Airline Contact Center AI Platform — WFM Data Model v1

**Status:** Design proposal for review; not executable SQL. No database changes are authorized by this document.

## 1. Scope and design decisions

This model extends the existing `db_Airlines` design with end-to-end Workforce Management (WFM): historical interval facts, forecasting, agent capability data, published schedules, attendance, actual activity intervals, schedule adherence, and forecast-to-staffing calculations.

1. **Modular monolith:** MySQL stores normalized operational facts and metadata. Python services calculate KPIs and staffing. Streamlit presents results. LangGraph may call tools, but must not invent values or execute migrations.
2. **Market is a first-class dimension:** `market_code` is present on historical interval facts, forecasts, staffing assumptions/results, and contact interactions. It is not inferred from passenger nationality or sale point.
3. **Planning grain:** default 30-minute intervals, configurable for each data feed. Every interval is anchored in UTC; market/site/agent time zones are IANA names such as `Asia/Qatar` and `America/New_York`.
4. **UTC is authoritative:** store event and interval boundaries in UTC. Keep the applicable IANA time-zone identifier; local wall-clock values can be stored as imported/audit snapshots when required. Validate them against UTC, especially around daylight-saving transitions.
5. **Published schedules are immutable snapshots:** schedule edits create a new schedule version/publication. Adherence is evaluated against the publication version that was in force, not against a later edited draft.
6. **Source-of-truth and lineage:** raw events and imported aggregates are distinguishable. Do not add raw interactions and their aggregate interval facts together as if they were separate demand.
7. **Separate service demand from employee UI language:** employee response language, passenger/service language, and policy-document source language remain different concepts.
8. **Actual KPI definitions are versioned:** configured tolerances, SLA rules, shrinkage assumptions, and activity-state mappings must be effective-dated and versioned.
9. **Data minimization:** store employee identifiers and names only for authorized WFM use. Prefer internal `agent_id` as the database key; do not copy unnecessary passenger PII into analytics tables.
10. **Suggested defaults are not company policy:** all tolerance values, service targets, occupancy targets, shrinkage assumptions, and activity eligibility must be confirmed with operations before production use.

## 2. Shared reference / dimension entities

### `markets`
- **PK:** `market_code` (e.g. `QATAR`, `USA`, `UAE`)
- Key fields: `market_name`, `country_code`, `reporting_timezone`, `is_active`
- Purpose: operational reporting/planning market. Keep separate from sales market/point-of-sale if that is also needed.

### `channels`
- **PK:** `channel_code`
- Key fields: `display_name`, `is_synchronous`, `is_active`
- Examples: `voice`, `webchat`, `whatsapp`, `email`, `social_media`.

### `languages`
- **PK:** `language_code`
- Key fields: `display_name`, `is_active`
- Initial examples: `en`, `ar`, `fr`. Use an explicit `unknown`/unmapped value where required by the ingestion contract; do not guess a language.

### `services`
- **PK:** `service_code`
- Key fields: `display_name`, `is_active`
- Examples: booking, refund, loyalty, general enquiry. Codes must be agreed and stable.

### `queues`
- **PK:** `queue_id`; **unique:** `queue_code`
- Key fields: `queue_name`, `service_code` FK, `channel_code` FK, `is_active`
- Purpose: operational routing/forecast group. A queue may serve multiple markets, so market is recorded on demand/forecast rows rather than inferred from queue name.

### `sites`
- **PK:** `site_id`; **unique:** `site_code`
- Key fields: `site_name`, `timezone_name`, `is_active`
- Purpose: work location for an agent and optional staffing constraints.

### `activity_types`
- **PK:** `activity_code`
- Key fields: `display_name`, `activity_group`, `is_paid`, `counts_as_working_time`, `is_adherence_eligible`, `is_active`
- Examples: `LOGIN`, `ON_QUEUE`, `BREAK`, `LUNCH`, `COACHING`, `MEETING`, `OFF_PHONE_WORK`, `TRAINING`, `OFF_DUTY`.
- Keep a canonical group such as `ON_QUEUE`, `BREAK`, or `MEETING` so an actual source state can be mapped to the corresponding scheduled activity.

### `source_systems` and `ingestion_batches` (recommended)
- `source_systems`: **PK** `source_system_id`; fields `system_code`, `system_name`, `system_type` (ACD/CCaaS, WFM, HRIS, LMS, CRM, manual import), `is_active`.
- `ingestion_batches`: **PK** `batch_id`; fields `source_system_id` FK, `started_at_utc`, `completed_at_utc`, `source_file_name`/external batch key, checksum, `status`, row counts, validation summary.
- Purpose: identify where each set of imported facts came from and make re-imports idempotent/auditable.

## 3. Contact demand and historical forecasting data

### `bookings` (support lookup; minimal fields)
- **PK:** `booking_id`; **unique:** normalized `booking_reference` for the initial single-source demo
- Key fields: `booking_status`, `scheduled_departure_utc`, `origin_airport_code`, `destination_airport_code`, `created_at_utc`, `updated_at_utc`
- Keep passenger names, passport numbers, payment information, and full PNR contents out unless an approved use case requires them.

### `contact_interactions`
- **PK:** `interaction_id`
- Grain: one contact offered to one queue (one queue leg). A transferred contact creates another leg linked by `conversation_reference` and `queue_leg_number`.
- FKs/dimensions: `market_code`, `channel_code`, `queue_id`, `service_language_code`, optional `booking_id`
- Key fields: `conversation_reference`, `queue_leg_number`, `offered_at_utc`, nullable `answered_at_utc`, `ended_at_utc`, `abandoned_at_utc`, nullable `talk_seconds`, `hold_seconds`, `after_contact_work_seconds`, `created_at_utc`, source/ingestion references
- Validation: non-negative durations; logically ordered timestamps; unique `(conversation_reference, queue_leg_number)` when conversation reference exists; channel/queue compatibility.
- Purpose: transaction/event-level source of truth when the source system exports contact-level data.

### `historical_interval_metrics`
- **PK:** `historical_interval_metric_id`
- **Unique business grain:** `(market_code, channel_code, service_language_code, service_code, queue_id, interval_start_utc, interval_seconds, source/definition version)`; implement an explicit import/run ID where facts from several sources could overlap.
- FKs: market, channel, language, service, queue, optional ingestion batch
- Key fields: `interval_start_utc`, `interval_seconds` (e.g. 1800), `offered_count`, `handled_count`, `abandoned_count`, `sla_eligible_count`, `answered_within_target_count`, `total_handling_seconds`, optional externally supplied `aht_seconds` and `service_level_pct` for reconciliation, `data_quality_status`, `source_system_id`, `batch_id`, `loaded_at_utc`
- Canonical derived metrics: `AHT = total_handling_seconds / eligible_handled_count`; `SL = answered_within_target_count / sla_eligible_count * 100`; abandon rate uses a defined eligible denominator. Preserve numerator and denominator counts; never average interval percentages to create a larger-period percentage.
- Purpose: standard interval fact for training/validating forecasts and comparing forecast to actual. Where contact-level data exists, derive aggregates from it; where only vendor interval exports exist, import them with lineage. Never count both paths as two independent sets of contacts.

### `sla_rules`
- **PK:** `sla_rule_id`
- FKs/dimensions: `market_code`, `queue_id` (and channel if the rule is channel-specific)
- Key fields: `measurement_mode` (`answer_within_target` or `first_response_within_target`), `response_target_seconds`, `target_service_level_pct`, short-abandon threshold/exclusion, `effective_from_utc`, nullable `effective_to_utc`, `definition_version`
- Unique/effective-date rules must prevent ambiguous overlapping rule periods for the same `(market, queue, channel)` grain.
- Async channel SLA must define what constitutes an eligible offer, response, completion, and abandonment; do not apply live-call formulas blindly.

## 4. Agent, language, service and training capabilities

### `agents`
- **PK:** internal `agent_id`; **unique:** external `staff_id`
- Key fields: `display_name` (restricted HR data), `site_id` FK, `primary_timezone`, `employment_status` (`active`/`inactive` and optionally leave/terminated statuses), `active_from`, `active_to`, optional source-system ID and audit timestamps
- Purpose: common agent identity. Other tables use `agent_id`, not a display name.

### `agent_language_skills`
- **PK:** composite `(agent_id, language_code, valid_from_utc)` or surrogate ID plus equivalent unique constraint
- FKs: `agent_id`, `language_code`
- Key fields: `proficiency_level`, `is_certified`, `valid_from_utc`, `valid_to_utc`, `is_active`
- Purpose: languages an agent can serve and proficiency/validity.

### `agent_service_skills` (recommended for multi-service WFM)
- **PK:** composite `(agent_id, service_code, valid_from_utc)` or surrogate ID plus equivalent unique constraint
- FKs: `agent_id`, `service_code`
- Key fields: `skill_level`, `valid_from_utc`, `valid_to_utc`, `is_active`
- Purpose: agent eligibility for a service or service group. Add queue-specific skills instead if the operation actually manages eligibility at queue level.

### `training_courses` and `agent_training_completions`
- `training_courses`: **PK** `training_id`; fields `training_code`, `training_name`, `validity_days`/expiry rule, `is_active`.
- `agent_training_completions`: **PK** `agent_training_completion_id`; FKs `agent_id`, `training_id`; fields `completed_at_utc`, `expires_at_utc`, `status`, optional certificate/source reference.
- Purpose: ensure the schedule optimizer does not assign an agent to a service/market requiring training the agent has not completed or whose training has expired.

## 5. Schedule planning and publication

### `schedule_publications`
- **PK:** `schedule_publication_id`
- Key fields: `publication_code`/version, planning window start/end UTC, `status` (`draft`, `published`, `superseded`, `cancelled`), `published_at_utc`, `published_by`, optional `supersedes_publication_id`, source WFM reference
- Purpose: immutable schedule snapshot/version used for adherence. Draft changes do not rewrite the historic published schedule.

### `schedule_shifts`
- **PK:** `shift_id`; FK `schedule_publication_id`, `agent_id`
- Key fields: `shift_start_utc`, `shift_end_utc`, `agent_timezone`, optional imported `shift_start_local`, `shift_end_local`, local UTC offsets, shift status, paid/unpaid duration fields, market/site as applicable
- Constraints: start < end; avoid unintended overlapping shifts for the same agent/publication. A cross-midnight shift is one shift with UTC boundaries spanning the date change.
- UTC is authoritative; local values are provided for audit/display and must be validated against the timezone, particularly at daylight-saving transitions.

### `scheduled_activities`
- **PK:** `scheduled_activity_id`; FK `shift_id`, `activity_code`
- Key fields: `scheduled_start_utc`, `scheduled_end_utc`, optional local-time snapshots and timezone, `market_code`, `channel_code`, `service_code`, `service_language_code`, `queue_id` as applicable, `planned_minutes`, `adherence_eligible`, optional activity/exception notes
- Purpose: every planned segment in a shift: login, on-queue handling, break, lunch, coaching, meetings, training, off-phone work, etc. Activities should cover the shift as intended and should not overlap unless the business explicitly permits it.

## 6. Real-time attendance and actual activity capture

### `absence_records`
- **PK:** `absence_id`; FK `agent_id`, optional `shift_id`
- Key fields: `absence_type`, `planned_or_unplanned`, `approval_status`, `start_utc`, `end_utc`, `recorded_at_utc`, `source_system_id`, `exclude_from_adherence` (policy-controlled), reason code with restricted access
- Purpose: approved time off and unplanned absence. Keep the recorded absence separate from raw attendance events; reconcile it to the published shift in a traceable way.

### `attendance_events`
- **PK:** `attendance_event_id`; FK `agent_id`, `source_system_id`
- Key fields: `event_type` (`clock_in`, `clock_out`, `login`, `logout`, `absence_start`, `absence_end`), `event_at_utc`, source event ID, ingested_at_utc, validation status, raw code for traceability
- Purpose: immutable raw attendance/login signals from timekeeping, identity, desktop, or telephony platforms.

### `attendance_intervals` (normalized/derived)
- **PK:** `attendance_interval_id`; FK `agent_id`, optional `shift_id`, source/event references
- Key fields: `present_start_utc`, `present_end_utc`, `presence_status`, `derivation_run_id`, `data_quality_status`
- Purpose: normalized presence windows reconstructed from attendance events. This is derived data, not a replacement for raw events.

### `source_activity_mappings`
- **PK:** `source_activity_mapping_id`
- FKs: `source_system_id`, canonical `activity_code`
- Key fields: `source_state_code`, optional source channel/tenant, `valid_from_utc`, `valid_to_utc`, `mapping_version`, `is_active`
- Unique key should identify a source state unambiguously over its validity period.
- Purpose: map vendor-specific agent states (e.g. available, wrap-up, meal) to canonical activity types/buckets used by schedule comparison.

### `actual_activity_intervals`
- **PK:** `actual_activity_interval_id`; FK `agent_id`, canonical `activity_code`, source mapping/event references
- Key fields: `actual_start_utc`, nullable `actual_end_utc` for currently open states, `source_state_code`, `source_system_id`, `captured_at_utc`, `ingested_at_utc`, `data_quality_status`
- Purpose: normalized segments describing what the agent actually did. Construct from immutable raw state-change events; close the previous interval when a new state is received. Retain source-event IDs so errors can be traced.

### `attendance_reconciliation_results` (recommended operational output)
- **PK:** `attendance_reconciliation_id`; FKs `shift_id`, `agent_id`, optional `absence_id`
- Key fields: expected start/end, first observed presence, late minutes, missing attendance flag, matched absence status, result status, evaluated_at_utc, rule version
- Purpose: make real-time exceptions visible to supervisors. Attendance presence is not identical to activity adherence.

## 7. Adherence configuration and results

### `adherence_policies`
- **PK:** `adherence_policy_id`
- Optional scope keys: market, site, activity group/activity code; effective dates and `policy_version`
- Configurable fields (suggested initial values only):
  - `late_start_tolerance_seconds` (example: 60)
  - `early_start_tolerance_seconds` (example: 60)
  - `early_end_tolerance_seconds` (example: 60)
  - `extended_end_tolerance_seconds` (example: 60)
  - `missing_activity_grace_seconds` (example: 300)
  - `minimum_data_coverage_pct` / data-completeness policy
  - absence/approved exception treatment and activity eligibility rules
- Tolerances must be approved by operations and effective-dated. They are not universal WFM standards.

### `adherence_runs`
- **PK:** `adherence_run_id`
- Key fields: reporting window start/end UTC, schedule publication/version ID, `evaluated_at_utc`, `actual_data_cutoff_utc`, policy/mapping versions, status, invocation source
- Purpose: reproducible real-time snapshots and final historical recalculation. A final result should not be marked final while the ingestion grace period has not elapsed or source data is known to be incomplete.

### `adherence_activity_results`
- **PK:** `adherence_activity_result_id`; unique per `(adherence_run_id, scheduled_activity_id)`
- FKs: run, scheduled activity, optional matched shift/agent keys for efficient reporting
- Key fields: `scheduled_seconds`, `eligible_scheduled_seconds`, `adherent_seconds`, `non_adherent_seconds`, `start_deviation_seconds`, `end_deviation_seconds`, `start_classification`, `end_classification`, `overall_status` (`on_time`, `late`, `early`, `extended`, `missed`, `partial`, `excused`, `data_gap`), result quality/warnings
- Purpose: store the auditable comparison result for each scheduled activity. Start and end classifications are separate because one activity can start late and also finish extended.

### `adherence_activity_matches` (for fragmented actuals)
- **PK:** `adherence_match_id`; FKs `adherence_activity_result_id`, `actual_activity_interval_id`
- Key fields: overlap start/end UTC, overlap seconds, `is_expected_activity`, mapped activity group and mapping version
- Purpose: one planned segment may correspond to multiple actual intervals. This bridge records which actual spans contributed to the score without losing detail.

### Adherence calculation rules

**Time-weighted adherence is the primary KPI:**

`activity_adherence_pct = adherent_seconds / eligible_scheduled_seconds * 100`

`shift_adherence_pct = SUM(adherent_seconds for eligible activities in the shift) / SUM(eligible_scheduled_seconds for those activities) * 100`

`agent_day_adherence_pct = SUM(adherent_seconds across eligible shifts/activities) / SUM(eligible_scheduled_seconds across the same scope) * 100`

- Do **not** average activity percentages equally; use the duration-weighted formula above.
- `adherent_seconds` is the overlap, clipped to the scheduled window, where the actual canonical activity bucket matches the scheduled bucket under the active policy.
- Unapproved absence during scheduled eligible time is non-adherent by default. Approved exceptions may be excluded only if the approved company policy says so and the exclusion is auditable.
- Break, lunch, meeting, coaching, training and off-phone tasks can be adherent when the correct activity is performed at the scheduled time. Being logged in is not sufficient if the agent is in the wrong activity.
- Report schedule conformance/punctuality separately from duration adherence. `late`, `early`, `extended`, `missed` are deviation classifications; they do not replace the time-weighted percentage.
- Extended activity outside the scheduled end is reported as an exception but does not increase the scheduled denominator or give extra adherence credit.
- Missing data is `data_gap`, not automatically `missed`. Use `missed` only after the applicable grace period and when the relevant source feed is healthy/complete enough to conclude the event did not occur.

**Suggested classification logic (configurable):**
- Start `on_time` if actual start is within `[scheduled_start - early_start_tolerance, scheduled_start + late_start_tolerance]`.
- Start `early` if it is earlier than that window; start `late` if it is later.
- End `on_time` if actual end falls within `[scheduled_end - early_end_tolerance, scheduled_end + extended_end_tolerance]`.
- End `early` if before the end window; end `extended` if after it.
- `missed` if no matching activity exists after `scheduled_end + missing_activity_grace_seconds` and input data is confirmed complete.
- `partial` if a valid matching segment covers only part of the expected scheduled interval.
- Store start and end labels separately; do not force two different deviations into one label.

## 8. Forecasting and forecast-to-staffing entities

### `forecast_runs`
- **PK:** `forecast_run_id`
- Key fields: model name/version, forecast type, training data cutoff UTC, target horizon, interval size, created/start/end times, status, configuration JSON/version, training/evaluation metadata, source data version
- Purpose: identify exactly which model/data/config produced a forecast.

### `forecast_results`
- **PK:** `forecast_result_id`; unique per forecast run + dimensions + target interval
- FKs/dimensions: `forecast_run_id`, market, channel, service language, service, queue
- Key fields: `interval_start_utc`, `interval_seconds`, `forecast_offered_count`, optionally `forecast_handled_count`, `forecast_aht_seconds`, forecast workload, lower/upper intervals or quantiles where available, model quality/warning fields
- Purpose: demand predictions by market/channel/language/service/queue. Store observed actuals separately from predictions.

### `staffing_assumptions`
- **PK:** `staffing_assumption_id`
- Scope: market, channel, queue/service, valid-from/to, assumption version
- Key fields: `service_model` (`ERLANG_C` for eligible synchronous queues; a separately approved workload/backlog model for asynchronous channels), target service level, response target seconds, max occupancy, planned shrinkage, unplanned shrinkage or approved combined shrinkage, source/version, effective dates
- Purpose: versioned inputs for staffing. Do not use Erlang C for email or other asynchronous/backlog work unless an explicitly validated model justifies it.

### `staffing_requirements`
- **PK:** `staffing_requirement_id`; FKs `forecast_result_id`, `staffing_assumption_id`
- Key fields: offered load (Erlangs where applicable), agents required for SLA, agents required for occupancy cap, `required_on_queue_agents`, combined shrinkage, `scheduled_heads_required`, `required_staff_hours`, calculation/model version, warnings
- Purpose: make each calculation reproducible and compare staffing need with schedule coverage.

### Forecast-to-FTE calculation chain

1. **Prepare historical series:** `historical_interval_metrics` by market/channel/language/service/queue and interval. Check missing intervals, changed queue definitions, holidays, campaigns, and source-data quality.
2. **Forecast demand and handle time:** produce offered contacts/tickets and AHT per future interval in `forecast_results`.
3. **For synchronous channels, calculate offered load:**
   - `arrival_rate_per_second = forecast_offered_count / interval_seconds`
   - `offered_load_erlangs = arrival_rate_per_second * forecast_aht_seconds`
   - Find the smallest integer agent count meeting both the configured service-level objective (using the approved Erlang C implementation) and the occupancy ceiling.
4. **For asynchronous channels:** use an approved backlog/workload-capacity model with handling work content, concurrency/productivity, response SLA, and carryover backlog. Do not pretend Erlang C is universal.
5. **Apply shrinkage:** if planned and unplanned shrinkage are maintained as sequential loss rates, a documented combined rate can be computed as `1 - (1 - planned_shrinkage) * (1 - unplanned_shrinkage)`. If the organization defines total shrinkage directly, use that approved definition instead; do not mix conventions. `scheduled_heads_required = ceil(required_on_queue_agents / (1 - combined_shrinkage))`.
6. **Distinguish agents from FTE:** the primary interval result is concurrent staff/headcount required. `required_staff_hours = scheduled_heads_required * interval_seconds / 3600`. Contractual monthly/annual FTE requires a separately defined standard-hours denominator and must not be inferred from one interval alone.
7. **Check skill feasibility:** compare requirements with active agents who have the required language/service capability, valid mandatory training, site eligibility, contractual availability and published shift coverage.
8. **Schedule and evaluate:** schedule publication -> activity assignments -> actual status ingestion -> attendance reconciliation -> adherence result. Compare observed volume/AHT/staffing with the forecast to refine later model evaluations.

## 9. Data flow and reconciliation lifecycle

1. **Demand source ingestion:** ACD/CCaaS, telephony, chat/WhatsApp, social, and ticket/email platforms provide raw contact events or interval aggregates. Record source system, extraction time, source batch, timezone assumptions, and validation status.
2. **Normalization:** map source channel/queue/market/language/service identifiers to canonical dimensions. Unmapped values go to an explicit exception/unknown bucket; do not silently infer the market or language.
3. **Historical facts:** derive `historical_interval_metrics` from event-level contacts when available, or import vendor interval totals when not. Reconcile totals to the source report and avoid double-loading equivalent facts.
4. **Agent/capability ingestion:** HRIS provides staff ID/name/site/employment status; skills may be maintained in WFM or sourced from operational qualification systems; LMS provides training completion/expiry.
5. **Forecast and staffing:** validated actual intervals -> `forecast_runs`/`forecast_results` -> staffing assumptions/Erlang C or async model -> `staffing_requirements`.
6. **Schedule publication:** create draft schedule; validate shifts, activity coverage, contracts, skill/language/training eligibility and coverage against required staff; publish a versioned schedule snapshot.
7. **Real-time capture after publication:** timekeeping provides clock/presence events; ACD/CCaaS/desktop provides actual activity-state changes. Store raw events immutably, normalize them into attendance and activity intervals, and keep source IDs.
8. **Reconciliation:** match agent ID + published shift + time interval + canonical activity bucket; resolve duplicates, out-of-order events, open-ended activities, clock gaps, approved absences and schedule amendments. Retain exceptions, not just a single final score.
9. **Adherence evaluation:** periodic real-time run uses a stated data cutoff/grace period. Final historical run happens after the source data is considered complete. Save the schedule publication, policy and state-mapping versions used.
10. **Dashboard and evaluation:** show adherence with coverage warnings; compare forecast/actual volume, AHT, SLA and required/available staffing. Use results for model evaluation only after the actuals are quality-checked.

## 10. Recommended migration rollout

Do not create the entire model in one large migration. A practical sequence is:

- **Migration 001 — Core operations/reference data:** `markets`, `languages`, `channels`, `services`, `queues`, minimal `bookings`, `contact_interactions`, effective-dated `sla_rules`, with reviewed constraints and seed dimensions.
- **Migration 002 — Historical facts and ingestion lineage:** `source_systems`, `ingestion_batches`, `historical_interval_metrics`, source mapping/quality metadata.
- **Migration 003 — Workforce and qualifications:** `sites`, `agents`, `agent_language_skills`, `agent_service_skills`, `training_courses`, `agent_training_completions`.
- **Migration 004 — Schedules:** `activity_types`, `schedule_publications`, `schedule_shifts`, `scheduled_activities`.
- **Migration 005 — Actual presence and activity:** `absence_records`, `attendance_events`, `attendance_intervals`, `source_activity_mappings`, `actual_activity_intervals`, attendance reconciliation output.
- **Migration 006 — Adherence:** `adherence_policies`, `adherence_runs`, `adherence_activity_results`, `adherence_activity_matches`, SQL views for shift/agent rollups.
- **Migration 007 — Forecasting/staffing:** `forecast_runs`, `forecast_results`, `staffing_assumptions`, `staffing_requirements`.
- **Later:** policy metadata/RAG, audit/evaluation tables, cached interval rollups if profiling shows they are needed.

Each migration must have a clear owner, tests, seed-data rules and rollback/recovery plan. Apply manually after review; never run DDL from the LLM or Streamlit UI.

## 11. Commonly native WFM versus external/custom sources

This varies by vendor, product tier, licensing and integration. Do not assume a capability exists until the selected platform/API and entitlement are verified.

- **Often native in an enterprise WFM platform:** forecasting scenarios, staffing requirements, schedule generation/publication, activity plans, time-off/calendar handling, real-time or historical adherence, intraday forecast-versus-actual monitoring.
- **Often owned by adjacent operational systems or synchronized into WFM:** raw ACD/CCaaS interaction events and agent state changes; HRIS employee identity/site/employment status; LMS training completions; identity/timekeeping clock events; channel-specific ticket/backlog events from email/social systems.
- **Frequently custom in an analytics layer or required for cross-system integration:** unified market/channel/language/service dimensional keys, common event taxonomy, data-quality/lineage, cross-platform historical interval facts, a consistent adherence policy/results contract, model evaluation, AI-generated explanations, and a common staffing/FTE output across heterogeneous channels.
- **Implementation recommendation:** if a WFM platform already owns schedules or adherence, integrate/read its APIs and preserve the platform's schedule/version identifiers. Do not rebuild a duplicate schedule engine until a clear capability gap is documented. Build only a common reporting/integration layer for the gaps.

Official vendor documentation illustrates that established WFM products can include forecasting, schedules, intraday monitoring, and adherence; exact support varies by product/edition: Genesys Cloud WFM overview (https://help.genesys.cloud/articles/workforce-management/) and NICE WFM overview (https://www.nice.com/products/workforce-management).

## 12. Open decisions before executable SQL

1. Does `market` mean operational/customer-service market, sales market/point of sale, or both?
2. Which system is authoritative for schedules, employee master data, attendance, and actual states?
3. Is the canonical reporting interval 15 or 30 minutes? Can historical source feeds guarantee complete intervals?
4. Exact queue/service/channel/language codes and `unknown` handling.
5. Approved channel-specific SLA definitions and short-abandon rules.
6. Adherence tolerances, activity mappings, grace periods, approved exceptions, and whether all scheduled activities count in the denominator.
7. Whether shrinkage is maintained as one total rate or separate sequential loss rates.
8. For async work: backlog carryover, response target, capacity/productivity, concurrency, and working-hours assumptions.
9. Which employee fields are approved to store, who can access them, and how long detailed raw events are retained.
10. Forecast history coverage and acceptance criteria for model accuracy before it can drive published staffing plans.
