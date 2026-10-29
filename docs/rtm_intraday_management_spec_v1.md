# Real-Time Intraday Management (RTM) Specification v1

**Project:** Airline Contact Center AI Platform  
**Status:** Design specification for review — not executable SQL and not a live operational recommendation.  
**Architecture fit:** Python modular monolith, Streamlit, LangGraph for orchestration, MySQL for operational metadata/audit/results, and the existing approved ACD/CCaaS/WFM systems as sources of live operational truth.

## 1. Objective

Build an intraday management capability that continuously compares actual queue and agent conditions with service targets, the published schedule, and the next-interval workload forecast. It must identify service risk, produce explainable recovery options, and make staff-specific recommendations only when current agent, skill, training, schedule, and routing data prove the candidate is eligible.

The system is a decision-support and controlled-action layer; it should not replace the ACD routing engine or an existing WFM platform where those systems already provide the authoritative capability.

## 2. Explicit assumptions

1. The operation is 24/7, multi-market, multi-channel, multi-service, multi-language, and multi-skill.
2. A configurable 15- or 30-minute interval is used for operational reporting. Live queue and agent events may update more frequently.
3. All source timestamps are normalized to UTC for storage; each agent's IANA time zone is retained for local schedule display and shift-boundary interpretation.
4. The current project has no confirmed live ACD/WFM/HR integration or actual agent roster attached to this specification. Therefore it can define the recommendation logic but cannot truthfully name real staff or promise an SLA improvement until valid data and integrations are connected.
5. `Market` means the operational/reporting market for this design. Sales market / point-of-sale, passenger nationality, site, service language, and employee language are separate dimensions.
6. Voice is treated as synchronous. Chat, messaging, email, and social queues use channel-specific workload and response-time policies; Erlang C is not assumed to fit asynchronous work automatically.
7. Example thresholds below are configuration examples only and must be approved by operations before production use.

## 3. Inputs required

### 3.1 Queue / skill-group and interval data

Required dimensions:
- Market, queue, service, channel, service language, skill group (where it exists), interval start UTC, interval length.
- Forecast and actual offered contacts; handled/answered contacts; AHT components; abandonment and short-abandon counts; current queue depth and oldest wait; service level target and response threshold; ASA; occupancy; online/on-queue/available qualified agents.
- For asynchronous channels: open backlog, arrivals, completed items, age distribution, work-in-progress/concurrency, handling-time distribution, and response SLA deadline/remaining time.
- Source event timestamp, ingestion timestamp, and data freshness / completeness status.

Actual interval SLA before interval close is provisional because the denominator and future arrivals can still change. Show both current-to-date / rolling actuals and forecast end-of-interval SLA, clearly labeled.

### 3.2 Agent state snapshot and skill matrix

For each pseudonymous or authorized staff identifier:
- staff ID; active/inactive status; site; market eligibility; local time zone.
- Current ACD/routing state, current activity, current interaction/wrap state, channels currently being handled, and last state-change timestamp.
- Published schedule activity and shift boundaries for the current and next interval, plus schedule publication/version.
- Skill/queue membership, proficiency level, proficiency effective dates, training completion and expiry, service/language authorization, and any mandatory certifications.
- Availability forecast: when an agent is expected to become free, and whether they can safely leave the current source queue.
- Constraints: minimum coverage retained in donor queue, break/meal rules, shift end, overtime authorization, union/local policy restrictions, and concurrent-channel capacity.

A skill proficiency score is a candidate-ranking input. It must not be treated as a fractional agent or converted to productive capacity unless that relationship has been calibrated from data.

### 3.3 SLA and operational policy

Per market + queue/skill group + channel + effective date:
- SLA target percentage and response threshold seconds (for example, target X% answered within Y seconds for voice).
- Eligible-offer denominator rules, short-abandon treatment, priority rules, maximum occupancy, minimum staffing, maximum routing/queue wait, and channel-specific measurement mode.
- Break deferral policy, permitted deferral maximum, supervisor authorization requirement, callback eligibility/consent, overflow eligibility, and safe rollback conditions.
- Risk thresholds, alert severity thresholds, minimum data freshness, alert cooldown/hysteresis, and auto-action policy.

### 3.4 Schedule and actual activity

- Published schedule version, agent shift, scheduled activities, planned breaks/lunch/coaching/training/meetings/handling/off-phone work, start/end UTC and agent-local representations.
- Actual ACD states and activity events, attendance/login/logout events, absence events, manual supervisor adjustments, and event timestamps.
- A governed mapping from source-specific states to canonical activity codes (e.g. ON_QUEUE, INTERACTING, ACW, BREAK, MEAL, COACHING, TRAINING, MEETING, ABSENT, UNKNOWN).
- Never map an unknown state silently to productive time; mark it as unknown/data gap until reviewed.

## 4. Capability A — Real-time staffing decisions

### 4.1 Risk detection

For every queue/skill group, calculate:
1. Actual-to-date and rolling service level, ASA / oldest wait, offered and handled trend, abandonment, occupancy, current backlog, and active qualified capacity.
2. Forecast end-of-interval and next-interval workload, service level risk, and required agents.
3. Staffing gap = required on-queue agents minus effective available qualified agents. Effective availability must exclude agents actively handling an interaction, unavailable agents, agents whose skills/training do not qualify, and agents who cannot safely be removed from their source queues.
4. Risk status using configurable rules. A sample rule could be: forecast end-of-interval SLA below target, or ASA / oldest wait forecast beyond threshold, or qualified staffing below requirement for a configured duration. The exact thresholds must be set by the operation.

Use three labels: `AT_RISK`, `IMPACTED`, and `DATA_INSUFFICIENT`. A stale data feed should not trigger automatic reassignments.

### 4.2 Candidate eligibility — hard constraints first

A candidate is eligible only if all required checks pass:
- Active and expected to be available at the decision time.
- Not in an active interaction or non-interruptible wrap-up; do not forcibly drop a live contact.
- Has an existing, authorized skill/queue assignment meeting the minimum proficiency for the destination, or is explicitly eligible for a temporary skill activation under policy.
- Required language skill and current training/certification are verified.
- Moving the agent will not break minimum source-queue coverage or a higher-priority target requirement.
- Schedule, break, shift-end, site, labor, overtime, and channel-concurrency rules permit the move.
- Destination routing system supports the assignment and confirms the new state.

A model must never infer that an agent is qualified from their name, language preference, or past activity. A request to add a skill to the agent is a recommendation only until training/authorization data validates eligibility and an authorized person or approved workflow confirms the routing-platform change.

### 4.3 Candidate ranking and global allocation

Rank eligible agents by a transparent score incorporating:
- Expected incremental coverage and estimated effect on destination SLA/ASA.
- Proficiency and verified training validity.
- Time until available and remaining shift time.
- Risk and capacity lost in the donor queue.
- Whether the move needs a schedule change, skill activation, or supervisor approval.
- Policy, customer-experience, and employee constraints.

Solve assignments across queues together, not one queue at a time. A multi-skilled agent must not be counted as full capacity in two queues at once. If a source queue is also at risk, the optimizer must show the net enterprise-wide effect and may reject the transfer.

### 4.4 Recommendation output

For each recommendation show:
- Source queue/skill and destination queue/skill.
- Staff identifier (and display name only if the viewer is authorized), verified skills/proficiency, current state, expected availability, and schedule impact.
- Action type: `USE_EXISTING_SKILL`, `TEMPORARY_SKILL_ACTIVATION`, `QUEUE_REASSIGNMENT`, `DEFER_FLEX_ACTIVITY`, or `NO_ELIGIBLE_AGENT`.
- Baseline versus proposed expected service level, ASA/oldest wait, occupancy, queue backlog, and donor-queue impact, plus assumptions/confidence/data freshness.
- Approval requirement, rollback instructions, expiry time, and audit reference.

If skill/proficiency, live state, or routing update capability is missing, return `CANNOT_RECOMMEND_SPECIFIC_AGENT` and identify the missing data rather than inventing a named person.

## 5. Capability B — Prioritized SLA recovery actions

Recommendations are ranked by urgency, expected net benefit, reversibility, confidence, operational risk, and required approval. Use a what-if calculation before executing a staffing/routing change.

| Priority candidate | Trigger / use | Expected impact to estimate | Main trade-off / control |
|---|---|---|---|
| Activate an existing qualified skill or borrow a cross-skilled agent | Destination queue at risk and an eligible agent can be spared | More qualified capacity at destination; estimate destination and donor impact | Must not count one agent twice; supervisor approval unless explicitly pre-authorized |
| Overflow / routing target expansion | Wait and SLA-risk threshold breached; another qualified pool exists | Broader eligible pool may reduce wait and backlog | Donor queues may degrade; skill-level or customer-fit may differ; use only routing-platform-supported, approved rules |
| Defer a flexible activity (e.g. coaching or non-critical meeting) | Short-lived gap with policy-permitted movable activity | Temporarily increases on-queue supply | Supervisor approval; respect protected breaks, labor rules and fatigue safeguards |
| Offer/activate callback | Voice queue wait is high and the approved callback workflow is available | Can reduce callers waiting in the live queue and improve customer experience | Callback acceptance/consent and separate callback SLA required; it does not automatically count as an in-SLA live answer under the current voice SLA denominator |
| Reprioritize asynchronous work | Email/message backlog is at risk of breaching response deadlines | Protects oldest or highest-risk items | Other tickets may age; priority policy must be explicit; forecast item workload/concurrency, not Erlang C by default |
| Reprioritize queue routing | Multiple queues compete for shared capacity | Redirects capacity toward the most urgent permitted service objective | Can harm a lower priority queue; compare net service outcomes and enforce priority policy |
| Request voluntary overtime / shift extension / additional reserve | Persistent forecast capacity deficit | Adds coverage for the remaining intervals | Cost, staff consent/authorization, hours and rest rules; normally supervisor approval |
| Reconcile shrinkage and return eligible time from auxiliary activities | Planned vs actual unavailable time differs and policy allows correction | Improves remaining-period capacity estimate; may identify genuinely recoverable time | Never rewrite actual history or set shrinkage artificially lower. Only trigger a valid operational return/adjustment and recompute from observed states |
| No action / monitor | Data is stale, candidate impact is uncertain, or no compliant candidate exists | Avoids an unsafe or counterproductive change | Explain risk, data gap, and escalation path |

Do not change the official SLA target, exclude contacts retrospectively, or suppress an alert to make performance appear recovered. An action's expected impact is an estimate from a model / what-if engine, not a guarantee.

## 6. Capability C — Forecast-driven FTE planning for the next interval

### 6.1 Forecast inputs and method

Use:
- Historical interval arrivals and AHT by market, service, queue, channel and service language.
- Current interval actual-to-date, normalized for elapsed time and intraday trend; current abandonment, occupancy, queue depth/age, agent states, and recent AHT.
- Same weekday/time historical patterns, recent intervals, calendar/special-event features where available, and data quality flags.

A baseline can use seasonal averages and/or a scikit-learn model for offered volume and AHT. Compare against a simple baseline on a time-based holdout; publish forecast error and prediction interval when supported. Current-interval volume alone is not sufficient to make a reliable next-interval forecast.

### 6.2 Synchronous voice workload and Erlang C

For one forecast interval:
- Offered workload in Erlangs: `A = forecast_offered_contacts * forecast_AHT_seconds / interval_seconds`.
- For each candidate number of agents `N`, compute predicted service level using Erlang C and the configured answer threshold `T`; choose the smallest `N` meeting the target SLA and the configured maximum occupancy.
- Erlang C assumes an approximate steady-state queue, common service distribution assumptions, qualified agents serving that queue, and no modeled customer abandonment. If abandonment/patience materially affects outcomes, evaluate Erlang A or a calibrated simulation instead of treating Erlang C as ground truth.
- Skill groups and queues sharing agents need a multi-skill allocation/optimization step to prevent double-counting agents and to account for proficiency and donor queues.

### 6.3 Shrinkage and FTE definitions

Separate these metrics:
- `Required_on_queue_agents`: simultaneous productive agents needed in the interval.
- `Scheduled_staff_required`: gross scheduled headcount needed after applicable shrinkage.
- `FTE_hours`: forecast productive/scheduled hours aggregated over time, divided by the organization's defined FTE-hour basis.

If shrinkage `S` is defined as the proportion of scheduled paid time unavailable for handling and is not already reflected in the available-staff forecast: `scheduled_staff_required = ceil(required_on_queue_agents / (1 - S))`. If planned and unplanned loss rates are sequential independent proportions, a possible combined assumption is `S = 1 - (1 - S_planned) * (1 - S_unplanned)`. Use the organization's approved convention and never apply shrinkage twice.

Real-time recovery should primarily use observed current available agents/states; do not inflate or deflate live headcount using a generic shrinkage percentage a second time.

For asynchronous channels, base staffing on workload hours, backlog aging, response deadlines, concurrency, and productive capacity. Do not apply Erlang C automatically.

### 6.4 Named-staff recommendation for next interval

To name individual agents, the live system must join `forecast_results`/`staffing_requirements` to:
- the next interval's published schedule,
- agent state and expected release time,
- current verified skills/proficiency and training,
- language/service/market permissions,
- absence/attendance updates, break constraints, shift end, and source queue minimums.

Output a ranked assignment plan per destination queue: agent ID, qualifying skill(s), availability time, move from/to, action needed, source-queue impact, authorization, and expected impact. Otherwise return the number of required agents and an explicit data-gap message, not fabricated names.

## 7. RTM monitoring, alerts, and action governance

### 7.1 Continuous loop

1. Receive event-driven ACD/CCaaS and WFM/attendance events where available; otherwise poll at a configurable interval.
2. Normalize and deduplicate events, order by source timestamp, and maintain a current snapshot with `last_event_at` and freshness status.
3. Reconcile actual agent state to the published schedule through configurable source-state-to-activity mappings.
4. Calculate queue KPIs, skill-qualified capacity, current risk, and next-interval staffing need.
5. Generate alerts and run what-if scenarios.
6. Recommend an action, seek approval where required, execute only through an authorized vendor API/tool, confirm success, observe impact, and rollback/escalate if the action fails or worsens donor queues.
7. Write a minimal, privacy-aware audit event for every decision and action.

Initial operational targets such as 10–30-second refresh and a 60-second feed-freshness limit are examples to validate against source-platform latency and volume, not fixed assumptions. Use alert cooldown/hysteresis to prevent repeated alerts for the same unresolved condition.

### 7.2 Alert conditions

Configurable signals include:
- Forecast end-of-interval SLA below target by a configured margin.
- Actual-to-date SLA materially behind the intraday plan (labeled provisional until interval close).
- ASA/oldest wait or queue depth past a limit.
- Qualified available agents below required headcount for a defined duration.
- AHT / occupancy / abandon rate outside a control band.
- High-risk asynchronous backlog or an item close to its deadline.
- Agent absent/off-queue while scheduled on-queue beyond a tolerance.
- Feed stale, missing skill/roster data, or schedule version inconsistent with the agent state.

### 7.3 Autonomy levels

- **Level 0 — Observe:** calculate KPIs and display current/forecast risk.
- **Level 1 — Recommend:** generate ranked, explainable actions; no operational write-back.
- **Level 2 — Supervisor-approved execution:** execute approved reassignment, skill activation, break deferral, callback, or queue-priority action through controlled tools.
- **Level 3 — Pre-authorized automatic action:** only for explicitly configured, bounded, reversible actions (e.g. a defined overflow rule) with fresh data, hard constraints, a rate limit, rollback, and audit. Never enabled by default.

The LLM/LangGraph agent may explain and orchestrate tools, but deterministic code must calculate the KPI and eligibility constraints. The LLM must not directly issue arbitrary SQL or unrestricted routing/schedule changes.

## 8. Recommended data entities to support this capability

The RTM requirement adds entities beyond a basic KPI database. Final names can be normalized before the migration is written.

### Reference / operating model
- `markets`, `sites`, `channels`, `services`, `queues`, `languages`, `skills`, `activity_codes`.
- `sla_rules` / `service_targets`, with market/queue/channel scope, response threshold, effective dates, short-abandon policy, and version.

### Demand and current state
- `historical_interval_metrics`: one row per market + queue + channel + service + service-language + interval + interval length, including offered, handled, AHT, abandon, SLA and coverage indicators.
- `queue_state_snapshots`: latest/current queue measures and source freshness, or append-only timestamped snapshots if historical intraday reconstruction is required.
- `forecast_runs`, `forecast_results`: model/version, training cutoff, horizon, metrics, prediction bounds when supported, dimensions and interval.
- `staffing_assumptions`, `staffing_requirements`: SLA/occupancy assumptions, shrinkage convention, required on-queue agents, gross scheduled agents and model version.

### Staff, qualifications, and schedule
- `agents`, `agent_skills` (or `agent_language_skills` + `agent_service_skills`), `training_courses`, `agent_training_completions`.
- `agent_state_events` or `agent_state_snapshots`, plus `attendance_events` and `absence_records`.
- `schedule_publications`, `schedule_shifts`, `scheduled_activities`.
- `actual_activity_events` / `actual_activity_intervals`, plus `source_activity_mappings`.

### RTM control plane and audit
- `rtm_threshold_rules`: versioned alert/risk and freshness rules.
- `rtm_alerts`: queue/skill/agent, signal, severity, opened/resolved times, evidence reference, data-quality state.
- `rtm_recommendations`: ranked option, candidate staff, expected baseline/scenario effects, trade-offs, approval status, expiry.
- `rtm_action_log`: who/what/when/why, requested and confirmed action, vendor transaction reference, success/failure, rollback details.
- Existing `audit_logs` and `evaluation_runs` can support broader governance and repeatable testing.

Avoid creating every table in one first migration. Build the core reference + historical foundation, then staff/skill/schedule and actual-state integrations, and add RTM recommendations/actions only when those integrations and test contracts exist.

## 9. Outputs for the supervisor

1. **Queue risk board:** market, queue, channel, service language, actual/rolling SLA, forecast end-of-interval SLA, ASA/oldest wait, occupancy, backlog, available qualified agents, required headcount, gap, confidence and last-update time.
2. **Agent staffing panel:** eligible agents and skill/proficiency evidence, expected available time, source queue, proposed destination, and donor queue effect.
3. **Recovery action list:** priority, expected outcome range, customer/workforce trade-off, approval needed, expiry and rollback.
4. **Next-interval plan:** forecast volume/AHT, required on-queue agents, gross scheduled headcount, available scheduled roster, gaps by dimension, and suggested named moves where authorized data supports them.
5. **Audit and explanation:** which events/data/rules led to the recommendation; what was approved/executed; whether source systems confirmed it; measured outcome after execution.

## 10. Minimum acceptance tests before live actions

- SLA calculations match independently verified examples for each channel and market rule.
- Partial-interval results are marked provisional; closed-interval results are reproducible.
- A stale ACD feed blocks auto-action and raises a data alert.
- An agent with a missing/expired qualification is never recommended for the skill.
- A live interaction is never interrupted to move the agent.
- A multi-skilled agent is never counted as simultaneous full capacity in multiple queues.
- Moving an agent shows both destination benefit and donor queue risk.
- A break can be deferred only under policy; protected breaks are not automatically overridden.
- Callback actions report on the proper callback metric and do not falsely relabel a missed live-answer target as success.
- Staffing tests cover Erlang C assumptions, occupancy cap, shrinkage not double-counted, and asynchronous-work methods.
- Every approval, vendor write-back, failure, and rollback is auditable.
- No named-agent recommendation is emitted without fresh roster, state, skill, schedule, and authorization data.

## 11. Data gaps to resolve before implementation

1. ACD/CCaaS platform and availability of queue metrics, agent state events, skill assignments, routing APIs and callbacks.
2. WFM platform or source of truth for published schedules, versions and schedule changes.
3. HR/Training source for staff ID, site, active status, proficiency, training and certification expiry.
4. Agreed grain (15 or 30 minutes), definitions for offered/handled/abandonment and SLA per channel.
5. Market/queue/service/channel/language taxonomy and whether sales market / point-of-sale is a separate dimension.
6. Maximum occupancy, target SL and response-time threshold per queue, short-abandon treatment, and priority rules.
7. Shrinkage convention, break deferral limits, callback consent/eligibility, overtime/shift changes and approval policy.
8. Freshness/latency objectives, outage behavior, alert cooldowns, rollback and manual supervisor fallback.
9. Historical-data length and quality sufficient to train/evaluate the next-interval forecast.

**Implementation gate:** Do not create RTM tables or enable write-back until the data-source mappings, KPI definitions, skill eligibility rules, action approvals, and acceptance tests have been reviewed and agreed.
