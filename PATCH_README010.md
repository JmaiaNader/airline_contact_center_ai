# AeroInsight Statistical Analysis & Anomaly Detection v1

This is an additive patch for the existing project. It reuses the existing deterministic KPI engine and authenticated tenant context. It adds a pure-Python statistical module, a Streamlit page, focused tests, and documentation.

No SQL migration, no test database, and no writes to `db_airlines` are included. Analysis is read-only and tenant-scoped through `KPIAnalysisService`.

Run focused and full tests after extraction. Synthetic datasets remain labelled as synthetic; anomaly findings are not production-certified and do not claim root causes.
