"""
Chatbot / query-refinement logic.

This module is intentionally kept separate from nlp_to_sql.py. It does NOT
re-run the NLP parser. Instead it:
  1. Parses the previously-generated SQL string back into a small structured
     dict (table / select columns / where conditions / group by / having /
     order by / limit) using regex.
  2. Applies rule-based edits to that dict based on the user's free-text
     feedback, reusing the same vocabulary dictionaries as nlp_to_sql.py
     (TABLE_MAP, COLUMN_MAP, CITIES, DEPARTMENTS, GENDERS, SORT_DIRECTION_MAP)
     so "Bangalore", "HR", "descending", etc. are recognised consistently.
  3. Rebuilds a new SQL string from the edited dict.

Scope / known limitation: only "simple" SELECT ... FROM <table> [WHERE ...]
[GROUP BY ...] [HAVING ...] [ORDER BY ...] [LIMIT ...] queries can be
refined this way. If the previous SQL contains a JOIN, UNION, EXISTS,
CASE, or a subquery, refinement is declined and the user is asked to
rephrase their original question instead - those query shapes are complex
enough that blind text-editing of the SQL string would be unsafe.
"""

import re
from nltk.tokenize import word_tokenize

from services.nlp_to_sql import (
    TABLE_MAP,
    COLUMN_MAP,
    CITIES,
    DEPARTMENTS,
    GENDERS,
    SORT_DIRECTION_MAP,
    CATEGORICAL_COLUMNS,
)

DEFAULT_NUMERIC_COLUMN = {
    "students": "marks",
    "employees": "salary",
}


class RefinementError(Exception):
    """Raised when the previous SQL can't be parsed, or the feedback can't
    be confidently understood. The Flask route turns this into a 422/400
    JSON error rather than a 500, since it's a user-input problem, not a
    server bug."""
    pass


# ---------------- SQL -> structured dict ----------------

UNSUPPORTED_KEYWORDS = ["JOIN", "UNION", " EXISTS", "CASE WHEN", "IFNULL(", "COALESCE("]

SELECT_RE = re.compile(
    r'^SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<table>[A-Za-z_]\w*)'
    r'(?:\s+WHERE\s+(?P<where>.+?))?'
    r'(?:\s+GROUP BY\s+(?P<group_by>.+?))?'
    r'(?:\s+HAVING\s+(?P<having>.+?))?'
    r'(?:\s+ORDER BY\s+(?P<order_by>.+?))?'
    r'(?:\s+LIMIT\s+(?P<limit>\d+))?$',
    re.IGNORECASE,
)

# Matches ONE condition at a time out of a WHERE clause, in the exact
# shapes nlp_to_sql.py generates them in. This has to understand
# BETWEEN x AND y as a single condition (not split on that inner "AND"),
# and IN (...) / NOT IN (...) as a single condition (not split on inner
# commas).
CONDITION_RE = re.compile(
    r"[A-Za-z_]\w*\s+(?:"
    r"NOT BETWEEN\s+\S+\s+AND\s+\S+|BETWEEN\s+\S+\s+AND\s+\S+|"
    r"NOT IN\s*\([^)]*\)|IN\s*\([^)]*\)|"
    r"IS NOT NULL|IS NULL|"
    r"NOT LIKE\s+'[^']*'|LIKE\s+'[^']*'|"
    r"(?:>=|<=|!=|=|>|<)\s*(?:'[^']*'|\S+)"
    r")",
    re.IGNORECASE,
)


def normalize_sql(sql):
    return re.sub(r"\s+", " ", sql).strip()


def parse_query(sql):
    normalized = normalize_sql(sql)
    upper = normalized.upper()

    if upper.count("SELECT") > 1 or any(kw in upper for kw in UNSUPPORTED_KEYWORDS):
        raise RefinementError(
            "That query uses a JOIN/UNION/subquery, which is too complex to "
            "refine automatically. Try rephrasing your original question instead."
        )

    m = SELECT_RE.match(normalized)
    if not m:
        raise RefinementError("Couldn't understand the previous SQL well enough to refine it.")

    d = m.groupdict()
    select_raw = d["select"].strip()
    select_cols = ["*"] if select_raw == "*" else [c.strip() for c in select_raw.split(",")]

    where_conditions = []
    if d["where"]:
        where_conditions = [mm.group(0).strip() for mm in CONDITION_RE.finditer(d["where"])]
        if not where_conditions:
            # fallback: couldn't decompose it, keep as one opaque chunk
            where_conditions = [d["where"].strip()]

    return {
        "select": select_cols,
        "table": d["table"],
        "where": where_conditions,
        "group_by": d["group_by"].strip() if d["group_by"] else None,
        "having": d["having"].strip() if d["having"] else None,
        "order_by": d["order_by"].strip() if d["order_by"] else None,
        "limit": d["limit"],
    }


def rebuild_sql(ctx):
    select_sql = "*" if ctx["select"] == ["*"] else ", ".join(ctx["select"])
    sql = f"SELECT {select_sql} FROM {ctx['table']}"

    if ctx["where"]:
        sql += " WHERE " + " AND ".join(ctx["where"])
    if ctx["group_by"]:
        sql += f" GROUP BY {ctx['group_by']}"
    if ctx["having"]:
        sql += f" HAVING {ctx['having']}"
    if ctx["order_by"]:
        sql += f" ORDER BY {ctx['order_by']}"
    if ctx["limit"]:
        sql += f" LIMIT {ctx['limit']}"

    return sql


# ---------------- feedback -> edits ----------------

ONLY_TRIGGERS = {"only", "just"}
REMOVE_TRIGGERS = {"remove", "drop", "clear", "without", "exclude"}
SORT_WORDS = {"sort", "order", "arrange", "ascending", "descending", "asc", "desc"}
SWAP_TRIGGERS = {"instead", "meant", "not"}
LIMIT_WORDS = {"top", "limit", "first"}


def _extract_columns(tokens):
    cols = []
    for w in tokens:
        if w in COLUMN_MAP and COLUMN_MAP[w] not in cols:
            cols.append(COLUMN_MAP[w])
    return cols


def apply_feedback(ctx, feedback_text):
    """Mutates and returns (ctx, applied_changes). Raises RefinementError
    if nothing in the feedback could be confidently mapped to an edit."""

    text = feedback_text.lower().strip()
    tokens = word_tokenize(text)
    applied = []

    # 1. Table swap - "employees instead of students", "I meant employees not students"
    tables_mentioned = [TABLE_MAP[w] for w in tokens if w in TABLE_MAP]
    # de-dupe while keeping order
    seen = []
    for t in tables_mentioned:
        if t not in seen:
            seen.append(t)
    tables_mentioned = seen

    if len(tables_mentioned) >= 1 and any(w in tokens for w in SWAP_TRIGGERS):
        new_table = tables_mentioned[0]
        if new_table != ctx["table"]:
            ctx["table"] = new_table
            ctx["where"] = []  # old filters (e.g. department, which is
            # employees-only) don't necessarily carry over safely to a
            # different table, so they're cleared rather than risk an
            # invalid column reference
            applied.append(f"switched table to '{new_table}' (cleared old filters)")

    # 2. Column restriction - "only want name and marks", "just show name, marks"
    if any(t in tokens for t in ONLY_TRIGGERS):
        cols = _extract_columns(tokens)
        if cols:
            ctx["select"] = cols
            applied.append(f"limited columns to: {', '.join(cols)}")

    # 3. Sort direction / column
    if any(t in tokens for t in SORT_WORDS):
        direction = None
        for w in tokens:
            if w in SORT_DIRECTION_MAP:
                direction = SORT_DIRECTION_MAP[w]
                break
        if direction is None:
            if "highest" in tokens or "biggest" in tokens or "largest" in tokens:
                direction = "DESC"
            elif "lowest" in tokens or "smallest" in tokens:
                direction = "ASC"

        sort_col = None
        for w in tokens:
            if w in COLUMN_MAP and COLUMN_MAP[w] not in CATEGORICAL_COLUMNS:
                sort_col = COLUMN_MAP[w]
                break
        if sort_col is None and ctx["order_by"]:
            sort_col = ctx["order_by"].split()[0]
        if sort_col is None and ctx["select"] and ctx["select"] != ["*"]:
            sort_col = ctx["select"][0]
        if sort_col is None:
            sort_col = DEFAULT_NUMERIC_COLUMN.get(ctx["table"])

        if sort_col:
            direction = direction or "ASC"
            ctx["order_by"] = f"{sort_col} {direction}"
            applied.append(f"sorting by {sort_col} {direction}")

    # 4. Remove filters (specific column, or all)
    if any(t in tokens for t in REMOVE_TRIGGERS) or "no filter" in text or "no condition" in text:
        removed_col = None
        for w in tokens:
            if w in COLUMN_MAP:
                removed_col = COLUMN_MAP[w]
                break
        if removed_col:
            before = len(ctx["where"])
            ctx["where"] = [c for c in ctx["where"] if not c.lower().startswith(removed_col.lower() + " ")]
            if len(ctx["where"]) < before:
                applied.append(f"removed filter on '{removed_col}'")
        elif ctx["where"]:
            ctx["where"] = []
            applied.append("cleared all filters")

    # 5. Categorical filters - city / department / gender
    #    "it" is deliberately excluded unless "department"/"dept" is also
    #    present - otherwise ordinary pronouns ("make it better", "fix it")
    #    would be misread as the IT department, the same collision
    #    nlp_to_sql.py itself guards against.
    mentions_department_word = "department" in tokens or "dept" in tokens

    for value_list, colname, caser in [
        (CITIES, "city", str.title),
        (DEPARTMENTS, "department", str.upper),
        (GENDERS, "gender", str.capitalize),
    ]:
        found = [
            w for w in tokens
            if w in value_list and not (colname == "department" and w == "it" and not mentions_department_word)
        ]
        if found:
            val = caser(found[0])
            new_cond = f"{colname} = '{val}'"
            ctx["where"] = [c for c in ctx["where"] if not c.lower().startswith(colname.lower() + " ")]
            ctx["where"].append(new_cond)
            applied.append(f"filtered {colname} = '{val}'")

    # 6. Limit / top N
    limit_val = None
    for w in tokens:
        if w.isdigit():
            limit_val = w
    if limit_val and any(t in tokens for t in LIMIT_WORDS):
        ctx["limit"] = limit_val
        applied.append(f"limit set to {limit_val}")

    if not applied:
        raise RefinementError(
            "Couldn't confidently tell what to change from that feedback. "
            "Try something specific, e.g. 'only show name and marks', "
            "'sort by salary descending', 'show only employees from "
            "Bangalore', or 'remove the department filter'."
        )

    return ctx, applied