# AeroInsight WFM Employee Profiles v1

Overlay the ZIP at the project root. It adds employee profile and skill management using existing tables in `db_airlines`; no SQL migration is required.

## Files
- `src/wfm/employee_models.py`
- `src/wfm/employee_repository.py`
- `src/wfm/employee_service.py`
- `app/pages/12_Workforce_Management.py`
- `tests/test_wfm_employee_validation.py`
- `docs/wfm_employee_profiles_v1.md`

## Install
```powershell
cd C:\Users\nader\Desktop\airline_contact_center_ai
Expand-Archive -LiteralPath "$HOME\Downloads\AeroInsight_WFM_Employee_Profiles_Trainee_Management_v1.zip" -DestinationPath "." -Force
```

## Verify
```powershell
python -m pytest tests/test_wfm_employee_validation.py -q
python -m pytest -q
python -m streamlit run app/main.py
```

The page requires `wfm.view` to view and `wfm.manage` to create employees and assign/verify skills. New skill assignments are unverified by default. Mark verified only after an actual proficiency assessment.

No new migration, test database, employee seed records, or production connector is created.
