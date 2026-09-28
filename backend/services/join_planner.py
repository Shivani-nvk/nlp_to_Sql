"""
Multi-table join planning for the rule-based engine.

nlp_to_sql.py grew its join support one table at a time, which is why a
two-table question works and almost nothing else does:

  * "show student names along with their marks" joined the tables but
    projected only student_name - the marks column the user actually asked
    for was silently dropped.
  * "show project names along with the employees rating them" names three
    tables, and the engine could only hold two, so it either dropped the
    relationship or escalated to the LLM.
  * "show employees with their department names" mentioned no join trigger
    word at all, so no join was built and department_name was lost.

This module replaces that with an actual planner. The schema is two
disconnected stars of real foreign keys, and none of it needs to be
hand-maintained:

    academic   marks -> student_info -> course
               marks -> subject     -> course
    corporate  employee_info -> department
               project     -> department
               performance -> employee_info, project

Given the tables a question names, it finds the minimal set of ON-clauses
that connects them into ONE tree, in an order that is valid for the
requested join type, and projects every requested column from whichever
table owns it.

Everything is derived from the live schema: a column named `<x>_id` is
treated as a foreign key onto whichever table has `<x>_id` as its primary
key. A table created through the admin panel therefore joins correctly the
moment it exists, with no edit here.
"""

import re

from services.schema_service import get_schema, get_primary_keys

# Tables the planner must never touch, whatever the question says.
EXCLUDED_TABLES = {"app_users"}

# A join across these two groups is not expressible with ON-clauses at all -
# there is no key connecting an academic row to a corporate row. Reported so
# the caller can escalate instead of emitting a Cartesian product.
ACADEMIC_TABLES = {"student_info", "course", "subject", "marks"}
CORPORATE_TABLES = {"employee_info", "department", "project", "performance"}

_graph_cache = None
_graph_fingerprint = None


def _schema_fingerprint():
    """Cheap identity for the current schema, so the graph is rebuilt only
    when a table is actually added, dropped or altered."""
    try:
        schema = get_schema()
        pks = get_primary_keys()
    except Exception:
        return None
    return (
        tuple(sorted((t, tuple(sorted(c.lower() for c in cols)))
                     for t, cols in schema.items())),
        tuple(sorted(pks.items())),
    )


def build_relationship_graph():
    """
    Returns {table: {neighbour: on_clause}} for every real foreign key in the
    current database, plus the reverse direction, so a question can be
    answered from either end ("students and their marks" / "marks and the
    students who scored them").

    An edge exists where table T holds a column C and some OTHER table U has
    C as its primary key. That is the standard single-column-FK shape and it
    is what every table in this schema uses. Where a pair also appears in
    nlp_to_sql.JOIN_KEY_MAP, that hand-written clause wins, because it
    carries the real column casing and was chosen deliberately.
    """
    global _graph_cache, _graph_fingerprint

    fingerprint = _schema_fingerprint()
    if fingerprint is not None and fingerprint == _graph_fingerprint and _graph_cache is not None:
        return _graph_cache

    graph = {}

    try:
        schema = get_schema()
        pks = {t: c.lower() for t, c in get_primary_keys().items()}
    except Exception:
        schema, pks = {}, {}

    if not schema:
        # Schema unreachable: fall back to the hand-written key map so the
        # planner still works (and still refuses disconnected pairs) rather
        # than reporting everything as unjoinable.
        try:
            from services.nlp_to_sql import JOIN_KEY_MAP  # lazy: avoids a cycle
        except Exception:
            JOIN_KEY_MAP = {}
        for (left, right), clause in JOIN_KEY_MAP.items():
            if left in EXCLUDED_TABLES or right in EXCLUDED_TABLES:
                continue
            graph.setdefault(left, {})[right] = clause
            graph.setdefault(right, {})[left] = clause
        _graph_cache, _graph_fingerprint = graph, None
        return graph

    # owner_of[lowercased pk column] = table that declares it
    owner_of = {pk: table for table, pk in pks.items()}

    for table, cols in schema.items():
        if table in EXCLUDED_TABLES:
            continue
        for col in cols:
            low = col.lower()
            target = owner_of.get(low)
            # A table joined to itself on its own PK is not a relationship.
            if not target or target == table or target in EXCLUDED_TABLES:
                continue
            # Guard against a self-referential-looking coincidence such as
            # performance.Employee_ID, which is a genuine FK to
            # employee_info.Employee_ID, being read as a self-join.
            clause = f"{table}.{col} = {target}.{_real_col(schema, target, low)}"
            graph.setdefault(table, {})[target] = clause
            graph.setdefault(target, {})[table] = clause

    # Hand-written clauses take precedence: they encode intent (and casing)
    # that the mechanical rule cannot know about.
    try:
        from services.nlp_to_sql import JOIN_KEY_MAP  # lazy: avoids a cycle
        for (left, right), clause in JOIN_KEY_MAP.items():
            if left in EXCLUDED_TABLES or right in EXCLUDED_TABLES:
                continue
            graph.setdefault(left, {})[right] = clause
            graph.setdefault(right, {})[left] = clause
    except Exception:
        pass

    _graph_cache, _graph_fingerprint = graph, fingerprint
    return graph


def _real_col(schema, table, lowered):
    for col in schema.get(table, {}):
        if col.lower() == lowered:
            return col
    return lowered


def invalidate_graph_cache():
    global _graph_cache, _graph_fingerprint
    _graph_cache = None
    _graph_fingerprint = None


def connect_reason(left, right):
    """
    Human-readable reason two tables can't be joined, or None if they can.
    Used to fill ESCALATION_REASONS so the hybrid router hands the question
    to the agentic layer rather than the rules pretending it is answerable.
    """
    if left == right:
        return None
    graph = build_relationship_graph()
    if right in graph.get(left, {}):
        return None

    left_academic = left in ACADEMIC_TABLES
    right_academic = right in ACADEMIC_TABLES
    if left_academic != right_academic and (left_academic or right_academic):
        return (
            f"'{left}' and '{right}' belong to unrelated parts of the schema "
            f"(academic vs corporate) and share no key, so no JOIN relates them"
        )
    return f"no foreign key relates '{left}' and '{right}'"


def plan_join_chain(driving_table, other_tables, join_type="INNER JOIN"):
    """
    Builds an ordered list of (table, on_clause) steps that attaches every
    table in `other_tables` to `driving_table`.

    Returns (steps, missing) where `steps` is the ordered chain and `missing`
    is the list of tables that could not be connected (empty on success).

    The chain is a tree, not a graph: each new table attaches to exactly one
    table already in the chain, so N tables always cost N-1 ON-clauses and
    the result is never a spurious multi-hop match. Tables are attached in
    BFS order from the driving table, which keeps the chain short and puts
    the tables closest to the driving table first - the order a LEFT JOIN
    needs, since the nullable side has to come after everything it depends
    on.
    """
    graph = build_relationship_graph()

    chain = [driving_table]
    steps = []
    missing = []
    pending = [t for t in other_tables if t and t != driving_table]

    # Deduplicate while keeping the order the question mentioned them in.
    seen = {driving_table}
    pending = [t for t in pending if not (t in seen or seen.add(t))]

    while pending:
        # Attach whichever pending table is reachable from something already
        # in the chain. When several are equally attachable, a fact table goes
        # first: "the project name, the department it belongs to and the
        # employees working on it" can reach both department and performance
        # straight from project, and putting performance on the chain first is
        # what lets the employees attach to the table that records who worked
        # on what, instead of to the department they merely share with it.
        attached = None
        for candidate in pending:
            parents = [
                (existing, graph[existing][candidate])
                for existing in chain
                if candidate in graph.get(existing, {})
            ]
            if not parents:
                continue
            if attached is None or _is_fact_table(candidate):
                attached = (candidate,) + _preferred_parent(parents)
            if _is_fact_table(candidate):
                break

        if not attached:
            missing.extend(pending)
            break

        candidate, parent, clause = attached
        steps.append((candidate, clause))
        chain.append(candidate)
        pending.remove(candidate)

    return steps, missing


def _is_fact_table(table):
    """
    True for a table with no primary key. Every row of such a table records one
    event about one other row, so a key out of it points at a single parent.
    A table with a primary key is a dimension, and its key is shared by many
    children - routing a relationship through one of those pairs entities that
    merely share a category.
    """
    from services.nlp_to_sql import get_primary_keys  # lazy: avoids a cycle
    return not (get_primary_keys() or {}).get(table)


def _preferred_parent(parents):
    """
    Chooses which already-attached table a new table should hang off when more
    than one of them holds a key for it.

    "the project name, the department it belongs to and the employees working
    on it" reaches employee_info through BOTH department and performance, and
    the two answers are not the same: via department it pairs every employee of
    the project's department with every rating row, via performance it pairs
    each rating with the employee who gave it. Only the second is what was
    asked.

    The tie is broken on the shape of the table. A table with no primary key is
    a fact table - every one of its rows records one event about one other row
    - so a key out of it points at exactly one parent. A table with a primary
    key is a dimension, and its key is shared by many children, so routing a
    relationship through it pairs entities that merely share a category. Fact
    tables win; everything else falls back to the order the chain was built in.
    """
    for parent, clause in parents:
        if _is_fact_table(parent):
            return parent, clause

    return parents[0]


def find_bridges(driving_table, other_tables):
    """
    Returns the extra tables needed to connect `other_tables` to
    `driving_table`, for pairs that share no direct key.

    "list employees and their projects" names employee_info and project,
    which are two hops apart in the corporate star: the honest answer routes
    through performance, which is where the actual relationship lives.
    Without this the planner would report the pair as unjoinable and escalate
    a question the schema can answer perfectly well.

    Only the shortest bridge is taken, and it is returned in the order it
    should appear in the chain.
    """
    graph = build_relationship_graph()
    extras = []
    named = {t for t in other_tables if t and t != driving_table}

    for target in other_tables:
        if not target or target == driving_table:
            continue
        if target in graph.get(driving_table, {}):
            continue

        # Breadth-first for the shortest path, but only through tables the
        # question actually named. "employee names, project names and ratings"
        # names performance (via "ratings"), and the real route is
        # employee_info -> performance -> project. Left unrestricted, the
        # search is just as happy to walk employee_info -> department ->
        # project, which joins two tables nobody asked about and pairs every
        # employee with every project in their department.
        path = _shortest_path(graph, driving_table, target, named | {driving_table})
        if not path:
            path = _shortest_path(graph, driving_table, target, None)

        if not path:
            continue
        for middle in path[1:-1]:
            if middle not in extras and middle not in other_tables:
                extras.append(middle)

    return extras


def _shortest_path(graph, start, target, allowed=None):
    """
    Shortest key-path from `start` to `target`, or None.

    When `allowed` is given the search never steps outside it, which is how a
    bridge prefers tables the question already named over any other table at
    the same distance. When several paths of that same shortest length survive,
    the one routed through a fact table wins, for the same reason
    `_preferred_parent` does: performance says an employee worked on a project,
    department only says they are in the same building.
    """
    frontier = [[start]]
    seen = {start}
    while frontier:
        nxt = []
        winners = []
        for path_so_far in frontier:
            for neighbour in graph.get(path_so_far[-1], {}):
                if neighbour in seen:
                    continue
                if allowed is not None and neighbour not in allowed:
                    continue
                extended = path_so_far + [neighbour]
                if neighbour == target:
                    winners.append(extended)
                    continue
                seen.add(neighbour)
                nxt.append(extended)
        if winners:
            for path in winners:
                if any(_is_fact_table(m) for m in path[1:-1]):
                    return path
            return winners[0]
        frontier = nxt
    return None



def chain_columns(chain):
    """Every column name that exists anywhere in the chain, lowercased."""
    from services.nlp_to_sql import table_columns  # lazy: avoids a cycle
    names = set()
    for t in chain:
        names.update(table_columns(t))
    return names


def column_owners(columns, candidate_tables):
    """
    Maps each requested column onto the tables in `candidate_tables` that
    actually have it. A column owned by exactly one table is unambiguous; one
    owned by several (Student_ID on both marks and student_info) has to be
    qualified as table.column in the projection so the SQL stays valid.
    """
    owners = {}
    for col in columns:
        if not col or col == "*":
            continue
        low = col.lower()
        matched = [t for t in candidate_tables if _has_column(t, low)]
        owners[col] = matched
    return owners


def _has_column(table, lowered):
    """
    True when `table` has a column the question's word could mean. The word is
    also tried in its singular form, because the maps are keyed by singular
    column names while a sentence says "results". Missing that plural turned
    "show excellent performance results" into a question about marks.
    """
    try:
        from services.nlp_to_sql import table_columns  # lazy: avoids a cycle
        columns = table_columns(table)
    except Exception:
        return False
    if lowered in columns:
        return True
    for variant in _singular_variants(lowered):
        if variant in columns:
            return True
    return False


def _singular_variants(word):
    """The obvious singular spellings of a plural word, cheapest guess first."""
    if word.endswith("ies") and len(word) > 4:
        return (word[:-3] + "y", word[:-3] + "ie")
    if word.endswith("ses"):
        return (word[:-2], word[:-1])
    if word.endswith("es") and len(word) > 3:
        return (word[:-2], word[:-1])
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return (word[:-1],)
    return ()


def qualify(columns, owners, driving_table, chain, projection=False):
    """
    Renders a projection list, adding the table prefix wherever a column is
    ambiguous or lives on a joined table. Unambiguous columns that belong to
    the driving table are left bare, so simple questions keep the readable
    SQL they had before.

    `owners` may be omitted (or given per-column) - ownership is then worked
    out for the columns at hand, which is what clause rewriting needs since it
    has no projection list to hand.

    `projection` marks a SELECT list, which is the one place a bare name can be
    read as a table rather than a column: MySQL rejects `SELECT marks FROM marks
    JOIN student_info` because `marks` is both a column and a joined table. In
    an expression (`AVG(marks)`) the same name can only ever be the column, so
    the prefix is left off there and the SQL stays readable.
    """
    resolved = {}
    parts = []
    for col in columns:
        if col == "*":
            parts.append("*")
            continue
        if owners is None:
            matched = column_owners([col], chain).get(col) or []
        else:
            matched = owners.get(col) or []
        if len(matched) > 1:
            # Ambiguous: pick the table that owns it and prefix it.
            owner = driving_table if driving_table in matched else matched[0]
            parts.append(f"{owner}.{col}")
        elif len(matched) == 1 and matched[0] != driving_table:
            parts.append(f"{matched[0]}.{col}")
        elif len(matched) == 1 and projection and col in chain:
            # A joined table shares this column's name, so a bare `marks` in a
            # SELECT list is the column and the table at once and MySQL
            # rejects it.
            parts.append(f"{matched[0]}.{col}")
        else:
            parts.append(col)
    return parts


def fanout_risk(driving_table, chain):
    """
    True when a joined table is on the "many" side of a relationship to the
    driving table, so one driving row can match several joined rows.

    That matters for counting: "how many students have marks" run as
    COUNT(*) over a join reports one row per mark, not per student, and
    answers a question nobody asked. The caller switches those to
    COUNT(DISTINCT driving_table.pk).
    """
    graph = build_relationship_graph()
    neighbours = graph.get(driving_table, {})
    for other in chain[1:]:
        clause = neighbours.get(other, "")
        # "<child>.<FK> = <parent>.<PK>" - the child is the many side.
        m = re.match(r"^\s*([A-Za-z_]\w*)\.", clause)
        if m and m.group(1) == other:
            return True
    return False


# ---------------- question -> set of tables ----------------

# Words that mean "and also show me the related rows", i.e. they license a
# join even though no table name is repeated ("show employees WITH their
# department names", "list projects AND the employees working on them").
JOIN_PHRASE_WORDS = {
    "along", "alongside", "together", "with", "and", "joined", "combined",
    "plus", "versus", "vs", "against", "including", "as", "well",
    "per", "for", "each", "every", "of",
}

# Pronouns that stand for "the row on the other side of the relationship".
# "students and their marks" - the marks are marks rows, not a column on
# student_info, so a pronoun after a table mention is a real join signal.
RELATION_PRONOUNS = {"their", "theirs", "them", "its", "it"}

# Verbs describing a relationship rather than naming a table.
#
# "belongs" is deliberately absent. It reads as course in "subjects belonging
# to a course" and as department in "the department it belongs to", and a
# single guess gets one of those wrong - the wrong table then drags in a
# whole chain of tables the sentence never mentioned. Wherever the question
# names the table it belongs to ("a course", "the department"), the table
# word already covers it.
RELATION_VERB_HINT = {
    "taking": "subject", "takes": "subject", "take": "subject", "took": "subject",
    "leading": "subject", "leads": "subject", "led": "subject",
    "rated": "performance", "rates": "performance", "rate": "performance",
    "scored": "marks", "score": "marks", "scoring": "marks",
    "studying": "course", "studies": "course", "study": "course",
    "enrolled": "course", "enrols": "course",
    "assigned": "performance", "assigned_to": "performance",
}

# Two-word verbs, where the preposition decides what the relationship is:
# an employee "working on" a project is a performance row, the same employee
# "working in" a department is a department row.
RELATION_PHRASE_HINT = {
    ("working", "on"): "performance",
    ("works", "on"): "performance",
    ("work", "on"): "performance",
    ("working", "in"): "department",
    ("works", "in"): "department",
    ("work", "in"): "department",
    ("assigned", "to"): "performance",
    ("belongs", "to"): None,
    ("belonging", "to"): None,
    ("belong", "to"): None,
}

# Verbs that name a MEASURE rather than a table. Used to fix a comparison that
# landed on a key column - "students who scored above 80" is about marks, not
# about which student_id happens to be large.
MEASURE_HINT = {
    "scored": ("marks", "marks"),
    "scoring": ("marks", "marks"),
    "score": ("marks", "marks"),
    "scores": ("marks", "marks"),
    "earned": ("marks", "marks"),
    "earning": ("marks", "marks"),
    "achieved": ("marks", "marks"),
    "obtaining": ("marks", "marks"),
    "rated": ("performance", "rating"),
    "rating": ("performance", "rating"),
    "rated_in": ("performance", "rating"),
    "spent": ("project", "budget"),
    "spending": ("project", "budget"),
    "earns": ("project", "budget"),
}


def resolve_question_tables(tokens, driving_table, requested_columns=None):
    """
    Works out every table a question is really asking about, in the order it
    mentions them.

    Three independent signals, because no single one is enough:

      1. a table word            - "show students and subjects"
      2. a column word           - "project names along with the employees
                                    rating them" names project, performance
                                    (via "rating") and employee_info
      3. a pronoun after a table - "students and their marks"

    A signal only counts when it names a table that is actually CONNECTED to
    something already in the set. That is what stops "show employees and the
    weather" from trying to join in a table that does not exist, and what
    keeps a disconnected academic/corporate pair from being planned at all.
    """
    from services.nlp_to_sql import (  # lazy: avoids an import cycle
        COLUMN_MAP, JOIN_TABLE_HINTS, TABLE_MAP,
    )

    graph = build_relationship_graph()

    found = []
    for token in tokens:
        candidate = TABLE_MAP.get(token) or JOIN_TABLE_HINTS.get(token)
        if not candidate or candidate in EXCLUDED_TABLES:
            continue
        # Some column words double as table hints - "result" points at marks,
        # because that is where pass/fail lives for the academic questions.
        # When the question's own table has that column too, it is talking
        # about the one it already named, and following the hint would drag in
        # an unrelated table ("performance records with an excellent result").
        if candidate != driving_table and _has_column(driving_table, token):
            continue
        if candidate not in found:
            found.append(candidate)

    # A column word that no table mentioned outright still pulls its own
    # table in - this is how "the employees rating them" reaches performance
    # when the question never says the word "performance".
    for col in (requested_columns or []):
        owners = [
            t for t in _all_tables()
            if t not in EXCLUDED_TABLES and _has_column(t, col.lower())
        ]
        # A column the question's own table already has adds nothing. Without
        # this, "performance records with an excellent result" pulls in marks
        # just because both tables have a `result` column - the two live in
        # unconnected halves of the schema, so that escalated a question that
        # never asked for a join.
        if driving_table in owners:
            continue
        # Prefer a table that is connected to what we already have; that is
        # the one the sentence means, as opposed to every table that happens
        # to share the column name.
        for owner in owners:
            if owner in found:
                break
        else:
            connected = [
                o for o in owners
                if any(o in graph.get(f, {}) for f in found)
            ]
            if connected and connected[0] not in found:
                found.append(connected[0])

    for i, token in enumerate(tokens):
        phrase = RELATION_PHRASE_HINT.get(
            (token, tokens[i + 1]) if i + 1 < len(tokens) else (token, None)
        )
        hint = phrase or RELATION_VERB_HINT.get(token)
        if hint and hint not in found and hint not in EXCLUDED_TABLES:
            found.append(hint)

    if driving_table in found:
        found.remove(driving_table)
    return [driving_table] + found


def _all_tables():
    try:
        return [t for t in get_schema() if t not in EXCLUDED_TABLES]
    except Exception:
        return []


def has_join_intent(tokens):
    """
    True when the sentence reads like a join rather than a single-table
    query. Deliberately conservative: a bare mention of a second table name
    is not enough, since "show students and their names" is one table, and
    "employees and students" is a UNION.
    """
    for token in tokens:
        if token in ("along", "alongside", "together", "joined", "combined",
                     "with", "versus", "including", "plus"):
            return True
        if token in RELATION_PRONOUNS and token != "it":
            return True
        if token in RELATION_VERB_HINT:
            return True
    return False


# ---------------- SQL assembly ----------------

# A quoted SQL string literal, used to skip over literals while qualifying
# column references - 'Pass' must not be rewritten into 'marks.Pass'.
_LITERAL_RE = re.compile(r"'(?:\\.|[^'\\])*'")


def ambiguous_columns(chain):
    """
    Column names present on more than one table in the chain. Only these need
    a table prefix; a column that exists on exactly one table resolves on
    its own, which keeps the emitted SQL readable.
    """
    counts = {}
    for table in chain:
        try:
            from services.nlp_to_sql import table_columns  # lazy: avoids a cycle
            cols = table_columns(table)
        except Exception:
            continue
        for col in cols:
            counts[col] = counts.get(col, 0) + 1
    return {col for col, n in counts.items() if n > 1}


def qualify_clause(clause, chain):
    """
    Adds table prefixes to any bare column reference in a rendered SQL
    fragment that is ambiguous across the join.

    String literals are stepped over untouched, so a filter on
    `Result = 'Pass'` keeps its value intact while the column next to it
    becomes `marks.Result`.
    """
    if not clause:
        return clause

    ambiguous = ambiguous_columns(chain)
    if not ambiguous:
        return clause

    # Longest names first, so "course_id" is not partially rewritten by "id".
    names = sorted(ambiguous, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\w.])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w])",
        re.IGNORECASE,
    )

    # owner preference: the driving table wins a tie, so the prefix is stable
    owners = {}
    for table in chain:
        try:
            from services.nlp_to_sql import table_columns  # lazy: avoids a cycle
            cols = table_columns(table)
        except Exception:
            continue
        for col in cols:
            owners.setdefault(col.lower(), []).append(table)
    preferred = chain[0]

    out = []
    pos = 0
    for lit in _LITERAL_RE.finditer(clause):
        out.append(_qualify_fragment(clause[pos:lit.start()], pattern, owners, preferred))
        out.append(lit.group(0))          # literal, verbatim
        pos = lit.end()
    out.append(_qualify_fragment(clause[pos:], pattern, owners, preferred))
    return "".join(out)


def _qualify_fragment(fragment, pattern, owners, preferred):
    def repl(match):
        name = match.group(0)
        candidates = owners.get(name.lower(), [])
        if not candidates:
            return name
        owner = preferred if preferred in candidates else candidates[0]
        return f"{owner}.{name}"

    return pattern.sub(repl, fragment)


def qualify_clause(clause, chain):
    """
    Qualifies the ambiguous column references inside one already-rendered
    clause body ("a = b AND c > 5"), leaving the operators and literals
    alone.

    Parenthesised spans are passed through untouched: the engine uses
    subqueries for things like "employees in the IT department", and the
    subquery resolves its own column against its own table, so rewriting
    its identifiers against the outer chain breaks it.
    """
    # Brackets, and anything nested inside them, belong to a subquery that
    # resolves its own columns against its own tables, and that span is emitted
    # verbatim. Rewriting its identifiers against the outer chain silently
    # destroys the condition.
    #
    # The span is found by scanning characters, NOT by looking for a "(" token:
    # the renderer writes "= (SELECT department_id FROM department WHERE
    # department_name = 'IT')", so the opening bracket arrives glued to SELECT
    # and a token-level test never sees it. Depth then never rises, the
    # subquery is rewritten against the outer chain, and the inner
    # "department_id" becomes "employee_info.department_id" - which MySQL
    # reads as a reference to the outer row. The filter ends up comparing each
    # row's own department_id with itself, so it is true for every row and
    # "employees in the IT department" returns all ten employees.
    #
    # Splitting the text into outer runs and inner spans (rather than
    # re-joining tokens) keeps the surrounding whitespace and any function
    # call intact: "avg(marks) > 80" comes back out exactly as it went in.
    segments = []
    buf = []
    depth = 0
    for char in clause:
        if char == "(":
            if depth == 0:
                segments.append((False, "".join(buf)))
                buf = []
            depth += 1
            buf.append(char)
        elif char == ")" and depth > 0:
            buf.append(char)
            depth -= 1
            if depth == 0:
                segments.append((True, "".join(buf)))
                buf = []
        else:
            buf.append(char)
    # An unclosed "(" leaves the tail inside the subquery - still verbatim.
    segments.append((depth > 0, "".join(buf)))

    rendered = []
    for is_inner, text in segments:
        core = text.strip()
        if is_inner or not core:
            rendered.append(text)
            continue
        leading = text[:len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()):]
        rendered.append(leading + " ".join(qualify(core.split(), None, None, chain)) + trailing)
    return "".join(rendered)


COMPARISON_RE = re.compile(
    r"^\s*(?:WHERE|where)\s+((?:\w+\.)?)(\w+)(\s*(?:<=|>=|<>|!=|=|<|>)\s*)"
)


def is_key_column(table, column):
    """
    True for a primary/foreign key column - an id, or the table's own key.

    Only the "_id" suffix counts as the convention. The previous condition was
    `endswith("_id") or endswith("id") and != "id"`, which `and` binding
    tighter than `or` collapses to a plain "ends with id" - so any ordinary
    word of that shape read as a key. It changed nothing on the current
    schema, where every `*id` column really is a key, so this is hardening
    rather than a fix, and narrow on purpose: a key spelled any other way is
    still caught by the primary-key lookup below.
    """
    from services.nlp_to_sql import get_primary_keys  # lazy: avoids a cycle

    lowered = (column or "").lower()
    if lowered in ("id", "ids"):
        return True
    if lowered.endswith("_id"):
        return True
    # get_primary_keys() maps table -> the key column NAME, so this is one
    # string to compare, not something to iterate. Iterating it built a set of
    # single characters, which matched no column but a one-letter one.
    pk = (get_primary_keys() or {}).get(table)
    return bool(pk) and lowered == str(pk).lower()


def retarget_comparison(where_clause, chain, driving_table, tokens):
    """
    Re-points a comparison that landed on a key column at the measure the
    sentence is actually about.

    "students who scored above 80" - the engine picks the numeric column
    nearest the comparison word, and the nearest one is student_info's
    student_id, so it filters `student_id > 80` and returns nothing. Nobody
    asks which students have an id above 80; "scored" names the measure, and
    the measure lives on marks, one join away. The chain is already known here,
    so the fix is to look the word up rather than to guess from position.
    """
    if not where_clause:
        return where_clause

    match = COMPARISON_RE.match(where_clause)
    if not match:
        return where_clause

    prefix, column, operator = match.group(1), match.group(2), match.group(3)
    if not is_key_column(driving_table, column):
        return where_clause

    for token in tokens:
        measure = MEASURE_HINT.get(token)
        if not measure:
            continue
        measure_table, measure_column = measure
        if measure_table in chain and measure_column in table_columns_of(measure_table):
            return where_clause[:match.start(2)] + measure_column + operator \
                + where_clause[match.end(3):]

    return where_clause


def table_columns_of(table):
    from services.nlp_to_sql import table_columns  # lazy: avoids a cycle
    return table_columns(table)


def render_tail(where_clause, group_by_clause, having_clause, order_by_clause,
                limit_clause, chain, rank_column=None, direction=None):
    """
    Re-assembles the WHERE / GROUP BY / HAVING / ORDER BY / LIMIT block for a
    planned join, qualifying every ambiguous column reference on the way.

    The clauses arrive pre-rendered from the main engine as a leading keyword
    plus a body (" WHERE result = 'Pass'"), so the body is what gets
    rewritten and the keyword is put back verbatim.

    `rank_column`/`direction` replace the ORDER BY entirely - used when the
    sort target is a joined column the engine only knew by its bare name.
    """
    out = []

    for rendered in (where_clause, group_by_clause, having_clause):
        if not rendered:
            continue
        head, body = rendered.split(" ", 1)
        out.append(f"{head} {qualify_clause(body, chain)}")

    if rank_column:
        out.append(f"ORDER BY {rank_column} {direction or 'ASC'}")
    elif order_by_clause:
        head, body = order_by_clause.split(" ", 1)
        out.append(f"{head} {qualify_clause(body, chain)}")

    if limit_clause:
        out.append(limit_clause.strip())

    return "".join(f"\n{c}" for c in out)


def render_from_chain(driving_table, steps, join_type):
    """
    Renders `FROM <driving> <JOIN ... ON ...> <JOIN ... ON ...>`.

    A chain of more than one hop is only expressible for join types that are
    order-independent (INNER, CROSS). For an outer join the null-preserving
    table has to be the last one attached, so a longer chain is rendered
    INNER up to the final hop and the requested type only on that last
    attachment - otherwise rows reachable only through the middle table would
    be wrongly preserved.
    """
    if not steps:
        return f"FROM {driving_table}"

    if join_type == "CROSS JOIN":
        return "FROM " + driving_table + "".join(
            f"\nCROSS JOIN {t}" for t, _ in steps
        )

    parts = [f"FROM {driving_table}"]
    last = len(steps) - 1
    for idx, (table, clause) in enumerate(steps):
        kind = join_type if (idx == last or join_type in ("INNER JOIN",)) else "INNER JOIN"
        parts.append(f"{kind} {table} ON {clause}")
    return "\n".join(parts)


