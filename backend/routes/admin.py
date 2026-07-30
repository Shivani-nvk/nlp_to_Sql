from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from services.admin_service import (
    insert_row, update_row, delete_row,
    add_column, rename_or_modify_column, drop_column
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    """Returns a (response, status) tuple to return immediately if the
    caller isn't an admin, or None if they're clear to proceed."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required."}), 403
    return None


@admin_bp.route("/insert", methods=["POST"])
@jwt_required()
def admin_insert():
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table = body.get("table")
    data = body.get("data")

    if not table or not isinstance(data, dict):
        return jsonify({"error": "Request must include 'table' and 'data'."}), 400

    result = insert_row(table, data)
    return jsonify(result), (201 if result.get("success") else 400)


@admin_bp.route("/update", methods=["PUT"])
@jwt_required()
def admin_update():
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table = body.get("table")
    row_id = body.get("id")
    data = body.get("data")

    if not table or row_id is None or not isinstance(data, dict):
        return jsonify({"error": "Request must include 'table', 'id', and 'data'."}), 400

    result = update_row(table, row_id, data)
    return jsonify(result), (200 if result.get("success") else 400)


@admin_bp.route("/delete", methods=["DELETE"])
@jwt_required()
def admin_delete():
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table = body.get("table")
    row_id = body.get("id")

    if not table or row_id is None:
        return jsonify({"error": "Request must include 'table' and 'id'."}), 400

    result = delete_row(table, row_id)
    return jsonify(result), (200 if result.get("success") else 400)


# ==================== COLUMN MANAGEMENT ROUTES ====================

@admin_bp.route("/column/add", methods=["POST"])
@jwt_required()
def admin_add_column():
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table = body.get("table")
    column_name = body.get("column_name")
    column_type = body.get("column_type")
    nullable = body.get("nullable", True)
    default = body.get("default")

    if not table or not column_name or not column_type:
        return jsonify({"error": "Request must include 'table', 'column_name', and 'column_type'."}), 400

    result = add_column(table, column_name, column_type, nullable, default)
    return jsonify(result), (201 if result.get("success") else 400)


@admin_bp.route("/column/update", methods=["PUT"])
@jwt_required()
def admin_update_column():
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table = body.get("table")
    old_name = body.get("old_name")
    new_name = body.get("new_name")
    column_type = body.get("column_type")

    if not table or not old_name or not new_name or not column_type:
        return jsonify({"error": "Request must include 'table', 'old_name', 'new_name', and 'column_type'."}), 400

    result = rename_or_modify_column(table, old_name, new_name, column_type)
    return jsonify(result), (200 if result.get("success") else 400)


@admin_bp.route("/column/delete", methods=["DELETE"])
@jwt_required()
def admin_delete_column():
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table = body.get("table")
    column_name = body.get("column_name")

    if not table or not column_name:
        return jsonify({"error": "Request must include 'table' and 'column_name'."}), 400

    result = drop_column(table, column_name)
    return jsonify(result), (200 if result.get("success") else 400)