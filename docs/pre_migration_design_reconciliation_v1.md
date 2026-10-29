# Pre-Migration Design Reconciliation v1

**Project:** `airline_contact_center_ai`  
**Database:** `db_Airlines`  
**Status:** Design reconciliation only — **not executable SQL**. No database objects should be created from this document.

## 1. Purpose

This document reconciles the three current design sources:

- `database_schema.md` — core relational schema and KPI contract.
- `wfm_data_model_v1.md` — forecasting, agents/skills, schedules, attendance, actual activities, adherence, and staffing.
- `rtm_intraday_management_spec.md` — real-time risk detection, staffing recommendations, SLA recovery actions, next-interval planning, and action governance.

The goal is to avoid duplicate or conflicting entities before preparing `database/migrations/001_create_core_schema.sql`.

## 2. Canonical design decisions

### 2.1 Platform and trust boundaries

- Use MySQL with InnoDB and `utf8mb4`.
- Start as a modular monolith: Streamlit UI, Python business services, deterministic analytics, forecasting modules, and LangGraph tool orchestration.
- SQL/Python owns numeric KPI calculations, staffing calculations, candidate eligibility, and policy enforcement. The LLM explains results and orchestrates approved tools; it must not invent values, run arbitrary SQL, execute DDL, or make unrestricted routing/schedule changes.
- Migrations are reviewed and applied manually by a developer/DBA. The runtime app uses a least-privilege account.

### 2.2 Shared dimensions and standard keys

Use the same canonical dimensions throughout interactions, historical interval facts, forecasts, staffing results, and RTM reports:

- `market_code`
- `channel_code`
- `service_code`
- `queue_id` / `queue_code`
- `service_language_code` / `language_code`
- UTC interval or event timestamp

Use stable codes in a consistent format. Recommended conventions are uppercase market codes (`QATAR`, `USA`, `UAE`) and lowercase `snake_case` for service, channel, activity, and source-system codes. Display names are separate from stored codes.

`markets` represents the **operational/reporting market** served by the contact-center interaction. It does not implicitly mean passenger nationality, booking route, employee home site, or ticket sales/point-of-sale market. If sales/POS market becomes required, add a separate dimension/field with its own definition.

### 2.3 Time and interval conventions

- UTC is authoritative for event timestamps and interval boundaries.
- Use IANA time-zone identifiers for market, site, and agent display/schedule interpretation (for example, `Asia/Qatar` or `America/New_York`).
- Default planning/reporting grain is 30 minutes, but interval duration must be stored explicitly (`interval_seconds`) so source feeds can use another supported grain without ambiguity.
- Keep published schedules as immutable versions. A schedule change produces a new publication/version; adherence uses the schedule publication that was in force.

### 2.4 Service language and unknown values

- Employee UI language, passenger/service language, and policy document source language remain separate concepts.
- Never infer service language from employee UI language, market, name, or queue label.
- For detail records, nullable `service_language_code` can mean unknown if the source cannot determine it. For aggregate grains where stable grouping/uniqueness is required, normalize unmapped/undetermined language to an explicit code such as `und`, with the ingestion quality flag retaining the reason. Do not treat unknown as a real proficiency or qualification.

### 2.5 Queue and channel model

- A `queues` record has one canonical `channel_code` and one `service_code` in v1.
- A shared queue can serve more than one operational market; therefore market attribution is stored on the interaction/interval fact, not inferred from queue name.
- Since a queue identifies its channel in v1, `sla_rules` can be keyed by `(queue_id, market_code, effective_from_utc)` without duplicating `channel_code`. If a future source allows one queue to serve multiple channels, revise the model before enabling that integration.

### 2.6 Source data and preventing double counting

- `contact_interactions` is contact/queue-leg grain: one offered leg to one queue. A transfer creates another leg, linked by `conversation_reference` and `queue_leg_number`.
- `historical_interval_metrics` is aggregate interval grain and is used for forecast training/validation and source reconciliation.
- Never add raw interactions and vendor interval aggregates together as though both represented separate demand. When both exist, establish one canonical calculation path and retain the other as a reconciliation source.
- Store source/ingestion lineage from Migration 002 onward. Migration 001 should not reference `source_systems` or `ingestion_batches` before those tables exist; add the lineage columns through the later migration if required.

## 3. Reconciled initial migration scope

Migration 001 should create only the core operational foundation:

1. `markets`
2. `languages`
3. `channels`
4. `services`
5. `queues`
6. `bookings` (minimal fields; synthetic/demo data initially)
7. `contact_interactions`
8. `sla_rules`

Recommended FK creation order follows the list above. The DDL will include explicit primary/foreign keys, required nullability, useful indexes, uniqueness constraints, and timestamp conventions. The migration should not create workforce, forecast, adherence, or RTM tables yet.

### 3.1 Seed data policy

Prepare reviewed seed data separately from table DDL, for example `database/seeds/001_core_reference_data.sql` or a typed seed script.

Potential reference values to review:

- Markets: `QATAR`, `USA`, `UAE` (names, country codes, and approved reporting time zones).
- Languages: `en`, `ar`, `fr`, and optionally `und` for normalized undetermined values.
- Channels: `voice`, `webchat`, `whatsapp`, `email`, `social_media`.
- Services: agree canonical business codes before seed. Examples in design documents are examples only, not verified source-system codes.

Do not invent queue names, production SLA targets, response thresholds, short-abandon rules, or market-specific targets. Insert only approved or clearly marked demo data.

## 4. WFM entity map and rollout

### Migration 002 — source lineage and historical interval facts

- `source_systems`
- `ingestion_batches`
- `historical_interval_metrics`
- Canonical source-ID mappings and data-quality/validation metadata as needed

Purpose: support reproducible imports, avoid duplicate loads, reconcile contact counts and train/evaluate forecasting.

### Migration 003 — agent identity and eligibility

- `sites`
- `agents`
- `agent_language_skills`
- `agent_service_skills` (or a reviewed generic `skills` + `agent_skills` design if the actual WFM skill taxonomy requires channel/queue-level skills)
- `training_courses`
- `agent_training_completions`

Use an internal `agent_id` as the database key and a unique external `staff_id` for source matching. Restrict employee display names and other HR-related fields by role. A candidate cannot be recommended based on an expired, missing, or unverified qualification.

### Migration 004 — schedule publication

- `activity_types`
- `schedule_publications`
- `schedule_shifts`
- `scheduled_activities`

Store UTC start/end values and the applicable agent/site timezone. Treat publication versions as immutable. Validate shift/activity overlap and cross-midnight/24-hour operation correctly.

### Migration 005 — attendance and observed activity

- `absence_records`
- `attendance_events`
- `attendance_intervals` (derived/normalized)
- `source_activity_mappings`
- `agent_state_events` (normalized append-only state changes from ACD/CCaaS/desktop systems)
- `actual_activity_intervals` (derived intervals from the event stream)
- `attendance_reconciliation_results`

Do not equate login with being available on-queue. Keep raw/normalized events and derived intervals distinguishable so late, duplicated, out-of-order, and missing events can be reconciled.

### Migration 006 — adherence

- `adherence_policies`
- `adherence_runs`
- `adherence_activity_results`
- `adherence_activity_matches` when fragmented actual activity must be matched to scheduled activities

Adherence calculation must record schedule publication, policy/tolerance version, data cutoff, and coverage warnings. On-time/late/early/extended/missed are configurable classifications. A data feed gap must be marked as a data-quality issue rather than automatically treated as a confirmed missed activity.

### Migration 007 — forecasts and staffing requirements

- `forecast_runs`
- `forecast_results`
- `staffing_assumptions`
- `staffing_requirements`

Keep forecast and actual values separate. Forecast outputs must identify their model/version, training cutoff, target interval, dimensions, metric, and uncertainty bounds where available. Distinguish required simultaneous on-queue agents, gross scheduled headcount, staff-hours, and contractual FTE.

### Migration 008 — RTM monitor and action governance

- `queue_state_snapshots` (and/or a history of timestamped snapshots, depending on retention and analytics requirements)
- `rtm_threshold_rules`
- `rtm_alerts`
- `rtm_recommendations`
- `rtm_action_log`
- Reuse or add `audit_logs` and `evaluation_runs` for cross-platform governance/evaluation

Use `agent_state_events` and `actual_activity_intervals` from Migration 005 rather than defining a second competing actual-activity model. `rtm_action_log` records operational action lifecycle and vendor confirmation; `audit_logs` captures broader security/tool events. The two may reference one another but should not duplicate the same payload unnecessarily.

RTM must default to observe/recommend mode. Supervisor-approved execution comes later. Automatic actions must remain disabled until explicitly permitted, bounded, reversible, tested, audited, and protected by data-freshness checks.

## 5. KPI and operations contracts

### 5.1 SLA

- SLA rules are effective-dated and market/queue scoped in v1; queue determines channel.
- The eligible denominator, threshold, short-abandon treatment, and sync/async measurement method must be explicit.
- Current interval SLA is labelled provisional until the interval closes. Historical reports must use the rule version effective at the event time.
- Records with unknown market cannot silently be assigned a market-specific SLA rule; flag/report them as unmapped or excluded from market-level conclusions.

### 5.2 AHT, abandonment, and historical metrics

- Do not convert missing duration components to zero.
- Keep numerator/denominator counts for ratios; do not average interval percentages to derive totals.
- For voice, Erlang C can be an initial baseline where its assumptions fit. For email/social/backlog work, use workload, backlog aging, concurrency, response deadlines, and productive capacity rather than applying Erlang C blindly.

### 5.3 Adherence

Recommended baseline:

`adherence_pct = adherent_eligible_seconds / eligible_scheduled_seconds * 100`

Count only the activity categories included by the approved adherence policy. Store tolerance/grace parameters as versioned configuration, not constants in the LLM prompt. Do not finalize company thresholds until WFM/Operations confirms them.

### 5.4 Staffing and FTE

- Calculate required on-queue headcount from forecast offered volume/AHT, interval duration, target service level, and occupancy constraints.
- Apply approved shrinkage once only to convert on-queue need to gross scheduled headcount.
- Use observed current available capacity for real-time actioning; do not apply generic shrinkage again to a live count.
- Define the organization's FTE standard-hours basis before reporting contractual FTE; an interval staffing requirement is not by itself an FTE value.

## 6. RTM decision and safety contracts

The RTM tool should consume fresh queue measures, the queue/skill configuration, agent state, verified skills and proficiency, mandatory training, current published schedule, attendance, SLA policy, and approved operational constraints.

Before recommending a named agent, check:

- required skills and language proficiency are verified and currently valid;
- the person is available now or by the required time, without interrupting an active interaction;
- the source queue remains above its minimum safe coverage after any move;
- site/market/security/contract eligibility, break rules, shift end, and training restrictions are respected;
- one agent is not counted as full capacity in two queues at the same time.

Each recovery action should show destination benefit, source/donor queue impact, expected range/confidence, trade-off, policy guardrail, approval status, expiry, execution result, and rollback/escalation path. If data is stale or key fields are missing, block automatic action and show the data gap.

## 7. Open items that must be decided before production use

These do not prevent drafting the core M001 schema, but must be settled before the relevant feature goes live:

1. Actual systems of record for interactions, agent states, schedules, HR, attendance, skills, and training; API/export availability.
2. Final canonical queue/service/channel/language/market codes and unmapped-value handling.
3. Whether the operational interval is fixed at 30 minutes or varies by source/use case.
4. Exact service-level definitions and targets per queue/market, including async response rules and short abandons.
5. Skill taxonomy: language + service skills only, or generic skills also at queue/channel level; approved proficiency scale.
6. Schedule and adherence policy: included activities, break protection, start/end tolerances, grace periods, absence handling, and feed-gap treatment.
7. Shrinkage convention and occupancy ceiling; confirm how planned/unplanned losses are combined.
8. Async workload model: backlog carryover, concurrency/productivity, and deadline/working-hours rules.
9. Employee data access/retention requirements and whether display names are needed in the RTM UI.
10. RTM polling/event latency, stale-feed thresholds, alert cooldowns, action approval roles, automatic-action allowlist, and rollback procedure.

## 8. Migration 001 review checklist

Before writing or executing `database/migrations/001_create_core_schema.sql`, verify:

- [ ] Database target is exactly `db_Airlines` (case-insensitive comparison may be needed on Windows, but use the agreed configured name consistently).
- [ ] No tables already exist unexpectedly; no `DROP` or destructive statements are present.
- [ ] Create order and foreign keys are valid.
- [ ] `markets`, languages, channels and services have a reviewed seed policy.
- [ ] Queue/channel/service codes are explicit and consistent.
- [ ] SLA rule uniqueness, effective-date rules, and unknown-market behavior are clear.
- [ ] Contact interaction queue-leg grain and nullable fields are agreed.
- [ ] Indexes cover common filters by market, queue, channel, language and event timestamp without over-indexing.
- [ ] Database migrations are separate from seed data and test fixtures.
- [ ] A least-privilege runtime role is separate from the administrative migration account.
- [ ] Unit/integration tests cover FK constraints, duplicate queue-leg rejection, timestamp ordering, market attribution and SLA rule selection.

## 9. Immediate next action

Use this document as the reconciliation gate. Once the file is in `docs/`, the next deliverable should be a reviewed, non-destructive `database/migrations/001_create_core_schema.sql` plus a separate seed file and migration tests. Do not add WFM or RTM operational tables until the later migrations described above.
