import re

from db import get_db_connection
from services.schema_service import get_schema

# app_users is deliberately off-limits here: admins are added manually in
# the DB, and regular users go through /signup (which hashes the password
# correctly). Letting it through this generic form would let raw passwords
# get inserted unhashed, or let someone grant themselves role='admin'.
EXCLUDED_TABLES = {"app_users"}


def _validate_table_and_columns(table, columns):
    """
    Returns an error string, or None if table + all columns are valid.
    This is what stops someone from passing a made-up table/column name
    (or a SQL-injection payload) into the query string.
    """
    if table in EXCLUDED_TABLES:
        return f"'{table}' can't be modified through this form."

    schema = get_schema()

    if table not in schema:
        return f"Unknown table '{table}'."

    valid_columns = schema[table]
    for col in columns:
        if col not in valid_columns:
            return f"Unknown column '{col}' for table '{table}'."

    return None


def insert_row(table, data):
    if not data:
        return {"error": "No data provided."}

    error = _validate_table_and_columns(table, data.keys())
    if error:
        return {"error": error}

    columns = list(data.keys())
    values = list(data.values())

    placeholders = ", ".join(["%s"] * len(columns))
    column_list = ", ".join(f"`{c}`" for c in columns)

    sql = f"INSERT INTO `{table}` ({column_list}) VALUES ({placeholders})"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(sql, values)
        conn.commit()
        return {"success": True, "id": cursor.lastrowid}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


def update_row(table, row_id, data):
    if not data:
        return {"error": "No data provided."}

    error = _validate_table_and_columns(table, data.keys())
    if error:
        return {"error": error}

    schema = get_schema()
    if "id" not in schema.get(table, {}):
        return {"error": f"Table '{table}' has no 'id' column to update by."}

    set_clause = ", ".join(f"`{col}` = %s" for col in data.keys())
    values = list(data.values()) + [row_id]

    sql = f"UPDATE `{table}` SET {set_clause} WHERE id = %s"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(sql, values)
        conn.commit()
        if cursor.rowcount == 0:
            return {"error": f"No row with id {row_id} in '{table}'."}
        return {"success": True, "rows_affected": cursor.rowcount}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


def delete_row(table, row_id):
    if table in EXCLUDED_TABLES:
        return {"error": f"'{table}' can't be modified through this form."}

    schema = get_schema()

    if table not in schema:
        return {"error": f"Unknown table '{table}'."}

    if "id" not in schema[table]:
        return {"error": f"Table '{table}' has no 'id' column to delete by."}

    sql = f"DELETE FROM `{table}` WHERE id = %s"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(sql, [row_id])
        conn.commit()
        if cursor.rowcount == 0:
            return {"error": f"No row with id {row_id} in '{table}'."}
        return {"success": True, "rows_affected": cursor.rowcount}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


# ==================== COLUMN MANAGEMENT ====================
# These build ALTER TABLE statements (add/rename/retype/drop a column).
# Table names, column names, and column types can't be parameterized in
# MySQL DDL the way row values can with %s placeholders - so instead we
# whitelist-validate every piece with regex before it ever touches the
# SQL string. That's what stands in for parameterized queries here.

# Column/table names: letters, numbers, underscores, must start with a letter.
IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')

# Column types: things like INT, VARCHAR(255), DECIMAL(10,2), BIGINT UNSIGNED,
# ENUM('a','b','c')
COLUMN_TYPE_RE = re.compile(
    r"^[A-Za-z]+"                                  # base type e.g. VARCHAR, INT
    r"(\((\d+(\s*,\s*\d+)?|'[^']*'(\s*,\s*'[^']*')*)\))?"  # (255) or (10,2) or ('a','b')
    r"(\s+UNSIGNED)?$",                             # optional UNSIGNED
    re.IGNORECASE
)


def _validate_identifier(name, label="identifier"):
    if not name or not IDENTIFIER_RE.match(name):
        return f"Invalid {label} '{name}'. Use only letters, numbers, and underscores, starting with a letter."
    return None


def _validate_column_type(col_type):
    if not col_type or not COLUMN_TYPE_RE.match(col_type.strip()):
        return f"Invalid column type '{col_type}'. Try something like VARCHAR(255), INT, or DATE."
    return None


def add_column(table, column_name, column_type, nullable=True, default=None):
    if table in EXCLUDED_TABLES:
        return {"error": f"'{table}' can't be modified through this form."}

    schema = get_schema()
    if table not in schema:
        return {"error": f"Unknown table '{table}'."}

    err = _validate_identifier(column_name, "column name")
    if err:
        return {"error": err}

    if column_name in schema[table]:
        return {"error": f"Column '{column_name}' already exists on '{table}'."}

    err = _validate_column_type(column_type)
    if err:
        return {"error": err}

    null_sql = "NULL" if nullable else "NOT NULL"
    sql = f"ALTER TABLE `{table}` ADD COLUMN `{column_name}` {column_type} {null_sql}"

    params = []
    if default not in (None, ""):
        sql += " DEFAULT %s"
        params.append(default)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


def rename_or_modify_column(table, old_name, new_name, column_type):
    """
    Renames a column and/or changes its type. MySQL's CHANGE COLUMN syntax
    needs the FULL type spelled out even if you're only renaming - there's
    no "just rename" shortcut, so the caller always sends a type.
    """
    if table in EXCLUDED_TABLES:
        return {"error": f"'{table}' can't be modified through this form."}

    schema = get_schema()
    if table not in schema:
        return {"error": f"Unknown table '{table}'."}

    if old_name not in schema[table]:
        return {"error": f"Unknown column '{old_name}' on '{table}'."}

    if old_name == "id":
        return {"error": "The 'id' column can't be renamed or retyped here."}

    err = _validate_identifier(new_name, "column name")
    if err:
        return {"error": err}

    err = _validate_column_type(column_type)
    if err:
        return {"error": err}

    if new_name != old_name and new_name in schema[table]:
        return {"error": f"Column '{new_name}' already exists on '{table}'."}

    sql = f"ALTER TABLE `{table}` CHANGE COLUMN `{old_name}` `{new_name}` {column_type}"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


def drop_column(table, column_name):
    if table in EXCLUDED_TABLES:
        return {"error": f"'{table}' can't be modified through this form."}

    schema = get_schema()
    if table not in schema:
        return {"error": f"Unknown table '{table}'."}

    if column_name not in schema[table]:
        return {"error": f"Unknown column '{column_name}' on '{table}'."}

    if column_name == "id":
        return {"error": "The 'id' column can't be dropped."}

    sql = f"ALTER TABLE `{table}` DROP COLUMN `{column_name}`"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()