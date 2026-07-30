"""The query.py file defines the /query API endpoint. It receives the users natural language query,
converts it to SQL using NLP, executes it on MySQL, and returns the result."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request
from db import get_db_connection
from services.nlp_to_sql import convert_to_sql

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

    # Convert natural language to SQL
    sql = convert_to_sql(question)

    # Safety net: /query is read-only for everyone (admin and user alike).
    # Insert/update/delete will go through separate admin-only routes once
    # those exist - this blocks it even if nlp_to_sql.py is later extended
    # to generate non-SELECT statements.
    if not sql.strip().upper().startswith("SELECT"):
        return jsonify({"error": "Only SELECT queries are allowed here."}), 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(sql)
        result = cursor.fetchall()
        conn.close()

        return jsonify({
            "question": question,
            "sql": sql,
            "data": result
        })

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500