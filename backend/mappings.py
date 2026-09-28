"""
Backwards-compatible alias for the keyword maps.

This module used to hold its own hand-written copy of TABLE_MAP / COLUMN_MAP
and friends. That copy described a schema that no longer exists (an `employees`
table, a `projects` table, salary/deadline columns), and nothing imported it -
so it was pure drift waiting to mislead the next reader.

It is now a re-export of the single source of truth in services/nlp_to_sql.py,
which is kept in sync with the live database on every conversion. Import from
either place and you get the same, current, schema-accurate maps.
"""

from services.nlp_to_sql import (  # noqa: F401
    TABLE_MAP,
    COLUMN_MAP,
    INTENT_MAP,
    CONDITION_MAP,
    AGGREGATE_MAP,
    SORT_DIRECTION_MAP,
    JOIN_TYPE_MAP,
    DEPARTMENTS,
    CITIES,
    GENDERS,
    CATEGORICAL_COLUMNS,
    DEFAULT_NUMERIC_COLUMN,
    STATIC_TABLE_COLUMNS,
    UNSUPPORTED_CONCEPT_WORDS,
)

__all__ = [
    "TABLE_MAP",
    "COLUMN_MAP",
    "INTENT_MAP",
    "CONDITION_MAP",
    "AGGREGATE_MAP",
    "SORT_DIRECTION_MAP",
    "JOIN_TYPE_MAP",
    "DEPARTMENTS",
    "CITIES",
    "GENDERS",
    "CATEGORICAL_COLUMNS",
    "DEFAULT_NUMERIC_COLUMN",
    "STATIC_TABLE_COLUMNS",
    "UNSUPPORTED_CONCEPT_WORDS",
]
