# Save this as routes/refine.py in your project.
#
# This is a SEPARATE blueprint from routes/query.py on purpose: the query
# chatbot/feedback feature is a distinct concern from the original NLP-to-SQL
# pipeline, and keeping it in its own file/route means nothing here can
# accidentally break convert_to_sql() or the /query endpoint.

from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request
from db import get_db_connection
from services.schema_service import get_schema
from services.query_refiner import parse_query, apply_feedback, rebuild_sql, RefinementError

refine_bp = Blueprint("refine", __name__)

# Same "read-only, no admin table" posture as /query - the chatbot can only
# ever produce SELECTs against the schema, never touch app_users.
EXCLUDED_TABLES = {"app_users"}
BLOCKED_KEYWORDS = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "--", ";", "/*"]


def _is_safe_select(sql):
    """Last line of defence before execution, on top of the fact that
    rebuild_sql() only ever assembles SELECT/FROM/WHERE/GROUP BY/HAVING/
    ORDER BY/LIMIT clauses out of parsed fragments - this catches anything
    that slipped through (e.g. a stray semicolon smuggled in via feedback
    text that happened to match a condition/column pattern)."""
    upper = sql.upper()
    if not upper.strip().startswith("SELECT"):
        return False
    if upper.count("SELECT") > 1:
        return False
    return not any(kw in upper for kw in BLOCKED_KEYWORDS)


@refine_bp.route("/query/refine", methods=["POST"])
def refine_query():
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({"error": "Missing or invalid token. Please log in."}), 401

    body = request.get_json(silent=True) or {}
    previous_sql = (body.get("previous_sql") or "").strip()
    feedback = (body.get("feedback") or "").strip()

    if not previous_sql or not feedback:
        return jsonify({"error": "Both 'previous_sql' and 'feedback' are required."}), 400

    # ---- 1. Parse the previous SQL + apply the feedback as edits ----
    try:
        ctx = parse_query(previous_sql)
        ctx, applied_changes = apply_feedback(ctx, feedback)
    except RefinementError as e:
        # User-facing, expected failure mode (unsupported SQL shape, or
        # feedback the rule engine couldn't confidently map to an edit) -
        # 422 Unprocessable Entity, not a 500.
        return jsonify({"error": str(e)}), 422

    # ---- 2. Validate the resulting table/columns against the live schema ----
    if ctx["table"] in EXCLUDED_TABLES:
        return jsonify({"error": f"'{ctx['table']}' can't be queried through this chatbot."}), 400

    schema = get_schema()
    if ctx["table"] not in schema:
        return jsonify({"error": f"Unknown table '{ctx['table']}'."}), 400

    new_sql = rebuild_sql(ctx)

    if not _is_safe_select(new_sql):
        return jsonify({"error": "The refined query failed a safety check and was not run."}), 400

    # ---- 3. Execute using the same DB connection helper as /query ----
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(new_sql)
        result = cursor.fetchall()
        conn.close()

        return jsonify({
            "sql": new_sql,
            "data": result,
            "applied_changes": applied_changes,  # short human-readable summary of what changed
        })

    except Exception as e:
        conn.close()
        # Most likely an invalid column name that slipped past our checks
        # (e.g. feedback referencing a column that doesn't exist on the
        # new table after a table swap) - surfaced as a normal DB error,
        # same pattern as /query.
        return jsonify({"error": f"Database error: {str(e)}"}), 500