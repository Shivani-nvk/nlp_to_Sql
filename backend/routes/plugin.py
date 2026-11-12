"""Headless plugin API for embedding NLP-to-SQL into organization portals."""

import time
from flask import Blueprint, request, jsonify

from services.hybrid_router import run_hybrid_query
from services.schema_service import get_schema, schema_summary
from services.sql_validator import validate_sql
from sqlalchemy import text

from services.tenant_manager import resolve_plugin_engine

plugin_bp = Blueprint("plugin", __name__, url_prefix="/api/v1/plugin")


def _credentials():
    data = request.get_json(silent=True) or {}
    api_key = (
        request.headers.get("X-API-Key")
        or request.args.get("api_key")
        or data.get("api_key")
        or ""
    )
    database_url = (
        request.headers.get("X-Database-URL")
        or data.get("database_url")
        or ""
    )
    return api_key, database_url


def _resolve_or_error():
    api_key, database_url = _credentials()
    engine, tenant_id, error = resolve_plugin_engine(api_key=api_key, database_url=database_url)
    if error:
        return None, jsonify({"error": error}), 401
    return engine, None, None


@plugin_bp.route("/connect", methods=["POST"])
def plugin_connect():
    engine, error_response, status = _resolve_or_error()
    if error_response:
        return error_response, status

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    schema = get_schema(engine=engine)
    summary = schema_summary(schema)
    summary.update({"ok": True, "dialect": engine.dialect.name})
    return jsonify(summary)


@plugin_bp.route("/schema", methods=["GET", "POST"])
def plugin_schema():
    engine, error_response, status = _resolve_or_error()
    if error_response:
        return error_response, status
    schema = get_schema(engine=engine)
    payload = schema_summary(schema)
    payload["dialect"] = engine.dialect.name
    return jsonify(payload)


@plugin_bp.route("/query", methods=["POST"])
def plugin_query():
    engine, error_response, status = _resolve_or_error()
    if error_response:
        return error_response, status

    data = request.get_json(silent=True) or {}
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Question missing"}), 400

    started = time.time()
    result = run_hybrid_query(
        question.strip(),
        role="user",
        engine=engine,
        is_custom_tenant=True,
    )
    elapsed_ms = int((time.time() - started) * 1000)

    if result.get("sql"):
        ok, reason = validate_sql(result["sql"], role="user")
        if not ok:
            return jsonify({
                "question": question,
                "sql": result["sql"],
                "data": [],
                "columns": [],
                "source": "failed",
                "trace": result.get("trace") or [],
                "repair_attempts": result.get("repair_attempts") or 0,
                "execution_time_ms": elapsed_ms,
                "error": reason,
            }), 400

    response = {
        "question": question,
        "sql": result.get("sql"),
        "data": result.get("result") or [],
        "columns": result.get("columns") or [],
        "source": result.get("source"),
        "trace": result.get("trace") or [],
        "repair_attempts": result.get("repair_attempts") or 0,
        "execution_time_ms": elapsed_ms,
        "used_ai_fallback": result.get("source") in ("agentic", "agentic_self_healed"),
    }
    if result.get("error") and result.get("source") in ("failed", "unanswerable"):
        response["error"] = result["error"]
        code = 400 if result.get("source") == "unanswerable" else 500
        return jsonify(response), code
    return jsonify(response)
