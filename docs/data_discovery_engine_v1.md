# Data Discovery & Semantic Mapping Engine — v1

## Status

First implementation slice for AeroInsight. Deterministic and LLM-free. CSV is the only connector in this slice. It does not connect to MySQL, persist mappings, expose an API, or send data to a model.

## Goal

Profile a source schema, suggest candidate mappings to a governed semantic catalog, expose data quality concerns, and require an explicit human approval before a mapping is considered approved.

## Safety and correctness rules

- A column name, inferred type, or numeric range is evidence for review, not proof of business equivalence.
- `fit_score` is a heuristic ranking score, not a calibrated probability.
- The engine never auto-approves a mapping.
- Approval is tenant-scoped and includes source ID, reviewer, UTC timestamp, and confirmations required by the chosen concept.
- Ambiguous, unmapped, and type-mismatched fields cannot be approved through this initial approval function.
- CSV reading is bounded by `max_rows`; truncated profiles disclose partial coverage.
- Sample values may contain sensitive content. This local prototype is for synthetic data; do not profile production passenger data until privacy controls, permissions, redaction, and retention are designed.
- No data is uploaded, no SQL is generated, and no database is changed.

## Run tests

From the project root with the project's virtual environment active:

```powershell
python -m pytest tests/test_data_discovery_engine.py -q
```

## Example in Python

```python
from pathlib import Path
from src.discovery import assess_field_mapping, profile_csv

report = profile_csv(Path("examples/synthetic_data/company_a_customer_feedback.csv"))
for field in report.fields:
    assessment = assess_field_mapping(field)
    print(field.name, field.inferred_type, assessment.status)
    for candidate in assessment.candidates:
        print("  ", candidate.concept_key, candidate.fit_score, candidate.rationale)
```

## Known limits / next stage

1. The catalog is intentionally small and manually governed.
2. Numeric ranges are profiled but are not automatically interpreted as equivalent scales.
3. There is no persistent tenant registry or approved-mapping store yet; approvals are typed audit objects only.
4. Source connectors beyond CSV, relational constraints, permissions, and role management are not implemented.
5. Next stage should be a review UI for mapping candidates and approvals, still without an LLM. Then persist approved mapping versions per tenant/source with tests proving tenant isolation.
