AeroInsight WFM Reference Data Seed - Step 1

Target: db_airlines
Tenant: demo_airline

This SQL file is INSERT-only and idempotent. It creates, only if missing:
- Services: booking, change_booking, loyalty
- Queues: Voice and WhatsApp for each service (6 queues total)

It does not create employee records, schedules, shifts, activities, or queue-skill requirements.
It does not modify or delete existing rows. It uses UTC timestamps.

Run once in MySQL Workbench. Re-running is designed not to duplicate these service/queue codes.
Expected summary: 3 seeded services and 6 seeded queues.

Business assumptions carried forward from the project requirements:
- Services: Booking, Change Booking, Loyalty
- Channels: Voice and WhatsApp
- WhatsApp staffing skills will be constrained to English in the subsequent skill/queue requirement setup.
- Language is not embedded in queue names because queues can have multiple skill requirements.

Important:
- Confirm the SQL output reports 3 services and 6 queues.
- If counts differ, stop and share the output; do not manually insert duplicates.
