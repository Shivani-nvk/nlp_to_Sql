from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from services.admin_service import (
    get_row, insert_row, update_row, delete_row,
    add_column, rename_or_modify_column, drop_column,
    create_table, drop_table
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    """Returns a (response, status) tuple to return immediately if the
    caller isn't an admin, or None if they're clear to proceed."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required."}), 403
    return None


@admin_bp.route("/row", methods=["GET"])
@jwt_required()
def admin_get_row():
    """
    GET /admin/row?table=employees&id=19
    or GET /admin/row?table=student_info&column=Student_Name&value=Ananya
    Used by the Update and Delete tabs to auto-fill the form as soon as any
    field is entered.
    """
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    table = request.args.get("table")
    row_id = request.args.get("id")
    column = request.args.get("column")
    value = request.args.get("value")

    if not table:
        return jsonify({"error": "Request must include 'table' query param."}), 400

    if (row_id is None or row_id == "") and (column is None or value is None or value == ""):
        return jsonify({"error": "Request must include 'id' or ('column' and 'value')."}), 400

    result = get_row(table, row_id=row_id, column=column, value=value)
    return jsonify(result), (200 if result.get("success") else 400)


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
    data = body.get("data")
    confirm = body.get("confirm", False)

    if not table:
        return jsonify({"error": "Request must include 'table'."}), 400

    if (row_id is None or str(row_id).strip() == "") and (not data or not isinstance(data, dict)):
        return jsonify({"error": "Request must include 'id' or 'data' with column criteria."}), 400

    result = delete_row(table, row_id=row_id, data=data, confirm=confirm)
    return jsonify(result), (200 if result.get("success") else 400)


# ==================== TABLE MANAGEMENT ROUTES ====================

@admin_bp.route("/table/add", methods=["POST"])
@jwt_required()
def admin_add_table():
    """
    POST /admin/table/add
    Body: {"table_name": "products", "columns": [
        {"name": "title", "type": "VARCHAR(255)", "nullable": false},
        {"name": "price", "type": "DECIMAL(10,2)", "default": "0.00"}
    ]}
    'columns' is optional - a table with just the auto id column is
    created if omitted, and columns can be added afterward via
    /admin/column/add.
    """
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table_name = body.get("table_name")
    columns = body.get("columns")

    if not table_name:
        return jsonify({"error": "Request must include 'table_name'."}), 400

    if columns is not None and not isinstance(columns, list):
        return jsonify({"error": "'columns', if provided, must be a list."}), 400

    result = create_table(table_name, columns)
    return jsonify(result), (201 if result.get("success") else 400)


@admin_bp.route("/table/delete", methods=["DELETE"])
@jwt_required()
def admin_delete_table():
    """
    DELETE /admin/table/delete
    Body: {"table_name": "products", "confirm": true}
    'confirm' must be true - this is irreversible. The frontend should
    make the admin type the table name to set it, not just click a button.
    """
    forbidden = _require_admin()
    if forbidden:
        return forbidden

    body = request.get_json(silent=True) or {}
    table_name = body.get("table_name")
    confirm = body.get("confirm", False)

    if not table_name:
        return jsonify({"error": "Request must include 'table_name'."}), 400

    result = drop_table(table_name, confirm)
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