from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db_connection


def get_user_by_username(username):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, username, password_hash, role FROM app_users WHERE username = %s",
        (username,)
    )
    user = cursor.fetchone()

    cursor.close()
    conn.close()
    return user


def create_user(username, password):
    """
    Signup always creates role='user'. Admins are never created through
    this function - they're added manually in the DB, on purpose.
    """
    if not username or not password:
        return {"error": "Username and password are required."}

    if get_user_by_username(username):
        return {"error": "That username is already taken."}

    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO app_users (username, password_hash, role) VALUES (%s, %s, 'user')",
        (username, password_hash)
    )
    conn.commit()

    cursor.close()
    conn.close()

    return {"success": True, "username": username, "role": "user"}


def verify_login(username, password):
    """
    Returns {"username": ..., "role": ...} on success, or None if the
    username doesn't exist or the password doesn't match.
    """
    user = get_user_by_username(username)

    if not user:
        return None

    if not check_password_hash(user["password_hash"], password):
        return None

    return {"username": user["username"], "role": user["role"]}