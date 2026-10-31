# AeroInsight Root Cause Investigation UI v1

Extract this ZIP into the project root.

New files:
- `app/pages/11_Root_Cause_Investigation.py`
- `src/analytics/root_cause_service.py`
- `tests/test_root_cause_service.py`
- `docs/root_cause_investigation_streamlit_v1.md`

Updated file:
- `src/analytics/root_cause_repository.py` (now filters by selected source and loaded ingestion batches)

No database migration is included. All MySQL access is read-only and scoped to the verified tenant and selected source.

Run focused tests:
```powershell
python -m pytest tests/test_root_cause_engine.py tests/test_root_cause_repository.py tests/test_root_cause_service.py -q
```
Run the full suite:
```powershell
python -m pytest -q
```
Start Streamlit:
```powershell
python -m streamlit run app/main.py
```
Then open page `11 — Root Cause Investigation`.
