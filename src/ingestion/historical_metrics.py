"""Tenant-scoped CSV ingestion for aggregated historical contact-centre intervals.

Only aggregated interval metrics are accepted. Customer, passenger, booking-reference,
agent-name, email, phone, token and credential fields are deliberately not part of the
allow-list. All database writes are tenant-bound and require data_source.manage.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from sqlalchemy import Engine, bindparam, text

if TYPE_CHECKING:
    from src.harness.auth_models import AuthenticatedTenantContext

REQUIRED_COLUMNS = ("interval_start_utc", "interval_seconds", "channel_code")
OPTIONAL_COLUMNS = (
    "market_code",
    "service_code",
    "queue_id",
    "service_language_code",
    "offered_contacts",
    "answered_contacts",
    "handled_contacts",
    "abandoned_contacts",
    "sla_eligible_contacts",
    "answered_within_threshold_contacts",
    "total_handle_seconds",
    "total_answer_wait_seconds",
    "source_reported_aht_seconds",
    "source_reported_asa_seconds",
    "source_reported_sla_percent",
)
ALLOWED_COLUMNS = frozenset((*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS))
_INTEGER_COLUMNS = frozenset(
    {
        "interval_seconds",
        "queue_id",
        "offered_contacts",
        "answered_contacts",
        "handled_contacts",
        "abandoned_contacts",
        "sla_eligible_contacts",
        "answered_within_threshold_contacts",
        "total_handle_seconds",
        "total_answer_wait_seconds",
    }
)
_DECIMAL_COLUMNS = frozenset(
    {
        "source_reported_aht_seconds",
        "source_reported_asa_seconds",
        "source_reported_sla_percent",
    }
)
_MAX_FILE_BYTES = 25 * 1024 * 1024
_MAX_ROWS = 100_000
_MAX_UINT64 = (1 << 64) - 1
_INTEGER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)$")
_SAFE_SOURCE_CODE = "contact_center_historical_csv"
_SAFE_SOURCE_NAME = "Contact Center Historical Interval CSV"


class HistoricalIngestionError(ValueError):
    """Raised when an uploaded historical interval file cannot be ingested safely."""


@dataclass(frozen=True, slots=True)
class HistoricalMetricsPreview:
    filename: str
    content_sha256: str
    records_received: int
    rows: tuple[Mapping[str, Any], ...]
    errors: tuple[str, ...]

    @property
    def can_import(self) -> bool:
        return self.records_received > 0 and not self.errors and len(self.rows) == self.records_received


@dataclass(frozen=True, slots=True)
class HistoricalMetricsImportResult:
    status: str
    ingestion_batch_id: int | None
    source_system_id: int | None
    records_received: int
    records_accepted: int
    records_rejected: int
    message: str


def _parse_utc_datetime(value: str, row_number: int) -> datetime:
    raw = value.strip()
    if not raw:
        raise HistoricalIngestionError(f"Row {row_number}: interval_start_utc is required.")
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HistoricalIngestionError(
            f"Row {row_number}: interval_start_utc must be ISO-8601 with a timezone, for example 2026-10-30T06:00:00Z."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoricalIngestionError(
            f"Row {row_number}: interval_start_utc must include a timezone offset; use Z for UTC."
        )
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_integer(name: str, value: str | None, row_number: int) -> int | None:
    raw = (value or "").strip()
    if raw == "":
        return None
    if not _INTEGER_PATTERN.fullmatch(raw):
        raise HistoricalIngestionError(
            f"Row {row_number}: {name} must be a whole non-negative integer."
        )
    parsed = int(raw)
    maximum = 2**32 - 1 if name == "interval_seconds" else _MAX_UINT64
    if parsed > maximum:
        raise HistoricalIngestionError(f"Row {row_number}: {name} exceeds the MySQL column range.")
    if name == "interval_seconds" and parsed == 0:
        raise HistoricalIngestionError(f"Row {row_number}: interval_seconds must be greater than zero.")
    if name == "queue_id" and parsed == 0:
        raise HistoricalIngestionError(f"Row {row_number}: queue_id must be greater than zero when supplied.")
    return parsed


def _parse_decimal(name: str, value: str | None, row_number: int) -> Decimal | None:
    raw = (value or "").strip()
    if raw == "":
        return None
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise HistoricalIngestionError(f"Row {row_number}: {name} must be numeric.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise HistoricalIngestionError(f"Row {row_number}: {name} must be a finite non-negative number.")
    if name == "source_reported_sla_percent" and parsed > 100:
        raise HistoricalIngestionError(f"Row {row_number}: source_reported_sla_percent must be between 0 and 100.")
    max_value = Decimal("999999999.999") if name != "source_reported_sla_percent" else Decimal("100.00")
    if parsed > max_value:
        raise HistoricalIngestionError(f"Row {row_number}: {name} exceeds the MySQL column range.")
    return parsed


def _clean_optional_code(name: str, value: str | None, row_number: int) -> str | None:
    raw = (value or "").strip()
    if raw == "":
        return None
    max_lengths = {"market_code": 16, "service_code": 64, "service_language_code": 12}
    if len(raw) > max_lengths.get(name, 64):
        raise HistoricalIngestionError(f"Row {row_number}: {name} is too long.")
    if name == "market_code":
        raw = raw.upper()
    elif name == "service_language_code":
        raw = raw.lower()
    return raw


def parse_historical_metrics_csv(payload: bytes, filename: str) -> HistoricalMetricsPreview:
    """Parse and validate CSV structure and row-level values without touching MySQL."""
    safe_name = Path(filename or "historical_interval_metrics.csv").name[:255]
    digest = hashlib.sha256(payload).hexdigest()
    errors: list[str] = []
    rows: list[Mapping[str, Any]] = []
    data_row_count = 0

    if not isinstance(payload, (bytes, bytearray)):
        return HistoricalMetricsPreview(safe_name, digest, 0, (), ("Uploaded content must be bytes.",))
    if len(payload) == 0:
        return HistoricalMetricsPreview(safe_name, digest, 0, (), ("The uploaded CSV is empty.",))
    if len(payload) > _MAX_FILE_BYTES:
        return HistoricalMetricsPreview(safe_name, digest, 0, (), ("CSV exceeds the 25 MB upload limit.",))

    try:
        decoded = bytes(payload).decode("utf-8-sig")
    except UnicodeDecodeError:
        return HistoricalMetricsPreview(safe_name, digest, 0, (), ("CSV must use UTF-8 encoding.",))

    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        headers = reader.fieldnames or []
        if not headers:
            return HistoricalMetricsPreview(safe_name, digest, 0, (), ("CSV header row is missing.",))
        if len(headers) != len(set(headers)):
            return HistoricalMetricsPreview(safe_name, digest, 0, (), ("CSV contains duplicate column names.",))
        missing = sorted(set(REQUIRED_COLUMNS).difference(headers))
        unknown = sorted(set(headers).difference(ALLOWED_COLUMNS))
        if missing:
            errors.append("Missing required columns: " + ", ".join(missing))
        if unknown:
            errors.append("Unsupported columns: " + ", ".join(unknown))
        if errors:
            return HistoricalMetricsPreview(safe_name, digest, 0, (), tuple(errors))

        for csv_row_number, raw_row in enumerate(reader, start=2):
            if raw_row is None or all((value or "").strip() == "" for key, value in raw_row.items() if key is not None):
                continue
            data_row_count += 1
            if data_row_count > _MAX_ROWS:
                errors.append(f"CSV exceeds the {_MAX_ROWS:,} row limit.")
                break
            try:
                if None in raw_row and raw_row[None]:
                    raise HistoricalIngestionError(f"Row {csv_row_number}: row contains more values than the header.")
                parsed: dict[str, Any] = {
                    "__source_row_number": csv_row_number,
                    "interval_start_utc": _parse_utc_datetime(raw_row.get("interval_start_utc", ""), csv_row_number),
                    "interval_seconds": _parse_integer("interval_seconds", raw_row.get("interval_seconds"), csv_row_number),
                    "channel_code": (raw_row.get("channel_code") or "").strip().lower(),
                }
                if not parsed["channel_code"]:
                    raise HistoricalIngestionError(f"Row {csv_row_number}: channel_code is required.")
                if len(parsed["channel_code"]) > 32:
                    raise HistoricalIngestionError(f"Row {csv_row_number}: channel_code exceeds 32 characters.")

                for name in OPTIONAL_COLUMNS:
                    if name in _INTEGER_COLUMNS:
                        parsed[name] = _parse_integer(name, raw_row.get(name), csv_row_number)
                    elif name in _DECIMAL_COLUMNS:
                        parsed[name] = _parse_decimal(name, raw_row.get(name), csv_row_number)
                    elif name in {"market_code", "service_code", "service_language_code"}:
                        parsed[name] = _clean_optional_code(name, raw_row.get(name), csv_row_number)

                eligible = parsed.get("sla_eligible_contacts")
                within = parsed.get("answered_within_threshold_contacts")
                if eligible is not None and within is not None and within > eligible:
                    raise HistoricalIngestionError(
                        f"Row {csv_row_number}: answered_within_threshold_contacts cannot exceed sla_eligible_contacts."
                    )
                answered = parsed.get("answered_contacts")
                if answered is not None and within is not None and within > answered:
                    raise HistoricalIngestionError(
                        f"Row {csv_row_number}: answered_within_threshold_contacts cannot exceed answered_contacts."
                    )
                rows.append(parsed)
            except HistoricalIngestionError as exc:
                errors.append(str(exc))
            except Exception as exc:  # defensive parser boundary; never expose raw row data
                errors.append(f"Row {csv_row_number}: invalid row ({type(exc).__name__}).")

    except csv.Error:
        errors.append("CSV structure is invalid or malformed.")

    records_received = data_row_count
    return HistoricalMetricsPreview(
        filename=safe_name,
        content_sha256=digest,
        records_received=records_received,
        rows=tuple(rows),
        errors=tuple(errors),
    )


class HistoricalMetricsIngestionService:
    """Preview and import aggregated intervals using a verified tenant context."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _tenant_id(context: AuthenticatedTenantContext) -> int:
        return context.require_permission("data_source.manage")

    def _validate_references(self, connection: Any, tenant_id: int, rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
        errors: list[str] = []

        def existing_values(sql: str, parameter_name: str, values: set[str]) -> set[str]:
            if not values:
                return set()
            stmt = text(sql).bindparams(bindparam(parameter_name, expanding=True))
            result = connection.execute(stmt, {parameter_name: sorted(values)}).mappings().all()
            return {str(next(iter(row.values()))) for row in result}

        markets = {str(row["market_code"]) for row in rows if row.get("market_code")}
        if markets:
            found = existing_values(
                "SELECT market_code FROM markets WHERE market_code IN :codes", "codes", markets
            )
            errors.extend(f"Unknown market_code: {code}" for code in sorted(markets - found))

        channels = {str(row["channel_code"]) for row in rows if row.get("channel_code")}
        found_channels = existing_values(
            "SELECT channel_code FROM channels WHERE channel_code IN :codes", "codes", channels
        )
        errors.extend(f"Unknown channel_code: {code}" for code in sorted(channels - found_channels))

        languages = {str(row["service_language_code"]) for row in rows if row.get("service_language_code")}
        if languages:
            found = existing_values(
                "SELECT language_code FROM languages WHERE language_code IN :codes", "codes", languages
            )
            errors.extend(f"Unknown service_language_code: {code}" for code in sorted(languages - found))

        services = {str(row["service_code"]) for row in rows if row.get("service_code")}
        if services:
            stmt = text(
                "SELECT service_code FROM services WHERE tenant_id = :tenant_id AND service_code IN :codes"
            ).bindparams(bindparam("codes", expanding=True))
            result = connection.execute(stmt, {"tenant_id": tenant_id, "codes": sorted(services)}).mappings().all()
            found = {str(row["service_code"]) for row in result}
            errors.extend(f"Unknown service_code for this company: {code}" for code in sorted(services - found))

        queue_ids = {int(row["queue_id"]) for row in rows if row.get("queue_id") is not None}
        queue_lookup: dict[int, tuple[str, str]] = {}
        if queue_ids:
            stmt = text(
                """SELECT queue_id, service_code, channel_code
                   FROM queues WHERE tenant_id = :tenant_id AND queue_id IN :queue_ids"""
            ).bindparams(bindparam("queue_ids", expanding=True))
            result = connection.execute(stmt, {"tenant_id": tenant_id, "queue_ids": sorted(queue_ids)}).mappings().all()
            queue_lookup = {
                int(row["queue_id"]): (str(row["service_code"]), str(row["channel_code"]))
                for row in result
            }
            for queue_id in sorted(queue_ids - set(queue_lookup)):
                errors.append(f"Unknown queue_id for this company: {queue_id}")
            for row in rows:
                queue_id = row.get("queue_id")
                if queue_id is None or int(queue_id) not in queue_lookup:
                    continue
                queue_service, queue_channel = queue_lookup[int(queue_id)]
                if row.get("channel_code") and str(row["channel_code"]) != queue_channel:
                    errors.append(
                        f"Queue/channel mismatch for queue_id {queue_id}: expected {queue_channel}."
                    )
                if row.get("service_code") and str(row["service_code"]) != queue_service:
                    errors.append(
                        f"Queue/service mismatch for queue_id {queue_id}: expected {queue_service}."
                    )
        return tuple(dict.fromkeys(errors))

    def preview_file(
        self,
        context: AuthenticatedTenantContext,
        *,
        payload: bytes,
        filename: str,
    ) -> HistoricalMetricsPreview:
        tenant_id = self._tenant_id(context)
        preview = parse_historical_metrics_csv(payload, filename)
        if preview.errors or not preview.rows:
            return preview
        with self._engine.connect() as connection:
            reference_errors = self._validate_references(connection, tenant_id, preview.rows)
        if reference_errors:
            return HistoricalMetricsPreview(
                filename=preview.filename,
                content_sha256=preview.content_sha256,
                records_received=preview.records_received,
                rows=preview.rows,
                errors=reference_errors,
            )
        return preview

    def _get_or_create_source(self, connection: Any, tenant_id: int) -> int:
        row = connection.execute(
            text(
                """SELECT source_system_id FROM source_systems
                   WHERE tenant_id = :tenant_id AND source_code = :source_code
                   FOR UPDATE"""
            ),
            {"tenant_id": tenant_id, "source_code": _SAFE_SOURCE_CODE},
        ).mappings().one_or_none()
        if row is not None:
            if int(row["source_system_id"]) <= 0:
                raise HistoricalIngestionError("Registered CSV source identifier is invalid.")
            status = connection.execute(
                text("SELECT source_status FROM source_systems WHERE tenant_id=:tenant_id AND source_system_id=:source_id"),
                {"tenant_id": tenant_id, "source_id": int(row["source_system_id"])},
            ).mappings().one()
            if status["source_status"] != "active":
                raise HistoricalIngestionError("Historical CSV source is disabled for this company.")
            return int(row["source_system_id"])
        connection.execute(
            text(
                """INSERT INTO source_systems
                   (tenant_id, source_code, display_name, source_type, source_status)
                   VALUES (:tenant_id, :source_code, :display_name, 'csv', 'active')"""
            ),
            {
                "tenant_id": tenant_id,
                "source_code": _SAFE_SOURCE_CODE,
                "display_name": _SAFE_SOURCE_NAME,
            },
        )
        inserted = connection.execute(
            text(
                """SELECT source_system_id FROM source_systems
                   WHERE tenant_id = :tenant_id AND source_code = :source_code"""
            ),
            {"tenant_id": tenant_id, "source_code": _SAFE_SOURCE_CODE},
        ).mappings().one()
        return int(inserted["source_system_id"])

    def import_file(
        self,
        context: AuthenticatedTenantContext,
        *,
        payload: bytes,
        filename: str,
    ) -> HistoricalMetricsImportResult:
        tenant_id = self._tenant_id(context)
        preview = parse_historical_metrics_csv(payload, filename)

        with self._engine.begin() as connection:
            source_system_id = self._get_or_create_source(connection, tenant_id)
            existing = connection.execute(
                text(
                    """SELECT ingestion_batch_id, batch_status
                       FROM ingestion_batches
                       WHERE tenant_id = :tenant_id
                         AND source_system_id = :source_system_id
                         AND source_content_sha256 = :content_hash
                       LIMIT 1"""
                ),
                {
                    "tenant_id": tenant_id,
                    "source_system_id": source_system_id,
                    "content_hash": preview.content_sha256,
                },
            ).mappings().one_or_none()
            if existing is not None:
                return HistoricalMetricsImportResult(
                    status="duplicate",
                    ingestion_batch_id=int(existing["ingestion_batch_id"]),
                    source_system_id=source_system_id,
                    records_received=preview.records_received,
                    records_accepted=0,
                    records_rejected=0,
                    message=f"This exact file was already processed as batch {existing['ingestion_batch_id']} ({existing['batch_status']}). No duplicate rows were inserted.",
                )

            all_errors = list(preview.errors)
            if not all_errors and preview.rows:
                all_errors.extend(self._validate_references(connection, tenant_id, preview.rows))
            if not preview.rows and not all_errors:
                all_errors.append("No data rows were found in the CSV.")

            if all_errors:
                rejected_count = max(preview.records_received, len(all_errors))
                rejected_count = min(rejected_count, preview.records_received) if preview.records_received else 0
                result = connection.execute(
                    text(
                        """INSERT INTO ingestion_batches (
                            tenant_id, source_system_id, batch_type, source_file_name,
                            source_content_sha256, batch_status, records_received,
                            records_accepted, records_rejected, validation_summary_json,
                            completed_at_utc
                        ) VALUES (
                            :tenant_id, :source_system_id, 'historical_interval_metrics',
                            :filename, :content_hash, 'rejected', :records_received,
                            0, :records_rejected, :summary, CURRENT_TIMESTAMP(6)
                        )"""
                    ),
                    {
                        "tenant_id": tenant_id,
                        "source_system_id": source_system_id,
                        "filename": preview.filename,
                        "content_hash": preview.content_sha256,
                        "records_received": preview.records_received,
                        "records_rejected": rejected_count,
                        "summary": json.dumps({"errors": all_errors[:100]}, ensure_ascii=False),
                    },
                )
                batch_id = int(result.lastrowid)
                return HistoricalMetricsImportResult(
                    status="rejected",
                    ingestion_batch_id=batch_id,
                    source_system_id=source_system_id,
                    records_received=preview.records_received,
                    records_accepted=0,
                    records_rejected=rejected_count,
                    message="The file was rejected. No historical metric rows were imported.",
                )

            batch_result = connection.execute(
                text(
                    """INSERT INTO ingestion_batches (
                        tenant_id, source_system_id, batch_type, source_file_name,
                        source_content_sha256, batch_status, records_received,
                        records_accepted, records_rejected, validation_summary_json
                    ) VALUES (
                        :tenant_id, :source_system_id, 'historical_interval_metrics',
                        :filename, :content_hash, 'received', :records_received,
                        0, 0, :summary
                    )"""
                ),
                {
                    "tenant_id": tenant_id,
                    "source_system_id": source_system_id,
                    "filename": preview.filename,
                    "content_hash": preview.content_sha256,
                    "records_received": preview.records_received,
                    "summary": json.dumps({"validation": "passed", "timezone": "UTC"}),
                },
            )
            batch_id = int(batch_result.lastrowid)

            insert_statement = text(
                """INSERT INTO historical_interval_metrics (
                    tenant_id, source_system_id, ingestion_batch_id, source_row_number,
                    interval_start_utc, interval_seconds, market_code, channel_code,
                    service_code, queue_id, service_language_code,
                    offered_contacts, answered_contacts, handled_contacts,
                    abandoned_contacts, sla_eligible_contacts,
                    answered_within_threshold_contacts, total_handle_seconds,
                    total_answer_wait_seconds, source_reported_aht_seconds,
                    source_reported_asa_seconds, source_reported_sla_percent,
                    quality_status, quality_notes_json
                ) VALUES (
                    :tenant_id, :source_system_id, :batch_id, :source_row_number,
                    :interval_start_utc, :interval_seconds, :market_code, :channel_code,
                    :service_code, :queue_id, :service_language_code,
                    :offered_contacts, :answered_contacts, :handled_contacts,
                    :abandoned_contacts, :sla_eligible_contacts,
                    :answered_within_threshold_contacts, :total_handle_seconds,
                    :total_answer_wait_seconds, :source_reported_aht_seconds,
                    :source_reported_asa_seconds, :source_reported_sla_percent,
                    'unreviewed', :quality_notes_json
                )"""
            )
            for row in preview.rows:
                parameters = {key: value for key, value in row.items() if key != "__source_row_number"}
                parameters.update(
                    {
                        "tenant_id": tenant_id,
                        "source_system_id": source_system_id,
                        "batch_id": batch_id,
                        "source_row_number": int(row["__source_row_number"]),
                        "quality_notes_json": json.dumps(
                            {"ingestion_validation": "passed", "source_file": preview.filename},
                            ensure_ascii=False,
                        ),
                    }
                )
                connection.execute(insert_statement, parameters)

            connection.execute(
                text(
                    """UPDATE ingestion_batches
                       SET batch_status = 'loaded',
                           records_accepted = :accepted,
                           records_rejected = 0,
                           completed_at_utc = CURRENT_TIMESTAMP(6),
                           validation_summary_json = :summary
                       WHERE tenant_id = :tenant_id AND ingestion_batch_id = :batch_id"""
                ),
                {
                    "accepted": len(preview.rows),
                    "summary": json.dumps(
                        {"validation": "passed", "quality_status": "unreviewed", "timezone": "UTC"},
                        ensure_ascii=False,
                    ),
                    "tenant_id": tenant_id,
                    "batch_id": batch_id,
                },
            )
            connection.execute(
                text(
                    """INSERT INTO audit_events (
                        tenant_id, actor_membership_id, action_code, target_type,
                        target_reference, outcome_code, event_details_json
                    ) VALUES (
                        :tenant_id, :membership_id, 'historical_metrics.batch_loaded',
                        'ingestion_batch', :batch_id, 'success', :details
                    )"""
                ),
                {
                    "tenant_id": tenant_id,
                    "membership_id": context.membership_id,
                    "batch_id": str(batch_id),
                    "details": json.dumps(
                        {
                            "records_received": len(preview.rows),
                            "records_accepted": len(preview.rows),
                            "source_code": _SAFE_SOURCE_CODE,
                            "content_sha256_prefix": preview.content_sha256[:12],
                        },
                        ensure_ascii=False,
                    ),
                },
            )

        return HistoricalMetricsImportResult(
            status="loaded",
            ingestion_batch_id=batch_id,
            source_system_id=source_system_id,
            records_received=len(preview.rows),
            records_accepted=len(preview.rows),
            records_rejected=0,
            message=f"Successfully imported {len(preview.rows)} aggregated interval rows.",
        )
