"""
Chatbot / query-refinement logic.

This module is intentionally kept separate from nlp_to_sql.py. It does NOT
re-run the NLP parser. Instead it:
  1. Parses the previously-generated SQL string back into a small structured
     dict (table / select columns / where conditions / group by / having /
     order by / limit) using regex.
  2. Applies rule-based edits to that dict based on the user's free-text
     feedback, reusing the same vocabulary dictionaries as nlp_to_sql.py
     (TABLE_MAP, COLUMN_MAP, CITIES, DEPARTMENTS, SORT_DIRECTION_MAP)
     so "Bangalore", "HR", "descending", etc. are recognised consistently.
     It also reuses nlp_to_sql.py's words_to_numbers() and
     merge_comparison_phrases() helpers, so English number words ("two",
     "one hundred") and >=/<= phrasings ("at least", "2 or more") are
     understood the same way here as in the main NLP parser.
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
    SORT_DIRECTION_MAP,
    CATEGORICAL_COLUMNS,
    # Shared with the main parser so both agree on what a column is called
    # for a given table, and on which numeric column a table falls back to
    # when the feedback names none.
    DEFAULT_NUMERIC_COLUMN,
    department_display,
    city_display,
    resolve_column,
    table_columns,
    build_department_id_condition,
    CATEGORICAL_VALUE_COLUMN,
    CATEGORICAL_VALUE_DISPLAY,
    # "max marks", "subject name", "phone number" ... are stored as single
    # canonical keys, so the phrase has to be collapsed before the tokens are
    # scanned for columns - otherwise "only show subject name and max marks"
    # reads "marks" as marks.Marks (wrong table), drops it, and never reaches
    # Max_Marks at all.
    merge_multiword_columns,
    # Real values of the low-cardinality text columns, used to check a
    # categorical word against what the column actually holds.
    COLUMN_VALUES,
    refresh_column_values,
    words_to_numbers,
    merge_comparison_phrases,
)


class RefinementError(Exception):
    """Raised when the previous SQL can't be parsed, or the feedback can't
    be confidently understood. The Flask route turns this into a 422/400
    JSON error rather than a 500, since it's a user-input problem, not a
    server bug."""
    pass


# ---------------- SQL -> structured dict ----------------

UNSUPPORTED_KEYWORDS = ["JOIN", "UNION", " EXISTS", "CASE WHEN", "IFNULL(", "COALESCE("]

# The main parser resolves a spoken department through the `department` table
# ("... WHERE department_id = (SELECT department_id FROM department WHERE
# department_name = 'IT')") rather than inventing a "department" column that
# no table has. That nested SELECT would otherwise trip the "more than one
# SELECT" refusal below and make every department query un-refinable, so it is
# lifted out first and kept as one opaque, replaceable condition.
#
# All three forms nlp_to_sql.py can emit are matched: "department_id = (...)",
# "department_id IN (...)" and the negated variants. The whole match is kept
# verbatim, so putting it back can only ever reproduce valid SQL.
DEPARTMENT_SUBQUERY_RE = re.compile(
    r"department_id\s*(?:NOT\s+IN|IN|=)\s*\(\s*SELECT\s+department_id\s+FROM\s+"
    r"department\s+WHERE\s+department_name\s*(?:NOT\s+IN|IN|=)\s*"
    r"(?:\(\s*'[^']*'(?:\s*,\s*'[^']*')*\s*\)|'[^']*')\s*\)",
    re.IGNORECASE,
)

# Placeholder written into the WHERE list in place of the lifted subquery. The
# trailing digits index into ctx["subqueries"], and rebuild_sql swaps the real
# SQL back in before the statement is returned. It is shaped like a condition
# (rather than a bare word) so CONDITION_RE still splits it out of a compound
# WHERE instead of swallowing it into the "couldn't decompose" fallback chunk.
DEPARTMENT_SUBQUERY_TOKEN_RE = re.compile(r"__department_subquery_(\d+)__")

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
    r")"
    # The lifted department subquery, which stands in for one whole condition
    # (see DEPARTMENT_SUBQUERY_TOKEN_RE).
    r"|__department_subquery_\d+__",
    re.IGNORECASE,
)


def normalize_sql(sql):
    return re.sub(r"\s+", " ", sql).strip()


def parse_query(sql):
    normalized = normalize_sql(sql)
    upper = normalized.upper()

    subqueries = []

    def _lift(match):
        subqueries.append(" ".join(match.group(0).split()))
        return f"__department_subquery_{len(subqueries) - 1}__"

    if DEPARTMENT_SUBQUERY_RE.search(normalized):
        normalized = DEPARTMENT_SUBQUERY_RE.sub(_lift, normalized)
        upper = normalized.upper()

    # the department lookup(s) above were the only tolerated second SELECT
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
        "subqueries": subqueries,
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

    # Put the lifted department subquery back. An unrecognised index is left
    # as the bare placeholder rather than dropped, so a bug here surfaces as
    # an obviously-invalid WHERE instead of a silently narrower query.
    subqueries = ctx.get("subqueries") or []
    if subqueries:
        def _restore(match):
            index = int(match.group(1))
            return subqueries[index] if index < len(subqueries) else match.group(0)

        sql = DEPARTMENT_SUBQUERY_TOKEN_RE.sub(_restore, sql)

    return sql


# ---------------- feedback -> edits ----------------

ONLY_TRIGGERS = {"only", "just"}
REMOVE_TRIGGERS = {"remove", "drop", "clear", "without", "exclude"}
SORT_WORDS = {"sort", "sorted", "order", "ordered", "arrange", "ascending", "descending", "asc", "desc"}
# "instead"/"meant"/"not" name a replacement table or column; "swap"/"rather"
# can only ever mean a column ("swap department for address" - swapping the
# table there would silently answer a question about a different table)
TABLE_SWAP_TRIGGERS = {"instead", "meant", "not"}
COLUMN_SWAP_TRIGGERS = TABLE_SWAP_TRIGGERS | {"swap", "rather"}
SWAP_TRIGGERS = TABLE_SWAP_TRIGGERS
LIMIT_WORDS = {"top", "limit", "first"}

# Words that signal "more than N rows per group" - i.e. a HAVING COUNT(*)
# filter, as opposed to a WHERE filter on an individual row's value.
# Deliberately does NOT reuse nlp_to_sql.py's CONDITION_MAP: that map's
# "above"/"below"/"greater"/"less" are about a single row's numeric column
# (e.g. "marks above 80"), while this is specifically about the size of a
# group after GROUP BY - keeping them separate avoids the two rules ever
# fighting over the same word in different contexts.
HAVING_GTE_WORDS = {"more", "greater", "above", "over"}
HAVING_LTE_WORDS = {"less", "fewer", "below", "under"}
# Words that signal the feedback is actually about group *size* (row count)
# rather than, say, a plain numeric filter on a column - only fires the
# HAVING rule when one of these also appears, so "salary above 50000"
# (a WHERE filter) is never mistaken for a group-count filter.
HAVING_SCOPE_WORDS = {"students", "employees", "rows", "records", "entries", "count", "count(*)"}


def _extract_columns(tokens, table=None):
    cols = []
    for w in tokens:
        if w in COLUMN_MAP and COLUMN_MAP[w] not in cols:
            col = COLUMN_MAP[w]
            if col == "name":
                col = resolve_column("name", table) if table else col
            if table and col not in table_columns(table):
                continue
            cols.append(col)
    return cols


def apply_feedback(ctx, feedback_text):
    """Mutates and returns (ctx, applied_changes). Raises RefinementError
    if nothing in the feedback could be confidently mapped to an edit."""

    text = feedback_text.lower().strip()
    tokens = word_tokenize(text)
    # Same normalization the main NLP parser applies, so "two", "one
    # hundred", "at least", "3 or more" etc. are understood identically
    # here as they are in nlp_to_sql.py - run BEFORE any rule below scans
    # for digits or comparison words, for the same reason nlp_to_sql.py
    # runs them first (later rules would otherwise fire on the individual
    # words a phrase is built from, e.g. "least" alone, before the phrase
    # is collapsed).
    tokens = words_to_numbers(tokens)
    tokens = merge_comparison_phrases(tokens)
    # ...and the same for multi-word column names, so "max marks" reaches
    # Max_Marks instead of being read as the unrelated marks.Marks
    tokens = merge_multiword_columns(tokens)
    # the categorical rules below check a spoken value against what the column
    # really holds, which needs the sampled values; the sampler is cached, and
    # an unreachable database just leaves the map empty
    refresh_column_values()
    applied = []

    # 1. Table swap - "employees instead of students", "I meant employees not students"
    tables_mentioned = [TABLE_MAP[w] for w in tokens if w in TABLE_MAP]
    # de-dupe while keeping order
    seen = []
    for t in tables_mentioned:
        if t not in seen:
            seen.append(t)
    tables_mentioned = seen

    if len(tables_mentioned) >= 1 and any(w in tokens for w in TABLE_SWAP_TRIGGERS):
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
        cols = _extract_columns(tokens, table=ctx["table"])
        if cols:
            ctx["select"] = cols
            applied.append(f"limited columns to: {', '.join(cols)}")

            # If the query is GROUP BY'd and the restriction narrows it to
            # a single column that isn't the current grouping column,
            # follow it - "SELECT department ... GROUP BY subject" is
            # either invalid SQL or silently wrong, so the grouping is
            # updated to stay consistent with what's being shown.
            restricted = [c for c in cols if c != "COUNT(*)"]
            if ctx["group_by"] and len(restricted) == 1 and ctx["group_by"] != restricted[0]:
                ctx["group_by"] = restricted[0]

    # 3. Column swap - "swap department for address", "show phone number
    #    instead of address". Both columns have to be real columns of the
    #    same table: this only rewrites the projection, never a WHERE
    #    condition, so the filter the user already agreed to keeps working.
    if any(t in tokens for t in COLUMN_SWAP_TRIGGERS):
        _real_cols = table_columns(ctx["table"])
        # every column the feedback named is collected, not just the ones this
        # table happens to have: "swap department for address" names a
        # department, and employee_info has no department column to replace -
        # it has a Department_ID the user is thinking of as "the department
        # bit". The replacement still has to be a real column.
        named = []
        for w in tokens:
            if w in COLUMN_MAP:
                col = COLUMN_MAP[w]
                if col == "name":
                    col = resolve_column("name", ctx["table"])
                if col not in named:
                    named.append(col)
        _named_real = [c for c in named if c in _real_cols]
        if len(named) >= 2 and _named_real:
            old_col = named[0]
            new_col = _named_real[-1]
            if old_col.lower() == new_col.lower():
                old_col, new_col = new_col, _named_real[0] if _named_real[0].lower() != new_col.lower() else old_col
            if old_col.lower() != new_col.lower():
                if ctx["select"] == ["*"]:
                    # `SELECT *` has to be spelled out to drop one column
                    ctx["select"] = [
                        c for c in sorted(_real_cols) if c.lower() != old_col.lower()
                    ]
                replaced = False
                for i, c in enumerate(ctx["select"]):
                    if c.lower() == old_col.lower():
                        ctx["select"][i] = new_col
                        replaced = True
                if not replaced:
                    # the thing being replaced isn't a column of this table, so
                    # the request is really "show me that instead"
                    ctx["select"] = [new_col]
                    applied.append(f"showed '{new_col}' instead of '{old_col}'")
                else:
                    # a GROUP BY / ORDER BY on the column that just left the
                    # projection has to follow it, or the query stops being valid
                    if ctx["group_by"] and ctx["group_by"].lower() == old_col.lower():
                        ctx["group_by"] = new_col
                    if ctx["order_by"] and ctx["order_by"].split()[0].lower() == old_col.lower():
                        _parts = ctx["order_by"].split()
                        ctx["order_by"] = " ".join([new_col] + _parts[1:])
                    applied.append(f"swapped '{old_col}' for '{new_col}'")

    # 4. Sort direction / column
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

        _real_cols = table_columns(ctx["table"])
        sort_col = None
        # did the feedback name something we could not use? if so the
        # fallbacks below must not quietly sort by a different column
        named_unusable = False
        named_categorical = None
        for w in tokens:
            if w not in COLUMN_MAP:
                continue
            candidate = COLUMN_MAP[w]
            if candidate == "name":
                candidate = resolve_column("name", ctx["table"])
            # ORDER BY has to name a column the table actually has
            if candidate not in _real_cols:
                named_unusable = True
                continue
            # the abstract "name" is preferred over anything else; a real
            # categorical column (address, exam, result) is still a perfectly
            # good sort key, it is just not what the user named first
            if candidate in CATEGORICAL_COLUMNS and candidate != "name":
                if named_categorical is None:
                    named_categorical = candidate
                continue
            sort_col = candidate
            break
        # "sort by department name" on a table that only stores Department_ID
        # needs a JOIN to department, which this refiner cannot build. So does
        # "sort by marks" on student_info. Falling back to some other column
        # (a name, the first selected column, the table's default numeric) in
        # that situation answers a different question than the one that was
        # asked, so the request goes to the agentic refiner instead.
        if named_unusable and sort_col is None:
            raise RefinementError(
                "I can't sort this query by that - it would need a join to "
                "another table. Try asking for it as a new question."
            )
        if sort_col is None and named_categorical:
            sort_col = named_categorical
        if sort_col is None and ctx["order_by"]:
            existing = ctx["order_by"].split()[0]
            sort_col = existing if existing in _real_cols else None
        if sort_col is None and ctx["select"] and ctx["select"] != ["*"]:
            first = ctx["select"][0]
            sort_col = first if first in _real_cols else None
        if sort_col is None:
            sort_col = DEFAULT_NUMERIC_COLUMN.get(ctx["table"])

        if sort_col:
            direction = direction or "ASC"
            ctx["order_by"] = f"{sort_col} {direction}"
            applied.append(f"sorting by {sort_col} {direction}")

    # 5. Remove filters (specific column, or all)
    if any(t in tokens for t in REMOVE_TRIGGERS) or "no filter" in text or "no condition" in text:
        removed_col = None
        for w in tokens:
            if w in COLUMN_MAP:
                candidate = COLUMN_MAP[w]
                if candidate == "name":
                    candidate = resolve_column("name", ctx["table"])
                removed_col = candidate
                break
        if removed_col:
            before = len(ctx["where"])
            ctx["where"] = [c for c in ctx["where"] if not c.lower().startswith(removed_col.lower() + " ")]
            if len(ctx["where"]) < before:
                applied.append(f"removed filter on '{removed_col}'")
            elif removed_col in ctx["select"]:
                ctx["select"] = [c for c in ctx["select"] if c.lower() != removed_col.lower()]
                applied.append(f"removed column '{removed_col}'")
            elif ctx["select"] == ["*"]:
                # "remove budget" after a `SELECT *` means "show me everything
                # except budget" - there is no WHERE to strip, so the only
                # honest reading is to name the remaining columns
                _real = sorted(table_columns(ctx["table"]))
                remaining = [c for c in _real if c.lower() != removed_col.lower()]
                if remaining:
                    ctx["select"] = remaining
                    applied.append(
                        f"hidden '{removed_col}', showing the other "
                        f"{len(remaining)} columns"
                    )
        elif ctx["where"]:
            ctx["where"] = []
            applied.append("cleared all filters")

    # 4.5. HAVING / group-count filter - "subjects with more than 2
    # students", "only show departments where count is at least 3", etc.
    # Only makes sense when the query already has a GROUP BY (i.e. we're
    # filtering groups, not individual rows) - so this can never attach an
    # invalid HAVING to a non-grouped query. Also requires a
    # HAVING_SCOPE_WORDS hit (students/employees/rows/records/count) so a
    # plain row-level filter like "salary above 50000" is never mistaken
    # for a group-size filter.
    if ctx["group_by"] and any(w in tokens for w in HAVING_SCOPE_WORDS):
        num = None
        for w in tokens:
            if w.isdigit():
                num = w  # last digit wins, matching the same convention
                # nlp_to_sql.py's generic number scan uses

        op = None
        if "AT_LEAST" in tokens:
            op = ">="
        elif "AT_MOST" in tokens:
            op = "<="
        elif any(w in tokens for w in HAVING_GTE_WORDS):
            op = ">"
        elif any(w in tokens for w in HAVING_LTE_WORDS):
            op = "<"

        if num and op:
            ctx["having"] = f"COUNT(*) {op} {num}"
            if ctx["select"] != ["*"] and "COUNT(*)" not in ctx["select"]:
                ctx["select"].append("COUNT(*)")
            applied.append(f"added group filter: COUNT(*) {op} {num}")

    # 5. Categorical filters - department / city(address) / exam / result
    #    "it" is a real department name here, but it is also the most common
    #    pronoun in English ("make it better"). The disambiguator is the table
    #    being refined: employee_info and project carry Department_ID, so on
    #    those "show me it" can only sensibly mean the IT department, while on
    #    a table with no department column there is nothing for it to mean.
    _real_cols = table_columns(ctx["table"])
    _has_dept = "department_name" in _real_cols or "department_id" in _real_cols
    mentions_department_word = "department" in tokens or "dept" in tokens

    def _drop_filter(predicate):
        kept = []
        for c in ctx["where"]:
            if predicate(c):
                continue
            kept.append(c)
        ctx["where"] = kept

    def _is_department_condition(condition):
        # "department_id = ..." plus the lifted-subquery placeholder, which
        # stands in for exactly that condition.
        return (
            condition.lower().startswith("department")
            or DEPARTMENT_SUBQUERY_TOKEN_RE.fullmatch(condition.strip()) is not None
        )

    # department - a name on the department table, an id lookup on the tables
    # that only store one
    found_departments = [
        w for w in tokens
        if w in DEPARTMENTS
        and not (w == "it" and not (mentions_department_word or _has_dept))
    ]
    if found_departments and (
        "department_name" in _real_cols or "department_id" in _real_cols
    ):
        _drop_filter(_is_department_condition)
        _values = [(department_display(w), False) for w in found_departments]
        if "department_name" in _real_cols:
            ctx["where"].append(
                "department_name = " + " OR ".join(f"'{v}'" for v, _ in _values)
            )
        else:
            ctx["where"].append(build_department_id_condition(_values, len(_values) > 1))
        applied.append(f"filtered department to {', '.join(v for v, _ in _values)}")

    # "city" is just another word for Address in this schema
    found_cities = [w for w in tokens if w in CITIES]
    if found_cities and "address" in _real_cols:
        _drop_filter(lambda c: c.lower().startswith("address"))
        _values = [city_display(w) for w in found_cities]
        if len(_values) == 1:
            ctx["where"].append(f"address = '{_values[0]}'")
        else:
            joined = ", ".join(f"'{v}'" for v in _values)
            ctx["where"].append(f"address IN ({joined})")
        applied.append(f"filtered address to {', '.join(_values)}")

    # exam / result fixed vocabularies (marks.Exam, marks.Result,
    # performance.Result) - same words the main parser recognises.
    # CATEGORICAL_VALUE_COLUMN maps the spoken VALUE to the column it lives
    # in ("pass" -> "result"), so the words are grouped by the column they
    # resolve to, not iterated as if the key were a column name.
    _value_hits = {}
    for w in tokens:
        col = CATEGORICAL_VALUE_COLUMN.get(w)
        if col and col in _real_cols:
            _value_hits.setdefault(col, []).append(w)

    for col, words in _value_hits.items():
        # Pass/Fail belong to marks.Result while Good/Excellent/Average belong
        # to performance.Result. Both columns are called "result", so the
        # value is checked against what THIS table's column actually holds -
        # otherwise "only show pass" on performance builds a filter that can
        # never match and quietly returns nothing.
        stored = COLUMN_VALUES.get(ctx["table"], {}).get(col)
        if stored is not None:
            _lower_stored = {s.lower(): s for s in stored}
            _usable = []
            for w in words:
                _display = CATEGORICAL_VALUE_DISPLAY.get(w, w)
                if _display.lower() in _lower_stored or w.lower() in _lower_stored:
                    _usable.append(w)
            if not _usable:
                continue
            words = _usable
        _drop_filter(lambda c, _c=col: c.lower().startswith(_c + " "))
        _seen = []
        for w in words:
            _v = CATEGORICAL_VALUE_DISPLAY.get(w, w)
            if _v not in _seen:
                _seen.append(_v)
        if len(_seen) == 1:
            ctx["where"].append(f"{col} = '{_seen[0]}'")
        else:
            joined = ", ".join(f"'{v}'" for v in _seen)
            ctx["where"].append(f"{col} IN ({joined})")
        applied.append(f"filtered {col} to {', '.join(_seen)}")

    # 6. Limit / top N
    # "2" in "more than 2 students" is a HAVING threshold, not a row limit -
    # so the "<digit> <table>" heuristic is skipped whenever the feedback is
    # clearly a group-size filter (a HAVING-shaped request). Explicit
    # top/limit/first words still apply in that case.
    having_shaped_feedback = bool(
        ctx["group_by"]
        and any(w in tokens for w in HAVING_SCOPE_WORDS)
        and (any(w in tokens for w in (HAVING_GTE_WORDS | HAVING_LTE_WORDS))
             or "AT_LEAST" in tokens or "AT_MOST" in tokens)
    )

    limit_val = None
    limit_by_table_word = False
    for i, w in enumerate(tokens):
        if w.isdigit():
            limit_val = w
            # "show 3 employees" - a bare number right before a table name
            # is a row-count limit, on top of the explicit top/limit/first
            # words already handled below
            if i + 1 < len(tokens) and tokens[i + 1] in TABLE_MAP:
                limit_by_table_word = True
                break
    if limit_val and (
        any(t in tokens for t in LIMIT_WORDS)
        or (limit_by_table_word and not having_shaped_feedback)
    ):
        ctx["limit"] = limit_val
        applied.append(f"limit set to {limit_val}")

    if not applied:
        raise RefinementError(
            "Couldn't confidently tell what to change from that feedback. "
            "Try something specific, e.g. 'only show name and marks', "
            "'sort by budget descending', 'show only employees from "
            "Bengaluru', 'subjects with more than 2 rows', or "
            "'remove the department filter'."
        )

    return ctx, applied