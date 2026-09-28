"""
SQL validation and safety layer.

Applied BEFORE execution to both rule-based and agentic SQL output.
Rejects destructive operations, exposed auth tables, and suspicious patterns.
"""

import re

BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "REPLACE", "RENAME",
]

EXCLUDED_TABLES = {"app_users"}

# Schema metadata belongs to the database, not to the person asking the
# question. A user-role query has no reason to read information_schema, and
# letting it through would expose the names and types of every table in the
# server - including databases this app was never meant to see.
EXCLUDED_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}

BLOCKED_STATEMENT_SEPARATORS = [";", "/*", "--"]


def validate_sql(sql, role="user"):
    """
    Validates a SQL string for safety.

    Returns:
        (is_valid: bool, reason: str or None)
    """
    if not sql or not isinstance(sql, str):
        return False, "Empty or invalid SQL."

    upper = sql.upper().strip()

    if not upper.startswith("SELECT"):
        return False, "Only SELECT queries are allowed."

    for kw in BLOCKED_KEYWORDS:
        pattern = re.compile(r'\b' + kw + r'\b', re.IGNORECASE)
        if pattern.search(sql):
            return False, f"Blocked keyword: {kw}."

    for table in EXCLUDED_TABLES:
        if table.upper() in upper:
            return False, f"Table '{table}' is not accessible."

    for schema in EXCLUDED_SCHEMAS:
        if re.search(r"\b" + re.escape(schema.upper()) + r"\s*\.", upper):
            return False, f"Schema '{schema}' is not accessible."

    # a second, unprefixed table reference is fine (FROM marks), but a bare
    # metadata function like DATABASE() / USER() also leaks server internals
    for fn in ("DATABASE", "CURRENT_USER", "USER", "VERSION", "CONNECTION_ID"):
        if re.search(r'\b' + fn + r'\s*\(', upper):
            return False, f"Function '{fn}()' is not accessible."

    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        return False, "Blocked statement separator: ';' (multiple statements not permitted)."

    for sep in ["/*", "--"]:
        if sep in sql:
            return False, f"Blocked statement separator: '{sep}'."

    return True, None


def execute_sql_safe(conn, sql):
    """
    Executes a validated SQL query and returns (result, error).
    Returns (list[dict], None) on success or (None, str) on failure.
    """
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        result = cursor.fetchall()
        return result, None
    except Exception as e:
        return None, str(e)
    finally:
        cursor.close()
