from datetime import date
from types import SimpleNamespace

import pytest

from src.wfm.employee_models import (
    EmployeeCreateCommand,
    EmployeeSkillCommand,
    require_context_permission,
    validate_employee_command,
    validate_employee_skill_command,
)


def valid_profile(**overrides):
    values = dict(
        employee_code="AGT-0001",
        display_name="Test Agent",
        employment_type="permanent",
        employee_status="active",
        primary_language_code="en",
        work_timezone="Asia/Qatar",
        hire_date=date(2026, 1, 1),
        end_date=None,
    )
    values.update(overrides)
    return EmployeeCreateCommand(**values)


def test_employee_profile_normalizes_code_name_and_language():
    result = validate_employee_command(valid_profile(employee_code=" AGT-01 ", display_name=" Agent ", primary_language_code="EN"))
    assert result.employee_code == "AGT-01"
    assert result.display_name == "Agent"
    assert result.primary_language_code == "en"


@pytest.mark.parametrize("employment_type", ["permanent", "part_time", "contractor", "trainee"])
def test_supported_employment_types(employment_type):
    assert validate_employee_command(valid_profile(employment_type=employment_type)).employment_type == employment_type


@pytest.mark.parametrize("bad_code", ["", "AGT 01", "AGT/1", "x" * 65])
def test_invalid_employee_code_rejected(bad_code):
    with pytest.raises(ValueError):
        validate_employee_command(valid_profile(employee_code=bad_code))


def test_display_name_required():
    with pytest.raises(ValueError):
        validate_employee_command(valid_profile(display_name="   "))


def test_invalid_employment_type_rejected():
    with pytest.raises(ValueError):
        validate_employee_command(valid_profile(employment_type="intern"))


def test_end_date_cannot_precede_hire_date():
    with pytest.raises(ValueError):
        validate_employee_command(valid_profile(hire_date=date(2026, 5, 1), end_date=date(2026, 4, 30)))


def test_invalid_timezone_format_rejected():
    with pytest.raises(ValueError):
        validate_employee_command(valid_profile(work_timezone="Asia/Qatar;DROP"))


def test_primary_language_can_be_empty():
    assert validate_employee_command(valid_profile(primary_language_code=None)).primary_language_code is None


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_proficiency_levels_one_to_five_are_valid(level):
    assert validate_employee_skill_command(EmployeeSkillCommand(skill_id=1, proficiency_level=level)).proficiency_level == level


@pytest.mark.parametrize("level", [0, 6, True, 2.5])
def test_invalid_proficiency_level_rejected(level):
    with pytest.raises(ValueError):
        validate_employee_skill_command(EmployeeSkillCommand(skill_id=1, proficiency_level=level))


def test_skill_id_must_be_positive():
    with pytest.raises(ValueError):
        validate_employee_skill_command(EmployeeSkillCommand(skill_id=0, proficiency_level=3))


def test_unverified_skill_is_allowed_for_trainee_progression():
    command = validate_employee_skill_command(EmployeeSkillCommand(skill_id=10, proficiency_level=1, is_verified=False))
    assert command.is_verified is False


def test_context_permission_returns_tenant_id():
    context = SimpleNamespace(tenant_id=7, has_permission=lambda permission: permission == "wfm.manage")
    assert require_context_permission(context, "wfm.manage") == 7


def test_missing_permission_is_denied():
    context = SimpleNamespace(tenant_id=7, has_permission=lambda permission: False)
    with pytest.raises(PermissionError):
        require_context_permission(context, "wfm.manage")


def test_untrusted_context_shape_is_rejected():
    with pytest.raises(TypeError):
        require_context_permission({"tenant_id": 7}, "wfm.manage")
