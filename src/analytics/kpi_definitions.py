"""Single executable source of truth for AeroInsight's initial contact-centre KPIs.

Change formulas and governed field bindings here only. UI pages, reports and future
agents must consume these definitions rather than reimplementing KPI arithmetic.
All calculations are weighted from summed numerators and denominators; interval-level
percentages and source-reported averages are deliberately not averaged.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

KPI_DEFINITION_VERSION = "1.0.0"
CALCULATION_TIMEZONE = "UTC"

FormulaKind = Literal["sum", "ratio", "ratio_percent"]


@dataclass(frozen=True, slots=True)
class KPIDefinition:
    key: str
    label: str
    formula_kind: FormulaKind
    formula: str
    unit: str
    source_fields: tuple[str, ...]
    numerator_field: str | None = None
    denominator_field: str | None = None
    description: str = ""
    precision: int = 2


_DEFINITIONS = {
    "offered_contacts": KPIDefinition(
        key="offered_contacts",
        label="Offered Contacts",
        formula_kind="sum",
        formula="SUM(offered_contacts)",
        unit="contacts",
        source_fields=("offered_contacts",),
        description="Total contacts offered to the selected service/channel population.",
        precision=0,
    ),
    "answered_contacts": KPIDefinition(
        key="answered_contacts",
        label="Answered Contacts",
        formula_kind="sum",
        formula="SUM(answered_contacts)",
        unit="contacts",
        source_fields=("answered_contacts",),
        description="Total contacts answered, using the canonical interval measure.",
        precision=0,
    ),
    "handled_contacts": KPIDefinition(
        key="handled_contacts",
        label="Handled Contacts",
        formula_kind="sum",
        formula="SUM(handled_contacts)",
        unit="contacts",
        source_fields=("handled_contacts",),
        description="Total contacts handled, using the canonical interval measure.",
        precision=0,
    ),
    "abandoned_contacts": KPIDefinition(
        key="abandoned_contacts",
        label="Abandoned Contacts",
        formula_kind="sum",
        formula="SUM(abandoned_contacts)",
        unit="contacts",
        source_fields=("abandoned_contacts",),
        description="Total contacts abandoned before being handled.",
        precision=0,
    ),
    "service_level_percent": KPIDefinition(
        key="service_level_percent",
        label="Service Level",
        formula_kind="ratio_percent",
        formula="100 × SUM(answered_within_threshold_contacts) / SUM(sla_eligible_contacts)",
        unit="%",
        source_fields=("answered_within_threshold_contacts", "sla_eligible_contacts"),
        numerator_field="answered_within_threshold_contacts",
        denominator_field="sla_eligible_contacts",
        description=(
            "Answered within the configured threshold divided by eligible contacts. "
            "The denominator is the stored sla_eligible_contacts field; the KPI formula "
            "is not inferred from source_reported_sla_percent."
        ),
    ),
    "aht_seconds": KPIDefinition(
        key="aht_seconds",
        label="Average Handle Time",
        formula_kind="ratio",
        formula="SUM(total_handle_seconds) / SUM(handled_contacts)",
        unit="seconds",
        source_fields=("total_handle_seconds", "handled_contacts"),
        numerator_field="total_handle_seconds",
        denominator_field="handled_contacts",
        description="Weighted average handle time per handled contact, in seconds.",
    ),
    "asa_seconds": KPIDefinition(
        key="asa_seconds",
        label="Average Speed of Answer",
        formula_kind="ratio",
        formula="SUM(total_answer_wait_seconds) / SUM(answered_contacts)",
        unit="seconds",
        source_fields=("total_answer_wait_seconds", "answered_contacts"),
        numerator_field="total_answer_wait_seconds",
        denominator_field="answered_contacts",
        description="Weighted average answer wait per answered contact, in seconds.",
    ),
    "abandonment_rate_percent": KPIDefinition(
        key="abandonment_rate_percent",
        label="Abandonment Rate",
        formula_kind="ratio_percent",
        formula="100 × SUM(abandoned_contacts) / SUM(offered_contacts)",
        unit="%",
        source_fields=("abandoned_contacts", "offered_contacts"),
        numerator_field="abandoned_contacts",
        denominator_field="offered_contacts",
        description="Abandoned contacts divided by offered contacts.",
    ),
    "answer_rate_percent": KPIDefinition(
        key="answer_rate_percent",
        label="Answer Rate",
        formula_kind="ratio_percent",
        formula="100 × SUM(answered_contacts) / SUM(offered_contacts)",
        unit="%",
        source_fields=("answered_contacts", "offered_contacts"),
        numerator_field="answered_contacts",
        denominator_field="offered_contacts",
        description="Answered contacts divided by offered contacts.",
    ),
}

KPI_DEFINITIONS = MappingProxyType(_DEFINITIONS)

# Targets are intentionally separate from formulas. None means no target has been
# configured and the UI must not invent one. Configure tenant-specific targets in a
# governed settings layer later; never change the calculation to change a target.
DEFAULT_KPI_TARGETS = MappingProxyType(
    {
        "service_level_percent": None,
        "aht_seconds": None,
        "asa_seconds": None,
        "abandonment_rate_percent": None,
        "answer_rate_percent": None,
    }
)

# These imported fields are retained for source reconciliation only. They are NOT
# canonical calculation inputs.
SOURCE_REPORTED_RECONCILIATION_FIELDS = (
    "source_reported_aht_seconds",
    "source_reported_asa_seconds",
    "source_reported_sla_percent",
)
