AeroInsight WFM Step 3 - Service Skills and Queue Requirements
Target database: db_airlines
Tenant: demo_airline

What it does:
- Adds three service skills: Booking, Change Booking, Loyalty (if missing).
- Adds service and channel requirements for the six existing demo queues.
- Adds Arabic OR English language options for Voice queues.
- Adds English-only language requirement for WhatsApp queues.
- Uses minimum proficiency level 3 (Proficient).
- Is idempotent: existing service skills and queue-skill requirement rows are not duplicated.
- Creates no employees, employee skill assignments, schedules, or agent events.
- Uses one DML transaction; no schema changes / no migration.

Important matching rule:
queue_skill_requirements has no explicit any-of group column. The future WFM skill matcher
must enforce service AND channel as ALL-OF requirements, but language skills as ANY-OF within
the language category for a queue. For example, a Voice queue accepts a verified Arabic OR
English skill; it does not require both. WhatsApp accepts English only.

Run in MySQL Workbench:
1. Open 007_seed_demo_service_skills_and_queue_requirements.sql
2. Confirm target_schema = db_airlines and demo_airline_tenant_id is not NULL.
3. Execute the script once.
4. Expected summary: service_skills = 3 and active_queue_skill_requirements = 21.
5. Check each queue row: Voice has 4 requirements (service, channel, Arabic, English); WhatsApp has 3 (service, channel, English).

No production employee records are created. No actual assignment or staffing calculation runs in this step.
