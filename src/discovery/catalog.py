from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldType = Literal["integer", "number", "text", "datetime", "boolean", "mixed", "empty"]


@dataclass(frozen=True, slots=True)
class SemanticConcept:
    """A governed business concept; aliases generate suggestions, not proof of equivalence."""

    key: str
    display_name: str
    description: str
    aliases: tuple[str, ...]
    expected_types: tuple[str, ...]
    required_approval_fields: tuple[str, ...]


DEFAULT_SEMANTIC_CATALOG: tuple[SemanticConcept, ...] = (
    SemanticConcept(
        key="customer_satisfaction_score",
        display_name="Customer satisfaction score",
        description=(
            "A customer survey measure of satisfaction. The scale, population, survey timing, "
            "and calculation method must be confirmed per source."
        ),
        aliases=(
            "csat", "csat_score", "customer_score", "customer_satisfaction",
            "satisfaction_score", "survey_rating", "survey_score",
        ),
        expected_types=("integer", "number"),
        required_approval_fields=(
            "business_definition", "measurement_scale", "population", "time_window", "exclusions"
        ),
    ),
    SemanticConcept(
        key="net_promoter_score",
        display_name="Net Promoter Score",
        description=(
            "A recommendation measure; its survey question and standard NPS calculation "
            "must be verified rather than inferred from the column name."
        ),
        aliases=("nps", "nps_score", "promoter_score", "recommendation_score"),
        expected_types=("integer", "number"),
        required_approval_fields=(
            "business_definition", "measurement_scale", "population", "time_window", "formula", "exclusions"
        ),
    ),
    SemanticConcept(
        key="agent_quality_score",
        display_name="Agent quality score",
        description="A quality-assurance score whose rubric, scale, and evaluation population must be confirmed.",
        aliases=("qa_score", "quality_score", "agent_rating"),
        expected_types=("integer", "number"),
        required_approval_fields=(
            "business_definition", "measurement_scale", "population", "time_window", "formula", "exclusions"
        ),
    ),
    SemanticConcept(
        key="average_handle_time_seconds",
        display_name="Average handle time (seconds)",
        description="Average handling duration. Verify included components and units before using it as AHT.",
        aliases=("aht", "aht_seconds", "aht_secs", "avg_handle_time", "average_handle_time", "handle_time_seconds"),
        expected_types=("integer", "number"),
        required_approval_fields=("business_definition", "unit", "grain", "time_window", "population", "exclusions"),
    ),
    SemanticConcept(
        key="service_level_pct",
        display_name="Service level (%)",
        description="Share of eligible contacts answered within a defined threshold; formula and denominator are critical.",
        aliases=("service_level", "service_level_pct", "sla_pct", "answered_within_target_pct"),
        expected_types=("integer", "number"),
        required_approval_fields=(
            "business_definition", "unit", "formula", "denominator", "threshold", "population", "time_window", "exclusions"
        ),
    ),
    SemanticConcept(
        key="offered_contacts",
        display_name="Offered contacts",
        description="Count of contacts offered, with its event definition and aggregation grain explicitly confirmed.",
        aliases=("offered", "offered_count", "contacts_offered"),
        expected_types=("integer", "number"),
        required_approval_fields=("business_definition", "grain", "time_window", "population", "exclusions"),
    ),
    SemanticConcept(
        key="handled_contacts",
        display_name="Handled contacts",
        description="Count of handled contacts according to a source-specific handling definition.",
        aliases=("handled", "handled_count", "contacts_handled"),
        expected_types=("integer", "number"),
        required_approval_fields=("business_definition", "grain", "time_window", "population", "exclusions"),
    ),
    SemanticConcept(
        key="customer_feedback_text",
        display_name="Customer feedback text",
        description="Free-text customer feedback; language and redaction requirements must be reviewed before use.",
        aliases=("customer_feedback", "feedback_text", "customer_comment", "survey_comment", "comment"),
        expected_types=("text",),
        required_approval_fields=("business_definition", "population", "time_window", "privacy_review"),
    ),
    SemanticConcept(
        key="contact_reference",
        display_name="Contact reference",
        description="A source-local identifier for a contact or interaction; uniqueness scope must be verified.",
        aliases=("contact_id", "interaction_id", "case_id", "contact_ref"),
        expected_types=("identifier", "text", "integer"),
        required_approval_fields=("business_definition", "uniqueness_scope", "privacy_review"),
    ),
)


def normalize_name(value: str) -> str:
    """Normalize a column label for matching without applying fuzzy AI inference."""
    return "_".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
