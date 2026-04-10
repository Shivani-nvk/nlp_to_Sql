"""The query.py file defines the /query API endpoint. It receives the users natural language query,
converts it to SQL using NLP, executes it on MySQL, and returns the result."""

from flask import Blueprint, request, jsonify
from db import get_db_connection
from services.nlp_to_sql import convert_to_sql

query_bp = Blueprint("query", __name__)

@query_bp.route("/query", methods=["GET","POST"])
def run_query():

    # For browser testing
    if request.method == "GET":
        return jsonify({"message": "Query endpoint working. Use POST with a question."})

    data = request.get_json()

    # Check if question exists
    if not data or "question" not in data:
        return jsonify({"error": "Question missing"}), 400

    question = data["question"]

    # Convert natural language to SQL
    sql = convert_to_sql(question)

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