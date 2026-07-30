# Save this as routes/auth.py in your project (kept flat here since I don't
# have write access to your actual routes/ folder).

from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from services.auth_service import create_user, verify_login

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    result = create_user(username, password)

    if "error" in result:
        return jsonify(result), 400

    # Log them straight in after signup
    token = create_access_token(
        identity=username,
        additional_claims={"role": "user"}
    )
    return jsonify({"token": token, "username": username, "role": "user"})


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = verify_login(username, password)

    if not user:
        return jsonify({"error": "Invalid username or password."}), 401

    token = create_access_token(
        identity=user["username"],
        additional_claims={"role": user["role"]}
    )
    return jsonify({"token": token, "username": user["username"], "role": user["role"]})