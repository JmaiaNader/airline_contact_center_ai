"""Validated command models for WFM employee and skill management."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_EMPLOYEE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_LANGUAGE_CODE = re.compile(r"^[a-z]{2,12}$")
_TIMEZONE_CODE = re.compile(r"^(?:UTC|[A-Za-z_+-]+(?:/[A-Za-z0-9_+-]+)*)$")
_EMPLOYMENT_TYPES = {"permanent", "part_time", "contractor", "trainee"}
_EMPLOYEE_STATUSES = {"active", "inactive", "on_leave", "terminated"}


@dataclass(frozen=True, slots=True)
class EmployeeCreateCommand:
    employee_code: str
    display_name: str
    employment_type: str = "permanent"
    employee_status: str = "active"
    primary_language_code: str | None = None
    work_timezone: str = "Asia/Qatar"
    hire_date: date | None = None
    end_date: date | None = None


@dataclass(frozen=True, slots=True)
class EmployeeSkillCommand:
    skill_id: int
    proficiency_level: int
    is_verified: bool = False
    valid_until: date | None = None


def validate_employee_command(command: EmployeeCreateCommand) -> EmployeeCreateCommand:
    """Normalize and validate user-entered employee profile fields."""
    if not isinstance(command, EmployeeCreateCommand):
        raise TypeError("EmployeeCreateCommand is required.")

    employee_code = command.employee_code.strip()
    display_name = command.display_name.strip()
    employment_type = command.employment_type.strip().lower()
    employee_status = command.employee_status.strip().lower()
    timezone_name = command.work_timezone.strip()
    language = (
        command.primary_language_code.strip().lower()
        if command.primary_language_code is not None and command.primary_language_code.strip()
        else None
    )

    if not _EMPLOYEE_CODE.fullmatch(employee_code):
        raise ValueError("Employee code must be 1-64 letters, digits, dots, underscores or hyphens.")
    if not display_name or len(display_name) > 128:
        raise ValueError("Display name is required and must not exceed 128 characters.")
    if employment_type not in _EMPLOYMENT_TYPES:
        raise ValueError("Employment type must be permanent, part_time, contractor or trainee.")
    if employee_status not in _EMPLOYEE_STATUSES:
        raise ValueError("Employee status is invalid.")
    if language is not None and not _LANGUAGE_CODE.fullmatch(language):
        raise ValueError("Primary language code must be a lowercase language/reference code.")
    if not timezone_name or len(timezone_name) > 64 or not _TIMEZONE_CODE.fullmatch(timezone_name):
        raise ValueError("Work timezone must be a valid-looking IANA timezone name, e.g. Asia/Qatar.")
    if command.hire_date is not None and not isinstance(command.hire_date, date):
        raise ValueError("Hire date must be a date value.")
    if command.end_date is not None and not isinstance(command.end_date, date):
        raise ValueError("End date must be a date value.")
    if command.hire_date and command.end_date and command.end_date < command.hire_date:
        raise ValueError("End date cannot be earlier than hire date.")

    return EmployeeCreateCommand(
        employee_code=employee_code,
        display_name=display_name,
        employment_type=employment_type,
        employee_status=employee_status,
        primary_language_code=language,
        work_timezone=timezone_name,
        hire_date=command.hire_date,
        end_date=command.end_date,
    )


def validate_employee_skill_command(command: EmployeeSkillCommand) -> EmployeeSkillCommand:
    """Validate one language, channel or service proficiency record."""
    if not isinstance(command, EmployeeSkillCommand):
        raise TypeError("EmployeeSkillCommand is required.")
    if isinstance(command.skill_id, bool) or not isinstance(command.skill_id, int) or command.skill_id <= 0:
        raise ValueError("Skill ID must be a positive integer.")
    if (
        isinstance(command.proficiency_level, bool)
        or not isinstance(command.proficiency_level, int)
        or command.proficiency_level < 1
        or command.proficiency_level > 5
    ):
        raise ValueError("Proficiency level must be an integer from 1 to 5.")
    if not isinstance(command.is_verified, bool):
        raise ValueError("is_verified must be a boolean.")
    if command.valid_until is not None and not isinstance(command.valid_until, date):
        raise ValueError("valid_until must be a date value.")
    return command


def require_context_permission(context: object, permission: str) -> int:
    """Require a server-resolved tenant context and return its trusted tenant ID."""
    if context is None or not callable(getattr(context, "has_permission", None)):
        raise TypeError("A server-resolved AuthenticatedTenantContext is required.")
    if not context.has_permission(permission):
        raise PermissionError(f"Permission required: {permission}")
    tenant_id = getattr(context, "tenant_id", None)
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("Authenticated tenant context has an invalid tenant ID.")
    return tenant_id
