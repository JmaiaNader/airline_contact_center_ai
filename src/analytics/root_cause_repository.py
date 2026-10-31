"""Tenant- and source-scoped read-only interval loader for root-cause analysis.

The tenant ID must come from a verified AuthenticatedTenantContext. Source selection
is validated separately by the KPI service before this repository is called.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text


LOAD_INTERVAL_ROWS_SQL = text(
    """
    SELECT
        m.historical_interval_metric_id,
        m.tenant_id,
        m.source_system_id,
        m.ingestion_batch_id,
        m.interval_start_utc,
        m.interval_seconds,
        m.market_code,
        m.channel_code,
        m.service_code,
        m.queue_id,
        m.service_language_code,
        m.offered_contacts,
        m.answered_contacts,
        m.handled_contacts,
        m.abandoned_contacts,
        m.sla_eligible_contacts,
        m.answered_within_threshold_contacts,
        m.total_handle_seconds,
        m.total_answer_wait_seconds,
        m.quality_status,
        m.quality_notes_json,
        b.validation_summary_json
    FROM historical_interval_metrics AS m
    INNER JOIN ingestion_batches AS b
      ON b.tenant_id = m.tenant_id
     AND b.source_system_id = m.source_system_id
     AND b.ingestion_batch_id = m.ingestion_batch_id
     AND b.batch_type = 'historical_interval_metrics'
     AND b.batch_status = 'loaded'
    WHERE m.tenant_id = :tenant_id
      AND m.source_system_id = :source_system_id
      AND m.interval_start_utc >= :start_utc
      AND m.interval_start_utc < :end_utc
    ORDER BY m.interval_start_utc ASC, m.historical_interval_metric_id ASC
    """
)


def load_interval_rows(
    connection: Any,
    *,
    authenticated_tenant_id: int,
    source_system_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> list[dict[str, Any]]:
    """Load loaded-batch aggregate rows for one verified tenant, source and UTC window."""
    if (
        isinstance(authenticated_tenant_id, bool)
        or not isinstance(authenticated_tenant_id, int)
        or authenticated_tenant_id <= 0
    ):
        raise ValueError("authenticated_tenant_id must be a positive integer.")
    if isinstance(source_system_id, bool) or not isinstance(source_system_id, int) or source_system_id <= 0:
        raise ValueError("source_system_id must be a positive integer.")
    if not isinstance(start_utc, datetime) or not isinstance(end_utc, datetime):
        raise TypeError("start_utc and end_utc must be datetime values.")
    if start_utc.tzinfo is None or start_utc.utcoffset() is None:
        raise ValueError("start_utc must be a timezone-aware datetime.")
    if end_utc.tzinfo is None or end_utc.utcoffset() is None:
        raise ValueError("end_utc must be a timezone-aware datetime.")
    if start_utc >= end_utc:
        raise ValueError("start_utc must be earlier than end_utc.")

    result = connection.execute(
        LOAD_INTERVAL_ROWS_SQL,
        {
            "tenant_id": authenticated_tenant_id,
            "source_system_id": source_system_id,
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
    )
    return [dict(row) for row in result.mappings().all()]
