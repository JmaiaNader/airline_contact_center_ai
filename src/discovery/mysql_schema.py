"""Read-only relational schema discovery for the configured AeroInsight database.

This connector inspects database metadata only. It never reads business rows,
creates objects, changes data, or executes user-supplied SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Engine, Float, Integer, Numeric, Time, inspect

from src.discovery.catalog import DEFAULT_SEMANTIC_CATALOG
from src.discovery.mapping import MappingAssessment, assess_field_mapping
from src.discovery.profiling import FieldProfile

_SCHEMA_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")


@dataclass(frozen=True, slots=True)
class DatabaseColumnProfile:
    schema_name: str
    table_name: str
    column_name: str
    database_type: str
    inferred_type: str
    nullable: bool
    is_primary_key: bool
    is_indexed: bool
    foreign_key_targets: tuple[str, ...]
    mapping: MappingAssessment


@dataclass(frozen=True, slots=True)
class DatabaseTableProfile:
    schema_name: str
    table_name: str
    columns: tuple[DatabaseColumnProfile, ...]
    primary_key_columns: tuple[str, ...]
    has_tenant_id: bool


@dataclass(frozen=True, slots=True)
class DatabaseSchemaProfile:
    schema_name: str
    tables: tuple[DatabaseTableProfile, ...]
    warnings: tuple[str, ...]

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def column_count(self) -> int:
        return sum(len(table.columns) for table in self.tables)


def _infer_sqlalchemy_type(sql_type: Any) -> str:
    """Map SQLAlchemy type objects to the small governed field-type vocabulary."""
    if isinstance(sql_type, Boolean):
        return "boolean"
    if isinstance(sql_type, (DateTime, Date, Time)):
        return "datetime"
    if isinstance(sql_type, Integer):
        return "integer"
    if isinstance(sql_type, (Numeric, Float)):
        return "number"
    # String, enum, JSON and other non-numeric metadata are treated as text for
    # discovery purposes; the semantic catalog still decides compatibility.
    return "text"


def inspect_database_schema(
    engine: Engine,
    *,
    schema_name: str,
    expected_schema: str,
    table_names: tuple[str, ...] | None = None,
) -> DatabaseSchemaProfile:
    """Inspect only the configured schema's metadata and assess column names.

    `expected_schema` must come from trusted application settings, never from a
    Streamlit widget. Optional table_names only filters tables already discovered
    from that schema; it cannot change the schema or supply SQL identifiers.
    """
    if not isinstance(schema_name, str) or not _SCHEMA_NAME.fullmatch(schema_name):
        raise ValueError("schema_name has an invalid format.")
    if not isinstance(expected_schema, str) or not _SCHEMA_NAME.fullmatch(expected_schema):
        raise ValueError("expected_schema has an invalid format.")
    if schema_name != expected_schema:
        raise PermissionError("Schema inspection is restricted to the configured database.")

    requested_tables: set[str] | None = None
    if table_names is not None:
        if not isinstance(table_names, tuple) or any(
            not isinstance(name, str) or not name or len(name) > 64 for name in table_names
        ):
            raise ValueError("table_names must be a tuple of valid table names.")
        requested_tables = set(table_names)

    inspector = inspect(engine)
    available_tables = sorted(inspector.get_table_names(schema=schema_name))
    if requested_tables is not None:
        unknown = requested_tables.difference(available_tables)
        if unknown:
            raise ValueError("One or more requested tables are not present in the configured schema.")
        available_tables = [name for name in available_tables if name in requested_tables]

    table_profiles: list[DatabaseTableProfile] = []
    for table_name in available_tables:
        raw_columns = inspector.get_columns(table_name, schema=schema_name)
        pk_data = inspector.get_pk_constraint(table_name, schema=schema_name) or {}
        pk_columns = tuple(pk_data.get("constrained_columns") or ())
        pk_set = set(pk_columns)

        indexed_columns: set[str] = set()
        for index in inspector.get_indexes(table_name, schema=schema_name) or ():
            indexed_columns.update(index.get("column_names") or ())
        for index in inspector.get_unique_constraints(table_name, schema=schema_name) or ():
            indexed_columns.update(index.get("column_names") or ())
        indexed_columns.update(pk_columns)

        fk_targets_by_column: dict[str, list[str]] = {}
        for fk in inspector.get_foreign_keys(table_name, schema=schema_name) or ():
            referred_table = fk.get("referred_table") or "?"
            referred_schema = fk.get("referred_schema") or schema_name
            referred_columns = fk.get("referred_columns") or []
            for local_column, remote_column in zip(
                fk.get("constrained_columns") or (), referred_columns
            ):
                fk_targets_by_column.setdefault(local_column, []).append(
                    f"{referred_schema}.{referred_table}.{remote_column}"
                )

        columns: list[DatabaseColumnProfile] = []
        for column in raw_columns:
            column_name = str(column["name"])
            sql_type_obj = column.get("type")
            inferred_type = _infer_sqlalchemy_type(sql_type_obj)
            # Schema discovery intentionally supplies no row samples or data values.
            field = FieldProfile(
                name=column_name,
                inferred_type=inferred_type,
                row_count=0,
                non_empty_count=0,
                null_count=0,
                distinct_count=0,
                sample_values=(),
            )
            assessment = assess_field_mapping(field, catalog=DEFAULT_SEMANTIC_CATALOG)
            columns.append(
                DatabaseColumnProfile(
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                    database_type=str(sql_type_obj),
                    inferred_type=inferred_type,
                    nullable=bool(column.get("nullable", True)),
                    is_primary_key=column_name in pk_set,
                    is_indexed=column_name in indexed_columns,
                    foreign_key_targets=tuple(sorted(fk_targets_by_column.get(column_name, ()))),
                    mapping=assessment,
                )
            )

        table_profiles.append(
            DatabaseTableProfile(
                schema_name=schema_name,
                table_name=table_name,
                columns=tuple(columns),
                primary_key_columns=pk_columns,
                has_tenant_id=any(item.column_name == "tenant_id" for item in columns),
            )
        )

    warnings = (
        "This scan reads database metadata only; no business rows or passenger data are queried.",
        "Mapping scores are heuristic suggestions, not probabilities or proof of business equivalence.",
        "No mapping is approved or persisted by this read-only discovery stage.",
        "Tenant data access and mapping approvals must use a server-resolved AuthenticatedTenantContext.",
    )
    return DatabaseSchemaProfile(schema_name, tuple(table_profiles), warnings)
