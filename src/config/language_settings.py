from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LanguageCode = Literal["en", "ar", "fr"]


@dataclass(frozen=True)
class LanguageContext:
    """Keep employee, service, and source-document languages independent."""

    employee_language: LanguageCode
    service_language: LanguageCode | None = None
    policy_document_language: LanguageCode | None = None


def validate_language_code(value: str, *, allow_none: bool = False) -> LanguageCode | None:
    normalized = value.strip().lower()
    supported: set[str] = {"en", "ar", "fr"}
    if allow_none and not normalized:
        return None
    if normalized not in supported:
        raise ValueError(f"Unsupported language code: {value!r}. Use en, ar, or fr.")
    return normalized  # type: ignore[return-value]
