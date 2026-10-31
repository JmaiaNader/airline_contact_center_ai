# AeroInsight WFM Foundation v1

## Purpose

Migration 005 adds the minimum tenant-scoped workforce foundation needed for employee skills, schedules, planned activities, queue skill requirements, and actual agent-state event history. It is additive and targets the existing `db_airlines` schema.

## Tables

1. `employees`: minimal employee/trainee master. OIDC users are intentionally separate from workforce employees.
2. `workforce_skills`: tenant-specific language, service, channel, or other skill catalog.
3. `employee_skills`: employee proficiency (1-5), verification and validity.
4. `workforce_shifts`: planned/published shifts stored as UTC instants with the IANA timezone retained for local reconstruction.
5. `workforce_shift_activities`: break, lunch, training, meeting, coaching, occupied, idle, or other activity intervals.
6. `queue_skill_requirements`: minimum proficiency and required/preferred skill for a tenant queue.
7. `workforce_agent_state_events`: append-only state transitions. Current state and adherence are derived from the event stream in the next application layer.

## Security and tenancy

- Every WFM table has `tenant_id`.
- Employee, skill, shift, queue and membership links use tenant-scoped composite foreign keys where applicable.
- Do not accept `tenant_id`, `employee_id`, `shift_id`, or permission claims from arbitrary UI input. Resolve the tenant through `AuthenticatedTenantContext`.
- Read operations require `wfm.view`; workforce writes require `wfm.manage`.
- Company Admin and WFM Planner roles already receive these permissions from Migration 003.
- No personal email, phone, date of birth, or authentication credential is stored in the employee master. OIDC identity remains in the identity subsystem.

## Time model

All persisted instants are UTC (`DATETIME(6)`). `shift_timezone` retains an IANA zone such as `Asia/Qatar` for reconstructing local roster presentation and daylight-saving behaviour. Do not store Qatar local wall-clock time as if it were UTC.

## Seeding

Migration 005 seeds only tenant-scoped language and channel skills from the existing reference catalogs. It creates no employees, trainees, schedules, or agent-state events. Services and queues in the user's latest schema check were empty; service skills and queue skill requirements should be created only after those reference records exist.

## Execution

1. Run `database/checks/005_preflight.sql` in MySQL Workbench.
2. Verify the current schema is `db_airlines`, all parent tables exist, all seven WFM tables are absent, and `wfm.view` / `wfm.manage` are present.
3. Run `database/migrations/005_wfm_workforce_foundation.sql` once.
4. Run `database/checks/005_postflight.sql`.
5. Do not rerun Migration 005 after a partial DDL failure without inspecting which tables exist; MySQL DDL commits implicitly.

## Not included yet

This migration does not calculate staffing, forecast volume, implement Erlang C, or execute intraday actions. It establishes the schema required for the next WFM application layer. Shift overlap, activity containment, skill proficiency matching and state-event ordering are enforced in Python service logic in the next step; MySQL cannot express all temporal exclusion rules with ordinary foreign keys/check constraints.
