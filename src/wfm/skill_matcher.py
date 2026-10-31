"""Deterministic, fail-closed matching of employee skills to queue requirements."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal

MatchMode = Literal["all_of", "any_of"]


@dataclass(frozen=True, slots=True)
class QueueSkillRequirement:
    skill_id: int
    skill_code: str
    skill_category: str
    minimum_proficiency_level: int
    requirement_type: str = "required"
    requirement_group_code: str = "default"
    requirement_match_mode: MatchMode = "all_of"
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class EmployeeSkill:
    skill_id: int
    proficiency_level: int
    is_verified: bool
    skill_status: str = "active"
    valid_until_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class SkillMatchResult:
    eligible: bool
    satisfied_groups: tuple[str, ...]
    unsatisfied_groups: tuple[str, ...]
    missing_skill_codes: tuple[str, ...]
    matched_skill_codes: tuple[str, ...]
    explanation: str


def evaluate_queue_eligibility(
    requirements: Iterable[QueueSkillRequirement],
    employee_skills: Iterable[EmployeeSkill],
    *,
    at_utc: datetime | None = None,
) -> SkillMatchResult:
    """Evaluate ALL-OF and ANY-OF requirement groups.

    Rules:
    - All active `required` groups must be satisfied.
    - Within an `all_of` group every skill must be valid.
    - Within an `any_of` group at least one skill must be valid.
    - Employee skills must be active, verified, at/above minimum proficiency,
      and not expired at the supplied UTC instant.
    - Preferred requirements never block eligibility.
    - Missing requirements or inconsistent group modes fail closed.
    """
    instant = at_utc or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("at_utc must be timezone-aware")
    instant = instant.astimezone(timezone.utc)

    required = [
        item for item in requirements
        if item.is_active and item.requirement_type == "required"
    ]
    if not required:
        return SkillMatchResult(
            eligible=False,
            satisfied_groups=(),
            unsatisfied_groups=("__no_required_groups__",),
            missing_skill_codes=(),
            matched_skill_codes=(),
            explanation="No active required skills are configured; eligibility fails closed.",
        )

    groups: dict[str, list[QueueSkillRequirement]] = {}
    for requirement in required:
        if requirement.minimum_proficiency_level < 1 or requirement.minimum_proficiency_level > 5:
            raise ValueError(f"Invalid proficiency level for {requirement.skill_code}")
        if requirement.requirement_match_mode not in ("all_of", "any_of"):
            raise ValueError(f"Invalid match mode for group {requirement.requirement_group_code}")
        groups.setdefault(requirement.requirement_group_code, []).append(requirement)

    skill_by_id = {skill.skill_id: skill for skill in employee_skills}
    satisfied_groups: list[str] = []
    unsatisfied_groups: list[str] = []
    missing_codes: list[str] = []
    matched_codes: list[str] = []

    for group_code, group_items in sorted(groups.items()):
        modes = {item.requirement_match_mode for item in group_items}
        if len(modes) != 1:
            raise ValueError(f"Inconsistent match modes in group {group_code}")
        mode = next(iter(modes))
        valid_items: list[QueueSkillRequirement] = []
        invalid_items: list[QueueSkillRequirement] = []

        for requirement in group_items:
            employee_skill = skill_by_id.get(requirement.skill_id)
            is_valid = bool(
                employee_skill
                and employee_skill.skill_status == "active"
                and employee_skill.is_verified
                and employee_skill.proficiency_level >= requirement.minimum_proficiency_level
                and (
                    employee_skill.valid_until_utc is None
                    or employee_skill.valid_until_utc.astimezone(timezone.utc) > instant
                )
            )
            (valid_items if is_valid else invalid_items).append(requirement)

        group_satisfied = bool(valid_items) if mode == "any_of" else not invalid_items
        if group_satisfied:
            satisfied_groups.append(group_code)
            matched_codes.extend(item.skill_code for item in valid_items)
        else:
            unsatisfied_groups.append(group_code)
            if mode == "any_of":
                missing_codes.extend(item.skill_code for item in group_items)
            else:
                missing_codes.extend(item.skill_code for item in invalid_items)

    eligible = not unsatisfied_groups
    explanation = (
        "All required skill groups are satisfied."
        if eligible else "One or more required skill groups are not satisfied."
    )
    return SkillMatchResult(
        eligible=eligible,
        satisfied_groups=tuple(satisfied_groups),
        unsatisfied_groups=tuple(unsatisfied_groups),
        missing_skill_codes=tuple(sorted(set(missing_codes))),
        matched_skill_codes=tuple(sorted(set(matched_codes))),
        explanation=explanation,
    )
