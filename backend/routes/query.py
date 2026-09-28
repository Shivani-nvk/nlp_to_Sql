"""The query.py file defines the /query API endpoint. It receives the users natural language query,
converts it to SQL using NLP, executes it on MySQL, and returns the result.

The hybrid router is used: the rule-based engine is always tried first, and
the agentic AI engine only activates as a fallback (with a bounded
self-healing loop)."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from services.hybrid_router import run_hybrid_query

query_bp = Blueprint("query", __name__)


@query_bp.route("/query", methods=["GET", "POST"])
def run_query():

    # For browser testing
    if request.method == "GET":
        return jsonify({"message": "Query endpoint working. Use POST with a question."})

    # Require a valid token for actual queries (both admin and user - this
    # endpoint is read-only for everyone, so no role check needed here yet)
    try:
        verify_jwt_in_request()
    except Exception:
        return jsonify({"error": "Missing or invalid token. Please log in."}), 401

    data = request.get_json()

    # Check if question exists
    if not data or "question" not in data:
        return jsonify({"error": "Question missing"}), 400

    question = data["question"]

    if not isinstance(question, str):
        return jsonify({"error": "Question must be a string."}), 400

    if not question.strip():
        return jsonify({"error": "Question missing"}), 400

    claims = get_jwt()
    role = claims.get("role", "user")

    # Run the hybrid pipeline (rule-based first, agentic as fallback).
    result = run_hybrid_query(question, role=role)

    response = {
        "question": question,
        "sql": result["sql"],
        "data": result["result"],
        "source": result["source"],
        "trace": result["trace"],
        "repair_attempts": result["repair_attempts"],
        # Backwards-compat flag for the existing frontend logic.
        "used_ai_fallback": result["source"] in ("agentic", "agentic_self_healed"),
    }

    if result["error"] and result["source"] == "failed":
        response["error"] = result["error"]
        return jsonify(response), 500

    return jsonify(response)