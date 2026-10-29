import pytest

from src.config.language_settings import validate_language_code


def test_language_code_is_normalized() -> None:
    assert validate_language_code(" FR ") == "fr"


def test_optional_language_can_be_empty() -> None:
    assert validate_language_code("", allow_none=True) is None


def test_unsupported_language_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_language_code("de")
