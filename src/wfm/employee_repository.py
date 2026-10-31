"""Tenant-scoped MySQL repository for employee profiles and skill records."""
from __future__ import annotations

import json
from datetime import datetime, time
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from src.harness.auth_models import AuthenticatedTenantContext
from src.wfm.employee_models import (
    EmployeeCreateCommand,
    EmployeeSkillCommand,
    require_context_permission,
    validate_employee_command,
    validate_employee_skill_command,
)


class EmployeeRepository:
    """WFM CRUD repository. All queries bind tenant_id from trusted auth context."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _audit(
        connection: Any,
        context: AuthenticatedTenantContext,
        *,
        action_code: str,
        target_type: str,
        target_reference: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO audit_events (
                    tenant_id, actor_membership_id, action_code, target_type,
                    target_reference, outcome_code, event_details_json
                ) VALUES (
                    :tenant_id, :membership_id, :action_code, :target_type,
                    :target_reference, 'success', :event_details_json
                )
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "membership_id": context.membership_id,
                "action_code": action_code,
                "target_type": target_type,
                "target_reference": target_reference,
                "event_details_json": json.dumps(details, separators=(",", ":")),
            },
        )

    def list_language_options(self, context: AuthenticatedTenantContext) -> tuple[dict[str, Any], ...]:
        tenant_id = require_context_permission(context, "wfm.view")
        statement = text(
            """
            SELECT DISTINCT language_code
            FROM workforce_skills
            WHERE tenant_id = :tenant_id
              AND skill_category = 'language'
              AND is_active = 1
              AND language_code IS NOT NULL
            ORDER BY language_code
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"tenant_id": tenant_id}).mappings().all()
        return tuple(dict(row) for row in rows)

    def list_skills(self, context: AuthenticatedTenantContext) -> tuple[dict[str, Any], ...]:
        tenant_id = require_context_permission(context, "wfm.view")
        statement = text(
            """
            SELECT skill_id, skill_code, skill_name, skill_category,
                   language_code, service_code, channel_code
            FROM workforce_skills
            WHERE tenant_id = :tenant_id
              AND is_active = 1
            ORDER BY skill_category, skill_name, skill_id
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"tenant_id": tenant_id}).mappings().all()
        return tuple(dict(row) for row in rows)

    def list_employees(self, context: AuthenticatedTenantContext) -> tuple[dict[str, Any], ...]:
        tenant_id = require_context_permission(context, "wfm.view")
        statement = text(
            """
            SELECT
                e.employee_id,
                e.employee_code,
                e.display_name,
                e.employment_type,
                e.employee_status,
                e.primary_language_code,
                e.work_timezone,
                e.hire_date,
                e.end_date,
                COUNT(es.employee_skill_id) AS skill_count,
                COALESCE(GROUP_CONCAT(
                  CONCAT(
    ws.skill_code,
    ' [L',
    es.proficiency_level,
    '] ',
    CASE
        WHEN es.is_verified = 1 THEN '(verified)'
        ELSE '(unverified)'
    END
)
                    ORDER BY ws.skill_category, ws.skill_code SEPARATOR ' | '
                ), '') AS skills_summary
            FROM employees e
            LEFT JOIN employee_skills es
              ON es.tenant_id = e.tenant_id
             AND es.employee_id = e.employee_id
             AND es.skill_status = 'active'
            LEFT JOIN workforce_skills ws
              ON ws.tenant_id = es.tenant_id
             AND ws.skill_id = es.skill_id
            WHERE e.tenant_id = :tenant_id
            GROUP BY e.employee_id, e.employee_code, e.display_name,
                     e.employment_type, e.employee_status,
                     e.primary_language_code, e.work_timezone,
                     e.hire_date, e.end_date
            ORDER BY e.employee_code
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"tenant_id": tenant_id}).mappings().all()
        return tuple(dict(row) for row in rows)

    def list_employee_skills(
        self, context: AuthenticatedTenantContext, employee_id: int
    ) -> tuple[dict[str, Any], ...]:
        tenant_id = require_context_permission(context, "wfm.view")
        if isinstance(employee_id, bool) or not isinstance(employee_id, int) or employee_id <= 0:
            raise ValueError("Employee ID must be a positive integer.")
        statement = text(
            """
            SELECT
                es.employee_skill_id, es.employee_id, es.skill_id,
                ws.skill_code, ws.skill_name, ws.skill_category,
                ws.language_code, ws.service_code, ws.channel_code,
                es.proficiency_level, es.is_verified, es.skill_status,
                es.assessed_at_utc, es.valid_until_utc
            FROM employee_skills es
            INNER JOIN workforce_skills ws
              ON ws.tenant_id = es.tenant_id
             AND ws.skill_id = es.skill_id
            INNER JOIN employees e
              ON e.tenant_id = es.tenant_id
             AND e.employee_id = es.employee_id
            WHERE es.tenant_id = :tenant_id
              AND es.employee_id = :employee_id
            ORDER BY ws.skill_category, ws.skill_name
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement, {"tenant_id": tenant_id, "employee_id": employee_id}
            ).mappings().all()
        return tuple(dict(row) for row in rows)

    def create_employee(
        self, context: AuthenticatedTenantContext, command: EmployeeCreateCommand
    ) -> int:
        tenant_id = require_context_permission(context, "wfm.manage")
        clean = validate_employee_command(command)
        statement = text(
            """
            INSERT INTO employees (
                tenant_id, employee_code, display_name, employment_type,
                employee_status, primary_language_code, work_timezone,
                hire_date, end_date
            ) VALUES (
                :tenant_id, :employee_code, :display_name, :employment_type,
                :employee_status, :primary_language_code, :work_timezone,
                :hire_date, :end_date
            )
            """
        )
        try:
            with self._engine.begin() as connection:
                result = connection.execute(
                    statement,
                    {
                        "tenant_id": tenant_id,
                        "employee_code": clean.employee_code,
                        "display_name": clean.display_name,
                        "employment_type": clean.employment_type,
                        "employee_status": clean.employee_status,
                        "primary_language_code": clean.primary_language_code,
                        "work_timezone": clean.work_timezone,
                        "hire_date": clean.hire_date,
                        "end_date": clean.end_date,
                    },
                )
                employee_id = int(result.lastrowid)
                self._audit(
                    connection,
                    context,
                    action_code="wfm.employee_created",
                    target_type="employee",
                    target_reference=str(employee_id),
                    details={
                        "employment_type": clean.employment_type,
                        "employee_status": clean.employee_status,
                        "primary_language_code": clean.primary_language_code,
                    },
                )
                return employee_id
        except IntegrityError as exc:
            message = str(exc.orig).lower()
            if "uq005_employees_tenant_code" in message or "duplicate" in message:
                raise ValueError("This employee code already exists in the active company.") from exc
            raise

    def save_employee_skill(
        self,
        context: AuthenticatedTenantContext,
        employee_id: int,
        command: EmployeeSkillCommand,
    ) -> None:
        tenant_id = require_context_permission(context, "wfm.manage")
        if isinstance(employee_id, bool) or not isinstance(employee_id, int) or employee_id <= 0:
            raise ValueError("Employee ID must be a positive integer.")
        clean = validate_employee_skill_command(command)
        valid_until_utc = (
            datetime.combine(clean.valid_until, time.max).replace(tzinfo=None)
            if clean.valid_until is not None else None
        )
        with self._engine.begin() as connection:
            employee = connection.execute(
                text(
                    "SELECT employment_type, employee_status FROM employees "
                    "WHERE tenant_id = :tenant_id AND employee_id = :employee_id FOR UPDATE"
                ),
                {"tenant_id": tenant_id, "employee_id": employee_id},
            ).mappings().one_or_none()
            if employee is None:
                raise ValueError("Employee was not found in the active company.")
            if employee["employee_status"] == "terminated":
                raise ValueError("Skills cannot be assigned to a terminated employee.")

            skill = connection.execute(
                text(
                    "SELECT skill_code FROM workforce_skills "
                    "WHERE tenant_id = :tenant_id AND skill_id = :skill_id AND is_active = 1"
                ),
                {"tenant_id": tenant_id, "skill_id": clean.skill_id},
            ).mappings().one_or_none()
            if skill is None:
                raise ValueError("Active skill was not found in the current company.")

            connection.execute(
                text(
                    """
                    INSERT INTO employee_skills (
                        tenant_id, employee_id, skill_id, proficiency_level,
                        is_verified, skill_status, assessed_at_utc, valid_until_utc
                    ) VALUES (
                        :tenant_id, :employee_id, :skill_id, :proficiency_level,
                        :is_verified, 'active',
                        CASE WHEN :is_verified = 1 THEN UTC_TIMESTAMP(6) ELSE NULL END,
                        :valid_until_utc
                    )
                    ON DUPLICATE KEY UPDATE
                        proficiency_level = VALUES(proficiency_level),
                        is_verified = VALUES(is_verified),
                        skill_status = 'active',
                        assessed_at_utc = CASE WHEN VALUES(is_verified) = 1 THEN UTC_TIMESTAMP(6) ELSE NULL END,
                        valid_until_utc = VALUES(valid_until_utc),
                        updated_at_utc = UTC_TIMESTAMP(6)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "employee_id": employee_id,
                    "skill_id": clean.skill_id,
                    "proficiency_level": clean.proficiency_level,
                    "is_verified": 1 if clean.is_verified else 0,
                    "valid_until_utc": valid_until_utc,
                },
            )
            self._audit(
                connection,
                context,
                action_code="wfm.employee_skill_saved",
                target_type="employee_skill",
                target_reference=f"{employee_id}:{clean.skill_id}",
                details={
                    "skill_code": str(skill["skill_code"]),
                    "proficiency_level": clean.proficiency_level,
                    "is_verified": clean.is_verified,
                    "employment_type": str(employee["employment_type"]),
                },
            )
