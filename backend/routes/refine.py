# This is a SEPARATE blueprint from routes/query.py on purpose: the query
# chatbot/feedback feature is a distinct concern from the original NLP-to-SQL
# pipeline, and keeping it in its own file/route means nothing here can
# accidentally break convert_to_sql() or the /query endpoint.

from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request
from db import get_db_connection
from services.schema_service import get_schema
from services.query_refiner import parse_query, apply_feedback, rebuild_sql, RefinementError
from services.llm_fallback import llm_refine_convert, EMPTY_RESULT_HINT

refine_bp = Blueprint("refine", __name__)

# Same "read-only, no admin table" posture as /query - the chatbot can only
# ever produce SELECTs against the schema, never touch app_users.
EXCLUDED_TABLES = {"app_users"}
BLOCKED_KEYWORDS = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "UNION", "--", ";", "/*"]


def _is_safe_select(sql):
    """Last line of defence before execution, on top of the fact that
    rebuild_sql() only ever assembles SELECT/FROM/WHERE/GROUP BY/HAVING/
    ORDER BY/LIMIT clauses out of parsed fragments - this catches anything
    that slipped through (e.g. a stray semicolon smuggled in via feedback
    text that happened to match a condition/column pattern). Also applies
    to AI-generated SQL, which gets exactly the same scrutiny as the
    rule-based output - the AI is never trusted more than the rules.

    Note: this deliberately does NOT reject multiple SELECT keywords -
    legitimate subqueries (e.g. "salary > (SELECT AVG(salary) FROM
    employees)", which the rule-based engine itself generates for
    "average of all" / named-person comparisons) contain more than one
    SELECT and are safe. The actual statement-stacking risk that used to
    be caught by that check is UNION-based injection, which is now
    blocked explicitly via BLOCKED_KEYWORDS instead - a more precise
    fix than banning every second SELECT outright."""
    upper = sql.upper()
    if not upper.strip().startswith("SELECT"):
        return False
    if "APP_USERS" in upper:
        return False
    return not any(kw in upper for kw in BLOCKED_KEYWORDS)


@refine_bp.route("/query/refine", methods=["POST"])
def refine_query():
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({"error": "Missing or invalid token. Please log in."}), 401

    body = request.get_json(silent=True) or {}
    previous_sql = body.get("previous_sql") or ""
    feedback = body.get("feedback") or ""

    if not isinstance(previous_sql, str) or not isinstance(feedback, str):
        return jsonify({"error": "Both 'previous_sql' and 'feedback' must be strings."}), 400

    previous_sql = previous_sql.strip()
    feedback = feedback.strip()

    if not previous_sql or not feedback:
        return jsonify({"error": "Both 'previous_sql' and 'feedback' are required."}), 400

    used_ai_fallback = False
    applied_changes = []

    # ---- 1. Try the rule-based refiner first ----
    try:
        ctx = parse_query(previous_sql)
        ctx, applied_changes = apply_feedback(ctx, feedback)

        # Validate the resulting table against the live schema before
        # rebuilding SQL from it.
        if ctx["table"] in EXCLUDED_TABLES:
            return jsonify({"error": f"'{ctx['table']}' can't be queried through this chatbot."}), 400

        schema = get_schema()
        if ctx["table"] not in schema:
            return jsonify({"error": f"Unknown table '{ctx['table']}'."}), 400

        new_sql = rebuild_sql(ctx)

    except RefinementError:
        schema = get_schema()
        return _run_agentic_refinement(previous_sql, feedback, schema, [
            "Rule-based refiner could not confidently map feedback",
            "Agentic refiner activated"
        ])

    # ---- 3. Execute rule-based query with fallback to agentic if execution fails ----
    if not _is_safe_select(new_sql):
        return jsonify({"error": "The refined query failed a safety check and was not run."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(new_sql)
        result = cursor.fetchall()
        return jsonify({
            "sql": new_sql,
            "data": result,
            "applied_changes": applied_changes,
            "used_ai_fallback": False,
            "source": "rule_based",
            "repair_attempts": 0,
            "trace": [
                "Rule-based refiner matched feedback",
                "SQL rebuilt",
                "SQL validation passed",
                "Query executed successfully"
            ],
        })
    except Exception as e:
        # If rule-based execution threw an error, fall back to agentic refiner
        schema = get_schema()
        return _run_agentic_refinement(previous_sql, feedback, schema, [
            f"Rule-based execution failed: {str(e)}",
            "Agentic refiner activated as fallback"
        ])
    finally:
        cursor.close()
        conn.close()


def _run_agentic_refinement(previous_sql, feedback, schema, initial_trace=None):
    trace = list(initial_trace or [])
    MAX_REFINEMENT_ATTEMPTS = 3
    repair_attempts = 0
    last_error = None

    current_sql = llm_refine_convert(previous_sql, feedback, schema)
    if not current_sql:
        return jsonify({
            "error": "Couldn't tell what to change from that feedback. Try rephrasing, e.g. 'only show name and marks' or 'sort by salary descending'."
        }), 422

    # Tracks the final attempt's outcome. `result` staying None means every
    # attempt failed to execute; an empty list is a real answer the loop
    # chose to accept after the model failed to find a literal-free version.
    result = None
    empty_result_accepted = False

    for attempt in range(1, MAX_REFINEMENT_ATTEMPTS + 1):
        if not _is_safe_select(current_sql):
            last_error = "SQL safety validation failed."
            trace.append(f"Attempt {attempt}: Safety validation failed")
            if attempt < MAX_REFINEMENT_ATTEMPTS:
                current_sql = llm_refine_convert(previous_sql, feedback, schema, error=last_error)
                repair_attempts += 1
                if current_sql:
                    trace.append("SQL corrected by agentic refiner")
                continue
            break

        trace.append("SQL validation passed")
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(current_sql)
            result = cursor.fetchall()
            last_error = None
            trace.append("Query executed successfully")

            # A clean run that matched nothing is the case this whole
            # guard is about: valid SQL with a literal that exists in no row
            # raises no error, so without this the loop would break out here
            # and the UI would report "no records matched" as though the
            # filters had been fine. Give the model one more shot with the
            # real values in front of it, on the last attempt it just accepts
            # the empty result rather than looping forever.
            if not result and attempt < MAX_REFINEMENT_ATTEMPTS:
                last_error = EMPTY_RESULT_HINT
                trace.append(
                    f"Attempt {attempt} returned 0 rows - a literal may not "
                    f"exist in the data; asking the agentic refiner to re-check"
                )
                current_sql = llm_refine_convert(
                    previous_sql, feedback, schema, error=EMPTY_RESULT_HINT
                )
                repair_attempts += 1
                if current_sql:
                    trace.append("SQL corrected by agentic refiner")
                else:
                    empty_result_accepted = True
                    break
                continue

            if not result:
                empty_result_accepted = True
                trace.append(
                    "Query matched no rows and no better version could be found; "
                    "returning the empty result as-is"
                )
            break
        except Exception as e:
            last_error = str(e)
            trace.append(f"Attempt {attempt} execution failed: {last_error}")
            result = None
            if attempt < MAX_REFINEMENT_ATTEMPTS:
                current_sql = llm_refine_convert(previous_sql, feedback, schema, error=last_error)
                repair_attempts += 1
                if current_sql:
                    trace.append("SQL corrected by agentic refiner")
                else:
                    break
        finally:
            cursor.close()
            conn.close()

    if result is None:
        return jsonify({
            "error": f"Refinement failed: {last_error or 'Could not generate working SQL.'}",
            "trace": trace
        }), 500

    source = "agentic_self_healed" if repair_attempts > 0 else "agentic"
    applied_changes = ["Refined with AI assistance (self-healed)" if repair_attempts > 0 else "Refined with AI assistance"]
    return jsonify({
        "sql": current_sql,
        "data": result,
        "applied_changes": applied_changes,
        "used_ai_fallback": True,
        "source": source,
        "repair_attempts": repair_attempts,
        "trace": trace,
        # Lets the frontend say "this refinement matched nothing" rather than
        # the generic "no records matched your criteria", which reads as a
        # confirmation that the filters were correct.
        "empty_result": empty_result_accepted,
    })