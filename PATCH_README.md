# AeroInsight Stage 003-A — Identity & Access Design

This patch adds one design document only:

`docs/tenant_identity_access_spec_v1.md`

## Apply

Extract this ZIP into the root of the existing `airline_contact_center_ai` repository, preserving folders.

PowerShell example:

```powershell
Expand-Archive -LiteralPath "$HOME\Downloads\aeroinsight_stage_003a_identity_access_spec.zip" -DestinationPath "C:\Users\nader\Desktop\airline_contact_center_ai" -Force
```

Then review `docs/tenant_identity_access_spec_v1.md`.

## Safety

- This patch contains no SQL migration.
- It does not modify or connect to MySQL.
- It does not change Migration 001 or Migration 002.
- Do not create identity/access tables until the design and initial authentication/permission decisions are approved.
