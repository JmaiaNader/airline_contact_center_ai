# AeroInsight WFM Skill Logic Fix v1

This patch makes queue skill matching logic explicit before employee profiles are entered.

## Files
- `database/checks/006_preflight.sql`
- `database/migrations/006_explicit_queue_skill_logic.sql`
- `database/checks/006_postflight.sql`
- `src/wfm/skill_matcher.py`
- `tests/test_wfm_skill_matcher.py`
- `docs/wfm_skill_requirement_logic_v1.md`

## Important
- Target DB: `db_airlines` only.
- Migration 006 is a one-time DDL migration; run it once after preflight.
- Existing service/channel requirements remain ALL-OF.
- Language requirements within a queue become ANY-OF.
- No employee records are fabricated.
- Storage remains UTC.

Run Python tests:

```powershell
python -m pytest tests/test_wfm_skill_matcher.py -q
```
