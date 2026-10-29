from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

_MISSING = {"", "null", "none", "n/a", "nan"}
_BOOLEAN = {"true", "false", "yes", "no", "y", "n"}
_DEFAULT_SAMPLE_VALUES = 5
_MAX_ROWS_LIMIT = 1_000_000


@dataclass(frozen=True, slots=True)
class FieldProfile:
    name: str
    inferred_type: str
    row_count: int
    non_empty_count: int
    null_count: int
    distinct_count: int
    sample_values: tuple[str, ...]
    numeric_min: float | None = None
    numeric_max: float | None = None


@dataclass(frozen=True, slots=True)
class CsvProfile:
    source_name: str
    rows_profiled: int
    fields: tuple[FieldProfile, ...]
    quality_issues: tuple[str, ...]
    truncated: bool


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip().lower() in _MISSING


def _infer_type(field_name: str, values: list[str]) -> tuple[str, float | None, float | None]:
    if not values:
        return "empty", None, None

    normalized = [value.strip() for value in values]
    lowers = {value.lower() for value in normalized}
    if lowers and lowers <= _BOOLEAN:
        return "boolean", None, None

    name = field_name.lower()
    looks_temporal = any(part in name for part in ("date", "time", "timestamp", "_at"))
    if looks_temporal:
        parsed_temporal = 0
        for value in normalized:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                parsed_temporal += 1
                continue
            except ValueError:
                pass
            try:
                date.fromisoformat(value)
                parsed_temporal += 1
            except ValueError:
                pass
        if parsed_temporal == len(normalized):
            return "datetime", None, None

    integers: list[int] = []
    all_integer = True
    for value in normalized:
        try:
            integers.append(int(value))
        except ValueError:
            all_integer = False
            break
    if all_integer:
        return "integer", float(min(integers)), float(max(integers))

    numbers: list[float] = []
    all_number = True
    for value in normalized:
        try:
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                all_number = False
                break
            numbers.append(number)
        except ValueError:
            all_number = False
            break
    if all_number:
        return "number", min(numbers), max(numbers)

    numeric_count = 0
    for value in normalized:
        try:
            float(value)
            numeric_count += 1
        except ValueError:
            continue
    if 0 < numeric_count < len(normalized):
        return "mixed", None, None
    return "text", None, None


def profile_csv(path: str | Path, *, max_rows: int = 100_000, sample_values: int = _DEFAULT_SAMPLE_VALUES) -> CsvProfile:
    """Profile a CSV schema and bounded row sample without modifying its contents.

    This is intentionally a local, read-only connector for the first milestone. It does
    not open databases, upload data, or infer permission to use the content.
    """
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"CSV source does not exist or is not a file: {source}")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= _MAX_ROWS_LIMIT:
        raise ValueError(f"max_rows must be an integer between 1 and {_MAX_ROWS_LIMIT}.")
    if isinstance(sample_values, bool) or not isinstance(sample_values, int) or not 0 <= sample_values <= 20:
        raise ValueError("sample_values must be an integer between 0 and 20.")

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        if not headers:
            raise ValueError("CSV is empty or has no header row.")
        cleaned = [header.strip() if header is not None else "" for header in headers]
        if any(not header for header in cleaned):
            raise ValueError("CSV contains a blank column name; fix the header before profiling.")
        if len({header.casefold() for header in cleaned}) != len(cleaned):
            raise ValueError("CSV contains duplicate column names (case-insensitive).")
        reader.fieldnames = cleaned

        rows_by_field: dict[str, list[str]] = {header: [] for header in cleaned}
        null_counts: dict[str, int] = {header: 0 for header in cleaned}
        samples: dict[str, list[str]] = {header: [] for header in cleaned}
        row_count = 0
        issues: list[str] = []
        truncated = False

        for row in reader:
            if row_count >= max_rows:
                truncated = True
                break
            row_count += 1
            if None in row:
                issues.append(f"Row {row_count + 1} has extra values beyond the header width.")
                row.pop(None, None)
            for header in cleaned:
                value = row.get(header)
                if _is_missing(value):
                    null_counts[header] += 1
                    continue
                text = str(value).strip()
                rows_by_field[header].append(text)
                if text not in samples[header] and len(samples[header]) < sample_values:
                    samples[header].append(text)
            if any(value is None for value in row.values()):
                issues.append(f"Row {row_count + 1} has one or more missing trailing values.")

    fields: list[FieldProfile] = []
    for header in cleaned:
        values = rows_by_field[header]
        inferred_type, numeric_min, numeric_max = _infer_type(header, values)
        fields.append(
            FieldProfile(
                name=header,
                inferred_type=inferred_type,
                row_count=row_count,
                non_empty_count=len(values),
                null_count=null_counts[header],
                distinct_count=len(set(values)),
                sample_values=tuple(samples[header]),
                numeric_min=numeric_min,
                numeric_max=numeric_max,
            )
        )

    if truncated:
        issues.append(f"Profiling stopped at the configured limit of {max_rows} rows; coverage is partial.")
    if row_count == 0:
        issues.append("CSV contains headers but no data rows.")

    return CsvProfile(
        source_name=source.name,
        rows_profiled=row_count,
        fields=tuple(fields),
        quality_issues=tuple(dict.fromkeys(issues)),
        truncated=truncated,
    )
