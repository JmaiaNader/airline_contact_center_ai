from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

import streamlit as st

from app.authentication import require_authenticated_tenant_context
from src.config.settings import get_settings
from src.database.connection import create_db_engine
from src.wfm.employee_repository import EmployeeRepository
from src.wfm.employee_service import EmployeeManagementService

st.set_page_config(page_title="Workforce Management", page_icon="👥", layout="wide")
st.title("👥 AeroInsight — Workforce Management")
st.caption("Employee profiles · Multilingual skills · Trainee qualification · Tenant-scoped")

tenant_context = require_authenticated_tenant_context()
if not tenant_context.has_permission("wfm.view"):
    st.error("Your active company membership does not grant wfm.view.")
    st.stop()
can_manage = tenant_context.has_permission("wfm.manage")

settings = get_settings()
engine = create_db_engine(settings)
service = EmployeeManagementService(EmployeeRepository(engine))

st.info(
    f"Active company: **{tenant_context.tenant_display_name}** (`{tenant_context.tenant_code}`). "
    "Employee and skill records are stored in the existing db_airlines database. "
    "Every employee can hold one or many language skills; primary language is informational only."
)

try:
    employees = service.list_employees(tenant_context)
    skills = service.list_skills(tenant_context)
    language_options = [str(row["language_code"]) for row in service.list_language_options(tenant_context)]

    metric_cols = st.columns(3)
    metric_cols[0].metric("Employees", len(employees))
    metric_cols[1].metric("Trainees", sum(1 for row in employees if row["employment_type"] == "trainee"))
    metric_cols[2].metric("Active skills in catalog", len(skills))

    tab_directory, tab_create, tab_skills = st.tabs(
        ["Employee Directory", "Add Employee", "Skills & Qualification"]
    )

    with tab_directory:
        st.subheader("Employee Directory")
        if employees:
            st.dataframe(
                [
                    {
                        "Employee ID": row["employee_id"],
                        "Code": row["employee_code"],
                        "Name": row["display_name"],
                        "Type": row["employment_type"],
                        "Status": row["employee_status"],
                        "Primary language": row["primary_language_code"] or "—",
                        "Timezone": row["work_timezone"],
                        "Skill count": row["skill_count"],
                        "Skills": row["skills_summary"] or "No skills assigned",
                    }
                    for row in employees
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No employee profiles exist for this company yet. Add the first employee or trainee.")

    with tab_create:
        st.subheader("Create Employee Profile")
        if not can_manage:
            st.info("You have view access only. wfm.manage is required to create employees.")
        else:
            with st.form("create_employee_form", clear_on_submit=True):
                left, right = st.columns(2)
                with left:
                    employee_code = st.text_input("Employee code", max_chars=64, placeholder="AGT-0001")
                    display_name = st.text_input("Display name", max_chars=128)
                    employment_type = st.selectbox(
                        "Employment type",
                        ["permanent", "part_time", "contractor", "trainee"],
                        format_func=lambda value: {
                            "permanent": "Permanent Agent",
                            "part_time": "Part-time Agent",
                            "contractor": "Contractor",
                            "trainee": "Trainee",
                        }[value],
                    )
                with right:
                    primary_language = st.selectbox(
                        "Primary language (informational)",
                        options=["—"] + language_options,
                        help="This is the employee's primary language only. Additional work languages are assigned as separate verified skills.",
                    )
                    work_timezone = st.text_input("Work timezone", value="Asia/Qatar", max_chars=64)
                    has_hire_date = st.checkbox("Set hire date", value=True)
                    hire_date = st.date_input("Hire date", value=date.today()) if has_hire_date else None
                submitted = st.form_submit_button("Create employee profile", type="primary", use_container_width=True)
                if submitted:
                    try:
                        if not can_manage:
                            raise PermissionError("wfm.manage is required.")
                        new_id = service.create_employee(
                            tenant_context,
                            employee_code=employee_code,
                            display_name=display_name,
                            employment_type=employment_type,
                            primary_language_code=None if primary_language == "—" else primary_language,
                            work_timezone=work_timezone,
                            hire_date=hire_date,
                        )
                        st.success(f"Employee profile created successfully. Employee ID: {new_id}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not create employee ({type(exc).__name__}): {exc}")

    with tab_skills:
        st.subheader("Assign Languages, Services and Channels")
        st.caption(
            "Assign each language as a separate skill. Arabic-only, English-only and bilingual employees "
            "are all supported. A skill remains ineligible for queue routing until verified and at the required proficiency."
        )
        if not employees:
            st.info("Create an employee profile first.")
        elif not skills:
            st.warning("No active skills exist in this tenant's skill catalog.")
        else:
            employee_by_id = {int(row["employee_id"]): row for row in employees}
            selected_employee_id = st.selectbox(
                "Employee",
                options=list(employee_by_id),
                format_func=lambda key: (
                    f"{employee_by_id[key]['employee_code']} — {employee_by_id[key]['display_name']} "
                    f"({employee_by_id[key]['employment_type']})"
                ),
            )
            employee_skill_rows = service.list_employee_skills(tenant_context, int(selected_employee_id))
            if employee_skill_rows:
                st.dataframe(
                    [
                        {
                            "Skill": row["skill_name"],
                            "Category": row["skill_category"],
                            "Code": row["skill_code"],
                            "Proficiency": row["proficiency_level"],
                            "Verified": "Yes" if row["is_verified"] else "No",
                            "Status": row["skill_status"],
                            "Valid until (UTC)": row["valid_until_utc"] or "—",
                        }
                        for row in employee_skill_rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No skills assigned to this employee yet.")

            if not can_manage:
                st.info("You have view access only. wfm.manage is required to assign or verify skills.")
            else:
                skill_by_id = {int(row["skill_id"]): row for row in skills}
                with st.form("assign_employee_skill_form", clear_on_submit=True):
                    selected_skill_id = st.selectbox(
                        "Skill to assign or update",
                        options=list(skill_by_id),
                        format_func=lambda key: (
                            f"{skill_by_id[key]['skill_category'].title()} — "
                            f"{skill_by_id[key]['skill_name']} ({skill_by_id[key]['skill_code']})"
                        ),
                    )
                    proficiency = st.select_slider(
                        "Proficiency level",
                        options=[1, 2, 3, 4, 5],
                        value=1 if employee_by_id[selected_employee_id]["employment_type"] == "trainee" else 3,
                        format_func=lambda value: {
                            1: "1 — Trainee",
                            2: "2 — Basic",
                            3: "3 — Proficient",
                            4: "4 — Advanced",
                            5: "5 — Expert",
                        }[value],
                    )
                    verified = st.checkbox(
                        "Skill has been assessed and verified",
                        value=False,
                        help="Only verified skills meeting queue proficiency requirements can qualify an employee for routing.",
                    )
                    has_validity = st.checkbox("Set skill expiry date", value=False)
                    valid_until = st.date_input("Valid until", value=date.today()) if has_validity else None
                    saved = st.form_submit_button("Save employee skill", type="primary", use_container_width=True)
                    if saved:
                        try:
                            if not can_manage:
                                raise PermissionError("wfm.manage is required.")
                            service.save_employee_skill(
                                tenant_context,
                                employee_id=int(selected_employee_id),
                                skill_id=int(selected_skill_id),
                                proficiency_level=int(proficiency),
                                is_verified=bool(verified),
                                valid_until=valid_until,
                            )
                            st.success("Employee skill saved. Eligibility will be recalculated by the WFM skill matcher.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save employee skill ({type(exc).__name__}): {exc}")
finally:
    engine.dispose()
