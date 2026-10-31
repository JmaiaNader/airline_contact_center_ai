from datetime import datetime, timedelta, timezone

import pytest

from src.wfm.skill_matcher import (
    EmployeeSkill,
    QueueSkillRequirement,
    evaluate_queue_eligibility,
)

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)


def req(skill_id, code, category, group, mode="all_of", minimum=3):
    return QueueSkillRequirement(
        skill_id=skill_id,
        skill_code=code,
        skill_category=category,
        minimum_proficiency_level=minimum,
        requirement_group_code=group,
        requirement_match_mode=mode,
    )


def emp(skill_id, level=3, verified=True, status="active", expiry=None):
    return EmployeeSkill(skill_id, level, verified, status, expiry)


def test_voice_arabic_or_english_accepts_arabic_only():
    requirements = [
        req(10, "channel_voice", "channel", "channel"),
        req(20, "service_booking", "service", "service"),
        req(1, "language_ar", "language", "language", "any_of"),
        req(2, "language_en", "language", "language", "any_of"),
    ]
    result = evaluate_queue_eligibility(requirements, [emp(10), emp(20), emp(1)], at_utc=NOW)
    assert result.eligible is True
    assert "language" in result.satisfied_groups


def test_voice_arabic_or_english_accepts_english_only():
    requirements = [
        req(10, "channel_voice", "channel", "channel"),
        req(20, "service_booking", "service", "service"),
        req(1, "language_ar", "language", "language", "any_of"),
        req(2, "language_en", "language", "language", "any_of"),
    ]
    result = evaluate_queue_eligibility(requirements, [emp(10), emp(20), emp(2)], at_utc=NOW)
    assert result.eligible is True


def test_voice_requires_channel_and_service_and_one_language():
    requirements = [
        req(10, "channel_voice", "channel", "channel"),
        req(20, "service_booking", "service", "service"),
        req(1, "language_ar", "language", "language", "any_of"),
        req(2, "language_en", "language", "language", "any_of"),
    ]
    result = evaluate_queue_eligibility(requirements, [emp(10), emp(1)], at_utc=NOW)
    assert result.eligible is False
    assert "service" in result.unsatisfied_groups


def test_whatsapp_requires_english_only():
    requirements = [
        req(12, "channel_whatsapp", "channel", "channel"),
        req(20, "service_booking", "service", "service"),
        req(2, "language_en", "language", "language", "any_of"),
    ]
    result = evaluate_queue_eligibility(requirements, [emp(12), emp(20), emp(1)], at_utc=NOW)
    assert result.eligible is False
    assert "language_en" in result.missing_skill_codes


def test_unverified_skill_does_not_qualify():
    requirements = [req(1, "language_en", "language", "language", "any_of")]
    result = evaluate_queue_eligibility(requirements, [emp(1, verified=False)], at_utc=NOW)
    assert result.eligible is False


def test_expired_skill_does_not_qualify():
    requirements = [req(1, "language_en", "language", "language", "any_of")]
    result = evaluate_queue_eligibility(
        requirements, [emp(1, expiry=NOW - timedelta(seconds=1))], at_utc=NOW
    )
    assert result.eligible is False


def test_minimum_proficiency_is_enforced():
    requirements = [req(1, "language_en", "language", "language", "any_of", minimum=3)]
    result = evaluate_queue_eligibility(requirements, [emp(1, level=2)], at_utc=NOW)
    assert result.eligible is False


def test_preferred_requirement_does_not_block_eligibility():
    required = req(1, "language_en", "language", "language", "any_of")
    preferred = QueueSkillRequirement(
        skill_id=2, skill_code="language_ar", skill_category="language",
        minimum_proficiency_level=3, requirement_type="preferred",
        requirement_group_code="language", requirement_match_mode="any_of",
    )
    result = evaluate_queue_eligibility([required, preferred], [emp(1)], at_utc=NOW)
    assert result.eligible is True


def test_no_required_requirements_fails_closed():
    result = evaluate_queue_eligibility([], [emp(1)], at_utc=NOW)
    assert result.eligible is False


def test_mixed_modes_in_same_group_are_rejected():
    requirements = [
        req(1, "language_ar", "language", "language", "any_of"),
        req(2, "language_en", "language", "language", "all_of"),
    ]
    with pytest.raises(ValueError, match="Inconsistent match modes"):
        evaluate_queue_eligibility(requirements, [], at_utc=NOW)


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_queue_eligibility([req(1, "language_en", "language", "language", "any_of")], [], at_utc=datetime(2026, 10, 31))
