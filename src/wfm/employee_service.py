"""Application service for WFM employee profiles and skill qualification."""
from __future__ import annotations

from datetime import date
from typing import Any

from src.harness.auth_models import AuthenticatedTenantContext
from src.wfm.employee_models import EmployeeCreateCommand, EmployeeSkillCommand
from src.wfm.employee_repository import EmployeeRepository


class EmployeeManagementService:
    def __init__(self, repository: EmployeeRepository) -> None:
        self._repository = repository

    def list_employees(self, context: AuthenticatedTenantContext) -> tuple[dict[str, Any], ...]:
        return self._repository.list_employees(context)

    def list_skills(self, context: AuthenticatedTenantContext) -> tuple[dict[str, Any], ...]:
        return self._repository.list_skills(context)

    def list_language_options(self, context: AuthenticatedTenantContext) -> tuple[dict[str, Any], ...]:
        return self._repository.list_language_options(context)

    def list_employee_skills(
        self, context: AuthenticatedTenantContext, employee_id: int
    ) -> tuple[dict[str, Any], ...]:
        return self._repository.list_employee_skills(context, employee_id)

    def create_employee(
        self,
        context: AuthenticatedTenantContext,
        *,
        employee_code: str,
        display_name: str,
        employment_type: str,
        primary_language_code: str | None,
        work_timezone: str = "Asia/Qatar",
        hire_date: date | None = None,
    ) -> int:
        return self._repository.create_employee(
            context,
            EmployeeCreateCommand(
                employee_code=employee_code,
                display_name=display_name,
                employment_type=employment_type,
                employee_status="active",
                primary_language_code=primary_language_code,
                work_timezone=work_timezone,
                hire_date=hire_date,
            ),
        )

    def save_employee_skill(
        self,
        context: AuthenticatedTenantContext,
        *,
        employee_id: int,
        skill_id: int,
        proficiency_level: int,
        is_verified: bool,
        valid_until: date | None = None,
    ) -> None:
        self._repository.save_employee_skill(
            context,
            employee_id,
            EmployeeSkillCommand(
                skill_id=skill_id,
                proficiency_level=proficiency_level,
                is_verified=is_verified,
                valid_until=valid_until,
            ),
        )
