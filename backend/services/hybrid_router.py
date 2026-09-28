"""
Hybrid NLP-to-SQL query router.

Flow:
1. Rule-based engine is ALWAYS tried first.
2. If the rule-based engine confidently produces valid SQL that passes
   validation and executes successfully -> return result (source: rule_based).
3. If the rule-based engine fails (no keywords, invalid SQL, or a DB
   execution error) -> the agentic engine is activated as a fallback.
4. The agentic engine generates SQL against the LIVE schema, which is
   validated and executed.
5. If agentic SQL fails at runtime, a bounded self-healing loop (max 3
   attempts) sends the error + SQL + schema back to the agent to correct it.
6. Always returns a structured result with a source + safe activity trace.
"""

from db import get_db_connection
from services.nlp_to_sql import convert_to_sql, has_recognizable_keywords
from services.schema_service import get_schema
from services.llm_fallback import llm_fallback_convert, EMPTY_RESULT_HINT
from services.sql_validator import validate_sql, execute_sql_safe

try:
    from nltk import word_tokenize
except Exception:  # pragma: no cover - never reached in a normal install
    word_tokenize = lambda s: s.lower().split()

MAX_REPAIR_ATTEMPTS = 3

# Source identifiers. Response uses snake_case: rule_based / agentic /
# agentic_self_healed.
SOURCE_RULE_BASED = "rule_based"
SOURCE_AGENTIC = "agentic"
SOURCE_AGENTIC_SELF_HEALED = "agentic_self_healed"
SOURCE_FAILED = "failed"

# Questions that match these buckets go STRAIGHT to the agentic path - the
# rule-based engine's documented weaknesses (three-table chains, EXISTS /
# NOT EXISTS, ANY/ALL comparisons, named-row subqueries, grouped-vs-overall
# aggregates, CASE/labeling, UNION of differently-shaped tables, cross-table
# counts). The alternative history is the PRIMARY engine for these buckets,
# exactly as the task requires, instead of letting the rule engine produce
# wrong SQL. Every word here is matched against the LIVE schema - there is no
# deadline/lead/salary/manager column in it, so those words are absent and
# their questions are caught as unsupported concepts instead.
_PROJECT_WORDS = {"project", "projects", "project_name", "budget", "start_year"}
_EMPLOYEE_WORDS = {"employee", "employees", "emp", "staff", "personnel",
                   "department", "dept", "departments", "rating", "performance",
                   "address", "phone_no"}
# performance is the only bridge between employee_info and project, so any
# question that needs both ends plus the bridge ("project names along with the
# employees rating them") is a three-table join this engine can't build.
_BRIDGE_WORDS = {"performance", "rating", "ratings"}
_COMPARISON_WORDS = {"greater", "more", "higher", "above", "exceed",
                     "exceeds", "exceeding", "less", "lesser", "lower", "below",
                     "under", "than"}
_ANY_ALL_WORDS = {"any", "all", "every"}
_LABEL_WORDS = {"label", "categorize", "categorise"}
_RELATION_VERBS = {"taking", "takes", "take", "took", "assigned", "belong",
                   "belongs", "live", "lives", "rating", "rated", "ratings"}
# "the number of subjects per course", "departments with more than 2
# employees" - a COUNT of one table grouped by a column of another needs a
# derived table, which the single-table rule engine has no way to express.
_COUNT_WORDS = {"number", "count", "having"}
# marks is a first-class table in the live schema (Student_ID, Subject_ID,
# Exam, Marks, Result) with real foreign keys to student_info and subject,
# so single-hop marks questions ("marks above 60", "average marks per
# subject") and two-table joins ("students with marks above 80", "student
# name along with their marks") are solid rule-engine territory. Only the
# 3-way chain (marks + student + subject/course together) or a named
# person's marks still out-gun the rule engine's single-JOIN builder - those
# are a 2-or-3-table join the rule engine can't express reliably.
_RESULTS_WORDS = {"result", "results", "marks", "mark", "score", "scores", "grade", "grades"}
_EXAM_COURSE_WORDS = {"exam", "exams", "test", "tests", "course", "courses",
                      "subject", "subjects"}
_STUDENT_CONTEXT_WORDS = {"student", "students"}


def _is_rule_engine_weak(tokens, original_tokens=None):
    """True when the question belongs to a bucket the rule-based engine is
    documented to be weak at - those go to the agentic path as PRIMARY.

    `tokens` must already be lowercased. `original_tokens` (optional) keeps
    the original case so capitalized person names can be detected. Keep this
    conservative: strong rule-based territory (plain selects, filters,
    aggregates, group-by/having, null checks, student<->subject joins) must
    stay on the rule engine.
    """
    tok_set = set(tokens)
    name_tokens = original_tokens or tokens

    # CASE / labeling ("label employees as High if rating above 4...")
    if tok_set & _LABEL_WORDS:
        return True

    # a COUNT of one table grouped by a column of another ("the number of
    # subjects per course") needs a derived table - the rule engine would
    # either drop the count or turn the number into a row LIMIT
    if (tok_set & _COUNT_WORDS) and (tok_set & (_PROJECT_WORDS | _EMPLOYEE_WORDS)):
        return True

    # marks/results tied to a student AND a course/exam context together
    # needs a 2-3 table join (marks -> student_info, marks -> subject,
    # subject -> course) that the rule engine's single-JOIN builder can't
    # express. A bare marks context, or marks joined to only ONE other
    # table, stays on the rule engine (it has real join keys for those).
    has_results = bool(tok_set & _RESULTS_WORDS)
    has_exam_course_context = bool(tok_set & _EXAM_COURSE_WORDS)
    has_student_context = bool(tok_set & _STUDENT_CONTEXT_WORDS)
    if has_results and has_student_context and has_exam_course_context:
        return True

    # a named person's marks/results ("Aarav's marks", "results obtained
    # by Kiara") - same reasoning, plus the name itself isn't resolvable
    # by the rule engine's single-table subquery logic once a join is
    # also required.
    if has_results and has_student_context and any(_is_proper(t) for t in name_tokens):
        return True

    # project <-> employee only meet through performance, so naming both ends
    # AND the bridge is a three-table join. (A plain "projects in IT" or
    # "employees in marketing" is single-table and stays on the rule engine.)
    if (tok_set & _PROJECT_WORDS) and (tok_set & _EMPLOYEE_WORDS) and (tok_set & _BRIDGE_WORDS):
        return True

    # a relational verb on top of a two-table question ("which project is
    # Ravi rating") - the rule engine's join trigger relies on
    # "along/with/joined", not verbs.
    if tok_set & _RELATION_VERBS and (tok_set & (_PROJECT_WORDS | _RESULTS_WORDS)):
        return True

    # EXISTS / NOT EXISTS phrasing: "at least one X", "not taking any subject",
    # "do not lead any project".
    if tok_set & {"at_least", "atleast"}:
        return True
    if "any" in tok_set and (tok_set & {"not", "without", "no"}):
        return True

    # ANY / ALL comparisons: a comparison word + any/all/every.
    if (tok_set & _ANY_ALL_WORDS) and (tok_set & _COMPARISON_WORDS):
        return True

    # grouped aggregate vs overall: "... greater than the OVERALL average"
    if "overall" in tokens:
        return True

    # UNION of differently-shaped tables ("show students and subjects together")
    if "together" in tok_set or "union" in tok_set:
        return True

    # named-row subquery: a comparison of one row's value against another
    # row's value ("budget greater than the budget of Cloud Vault") - the name
    # comes through as a capitalized word the rule engine can't map.
    for i, w in enumerate(tokens):
        if w not in ("than", "above", "below"):
            continue
        if any(_is_proper(t) for t in name_tokens[i + 1:]):
            return True

    return False


def _is_proper(tok):
    """A token that looks like a proper noun (first letter uppercase) counts
    as a person/place name that the rule engine has no mapping for."""
    return bool(tok) and tok[0].isupper() and not tok[0].isdigit()


def _should_prefer_agentic(question):
    """Decides whether this question belongs to a rule-engine-weak bucket
    that should go straight to the agentic path."""
    words = word_tokenize(question)
    lowered = [w.lower() for w in words]
    return _is_rule_engine_weak(lowered, original_tokens=words)


def _build_schema_context():
    """Returns the live schema (dict of table -> {column: type})."""
    return get_schema()


def _safe_schema_for_llm(schema):
    """Same schema as get_schema(), but never exposes the auth table."""
    if not schema:
        return {}
    return {t: cols for t, cols in schema.items() if t != "app_users"}


def _rule_based_sql(question):
    """
    Attempts rule-based generation.
    Returns (sql, recognized) where recognized=False means the engine had
    no recognizable keywords (its output is likely a meaningless default).
    """
    sql = convert_to_sql(question)
    recognized = has_recognizable_keywords(question)
    return sql, recognized


def _agentic_generate(question, schema, previous_sql=None, error=None, attempt=1):
    """
    Calls the LLM to generate SQL. When previous_sql + error are provided,
    this is a self-heal/repair call and the prompt asks for a correction.
    Returns a SQL string or None.
    """
    try:
        if attempt > 1 and previous_sql and error:
            repaired = llm_fallback_convert(question, schema, previous_sql=previous_sql, error=error)
            return repaired
        return llm_fallback_convert(question, schema)
    except Exception:
        return None


def _execute(query_conn, sql):
    return execute_sql_safe(query_conn, sql)


def run_hybrid_query(question, role="user"):
    """
    Runs the full hybrid pipeline for a user question.

    Returns a dict:
      {
        "source": "rule_based" | "agentic" | "agentic_self_healed" | "failed",
        "sql": <final sql used>,
        "result": <rows or []>,
        "repair_attempts": <int>,
        "trace": ["...", ...],
        "error": <str or None>,
      }
    """
    trace = []
    schema = _build_schema_context()

    # Rule-engine-weak buckets (JOIN-heavy, EXISTS, ANY/ALL, subqueries,
    # labeling, etc.) go the agentic path as PRIMARY - the rule engine is
    # documented to get these wrong, and it would refuse to route correctly.
    if _should_prefer_agentic(question):
        trace.append("Complex query bucket detected; agentic engine used as primary")
        trace.append("Agentic engine activated")
        return _agentic_flow(question, schema, trace, role=role)

    # ---------------- 1. RULE-BASED ENGINE (PRIMARY) ----------------
    trace.append("Rule-based engine engaged")

    rule_sql, recognized = _rule_based_sql(question)

    if recognized and rule_sql:
        # Rule-based produced something meaningful - validate it.
        ok, reason = validate_sql(rule_sql, role)
        if not ok:
            trace.append(f"Rule-based SQL failed validation: {reason}")
        else:
            trace.append("SQL generated")
            trace.append("SQL validation passed")

            conn = get_db_connection()
            try:
                result, err = _execute(conn, rule_sql)
                if err is None:
                    trace.append("Query executed successfully")
                    return {
                        "source": SOURCE_RULE_BASED,
                        "sql": rule_sql,
                        "result": result or [],
                        "repair_attempts": 0,
                        "trace": trace,
                        "error": None,
                    }
                trace.append(f"Rule-based query execution failed: {err}")
            finally:
                conn.close()
    else:
        trace.append("Rule-based engine could not resolve query")

    # ---------------- 2. AGENTIC ENGINE (FALLBACK + SELF-HEAL) ----------------
    trace.append("Agentic engine activated")
    return _agentic_flow(question, schema, trace, role=role)


def _agentic_flow(question, schema, trace, role="user", repair_attempts=0):
    """
    Runs the agentic engine: generate -> validate -> execute, with a
    bounded self-healing loop (max MAX_REPAIR_ATTEMPTS total attempts).
    Reused both for rule-engine-weak buckets (as PRIMARY) and as the
    fallback after the rule-based path fails.
    """
    llm_schema = _safe_schema_for_llm(schema)

    current_sql = None
    last_error = None

    # First attempt: agentic generation
    current_sql = _agentic_generate(question, llm_schema, attempt=1)
    if not current_sql:
        trace.append("Agentic generation failed or returned unusable SQL")
        return {
            "source": SOURCE_FAILED,
            "sql": None,
            "result": [],
            "repair_attempts": 0,
            "trace": trace,
            "error": "Could not generate SQL.",
        }

    attempt = 1
    while attempt <= MAX_REPAIR_ATTEMPTS:
        # Validate
        ok, reason = validate_sql(current_sql, role)
        if not ok:
            last_error = reason
            trace.append(f"Generated SQL failed validation: {reason}")
            if attempt == MAX_REPAIR_ATTEMPTS:
                break
            current_sql = _agentic_generate(
                question, llm_schema,
                previous_sql=current_sql, error=last_error, attempt=attempt + 1
            )
            repair_attempts += 1
            if current_sql:
                trace.append("SQL corrected by agentic engine")
            attempt += 1
            continue

        trace.append("SQL validation passed")

        # Execute
        conn = get_db_connection()
        try:
            result, err = _execute(conn, current_sql)
        finally:
            conn.close()

        if err is None:
            # A clean run that matched nothing is not automatically a right
            # answer. Valid SQL whose WHERE clause contains a literal that
            # exists in no row (Exam = 'final' when the only stored exams are
            # 'Internal 1' and 'Semester') raises no error, so the loop used
            # to treat it as success and the user saw "no records matched",
            # which reads as confirmation that the filters were correct. Give
            # the model one more attempt with the real values in front of it;
            # on the last attempt, accept the empty result rather than loop.
            if not result and attempt < MAX_REPAIR_ATTEMPTS:
                last_error = EMPTY_RESULT_HINT
                trace.append(
                    f"Attempt {attempt} matched 0 rows - a literal may not "
                    f"exist in the data; asking the agentic engine to re-check"
                )
                current_sql = _agentic_generate(
                    question, llm_schema,
                    previous_sql=current_sql, error=EMPTY_RESULT_HINT,
                    attempt=attempt + 1
                )
                repair_attempts += 1
                if current_sql:
                    trace.append("SQL corrected by agentic engine")
                else:
                    break
                attempt += 1
                continue

            if not result:
                trace.append(
                    "Query matched no rows and no better version could be "
                    "found; returning the empty result as-is"
                )

            trace.append("Query executed successfully")
            source = SOURCE_AGENTIC_SELF_HEALED if repair_attempts > 0 else SOURCE_AGENTIC
            if source == SOURCE_AGENTIC_SELF_HEALED:
                trace.append(f"Agentic engine corrected SQL after {repair_attempts} attempt(s)")
            return {
                "source": source,
                "sql": current_sql,
                "result": result or [],
                "repair_attempts": repair_attempts,
                "trace": trace,
                "error": None,
            }

        # Execution failed - repair
        last_error = err
        trace.append(f"Query execution failed: {err}")

        if attempt == MAX_REPAIR_ATTEMPTS:
            break

        current_sql = _agentic_generate(
            question, llm_schema,
            previous_sql=current_sql, error=last_error, attempt=attempt + 1
        )
        repair_attempts += 1
        if current_sql:
            trace.append("SQL corrected by agentic engine")
        else:
            trace.append("Agentic engine failed to produce a correction")
            break
        attempt += 1

    # ---------------- 3. FAILED ----------------
    trace.append("All attempts failed")
    return {
        "source": SOURCE_FAILED,
        "sql": current_sql,
        "result": [],
        "repair_attempts": repair_attempts,
        "trace": trace,
        "error": last_error or "Query could not be completed.",
    }