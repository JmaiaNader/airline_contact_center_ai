# WFM Employee Profiles & Trainee Management v1

## Scope

This additive application layer uses the existing Migration 005 tables in `db_airlines`:

- `employees`
- `workforce_skills`
- `employee_skills`
- `audit_events`

It does not create a migration and does not insert fabricated employees.

## Employee types

`permanent`, `part_time`, `contractor`, `trainee` are stored in `employees.employment_type`.
`primary_language_code` is informational. Work language eligibility is determined only by separate rows in `employee_skills`.

## Multilingual support

Each language is a separate skill row. An employee may have Arabic only, English only, both, or more languages. A queue's `ANY OF` language requirement is evaluated by the existing `src/wfm/skill_matcher.py` implementation. Service and channel requirements remain `ALL OF`.

## Qualification rules

A skill can be recorded at proficiency 1-5. New skill assignments default to unverified. The existing skill matcher only counts a skill if it is active, verified, meets the configured minimum proficiency, and has not expired.

- 1: Trainee
- 2: Basic
- 3: Proficient
- 4: Advanced
- 5: Expert

A trainee profile is represented with `employment_type='trainee'`; no separate OIDC user is created. Employees and application users are distinct entities.

## Permissions

- `wfm.view`: list employee profiles and skill records.
- `wfm.manage`: create employee profiles, assign/update skills, and mark skills verified.

Every repository operation binds `tenant_id` from the server-resolved `AuthenticatedTenantContext`. The page never accepts a tenant ID from user input.

## Audit

Employee creation and each skill save/update append an `audit_events` row in the same database transaction. Sensitive personal information is not copied into audit metadata.

## Run

```powershell
python -m pytest tests/test_wfm_employee_validation.py -q
python -m pytest -q
python -m streamlit run app/main.py
```

Open page `12 — Workforce Management`.
