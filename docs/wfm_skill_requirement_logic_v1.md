# WFM Skill Requirement Logic v1

## Why this change is required

The current `queue_skill_requirements` table initially stored one row per required skill, but did not say whether rows were AND or OR. The seeded Voice queues contain both Arabic and English language rows. Treating every row as a mandatory AND would incorrectly require bilingual agents for every Voice queue.

## Explicit model

Migration 006 adds:

- `requirement_group_code`: groups related skill requirements.
- `requirement_match_mode`: `all_of` or `any_of`.

The seed's intended semantics become explicit:

- `service` group: `all_of`.
- `channel` group: `all_of`.
- `language` group: `any_of`.

Therefore Voice requires its channel skill AND its service skill AND (Arabic OR English). WhatsApp requires its channel skill AND its service skill AND English (the one-member language any-of group).

## Employee qualification policy

An employee skill qualifies only when it is active, verified, meets minimum proficiency, and has not expired. Required groups must all pass. Preferred requirements do not block eligibility. Empty/invalid requirements fail closed.

## Apply

1. Run `database/checks/006_preflight.sql`.
2. Ensure target schema is `db_airlines`, both new columns are absent, and existing demo tenant requirements are present.
3. Run `database/migrations/006_explicit_queue_skill_logic.sql` once.
4. Run `database/checks/006_postflight.sql`.

No employee records are created and no employee/schedule data is changed.
