import re

from db import get_db_connection
from services.schema_service import get_schema, get_primary_key, invalidate_schema_cache

# app_users is deliberately off-limits here: admins are added manually in
# the DB, and regular users go through /signup (which hashes the password
# correctly). Letting it through this generic form would let raw passwords
# get inserted unhashed, or let someone grant themselves role='admin'.
EXCLUDED_TABLES = {"app_users"}

# Tables whose rows are identified by several columns together. They are NOT
# declared as MySQL primary keys on purpose - join_planner.py relies on
# marks/performance having no PK to recognise them as fact tables.
COMPOSITE_KEYS = {
    "marks": ["Student_ID", "Subject_ID", "Exam"],
    "performance": ["Employee_ID", "Project_ID"],
}


def get_composite_keys():
    return COMPOSITE_KEYS


def _composite_where(table, key):
    """Returns (where_sql, params, error) for a composite-key lookup."""
    cols = COMPOSITE_KEYS.get(table)
    if not cols:
        return None, None, f"Table '{table}' has no composite key."
    if not isinstance(key, dict):
        return None, None, "Key must be an object of column values."
    missing = [c for c in cols if str(key.get(c, "")).strip() == ""]
    if missing:
        return None, None, f"Provide every key column: {', '.join(cols)} (missing {', '.join(missing)})."
    where = " AND ".join(f"`{c}` = %s" for c in cols)
    return where, [str(key[c]).strip() for c in cols], None


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


def get_row(table, row_id=None, column=None, value=None, key=None):
    """
    Fetches a single row by composite key, primary key, or any column value,
    for the admin panel's Update and Delete tabs to auto-fill the form.
    """
    if table in EXCLUDED_TABLES:
        return {"error": f"'{table}' can't be modified through this form."}

    schema = get_schema()
    if table not in schema:
        return {"error": f"Unknown table '{table}'."}

    pk = get_primary_key(table)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if key is not None:
            where, params, err = _composite_where(table, key)
            if err:
                return {"error": err}
            cursor.execute(f"SELECT * FROM `{table}` WHERE {where} LIMIT 1", params)
            row = cursor.fetchone()
            if row is None:
                return {"error": f"No matching row in '{table}' for that key."}
            return {"success": True, "row": row}

        if row_id is not None and str(row_id).strip() != "":
            if pk not in schema[table]:
                return {"error": f"Table '{table}' has no primary key column to look up by."}
            cursor.execute(f"SELECT * FROM `{table}` WHERE `{pk}` = %s LIMIT 1", [row_id])
            row = cursor.fetchone()
            if row is None:
                return {"error": f"No row with {pk} = {row_id} in '{table}'."}
            return {"success": True, "row": row}
        elif column and value is not None and str(value).strip() != "":
            if column not in schema[table]:
                return {"error": f"Unknown column '{column}' for table '{table}'."}
            cursor.execute(f"SELECT * FROM `{table}` WHERE `{column}` = %s LIMIT 1", [value])
            row = cursor.fetchone()
            if row is None and not str(value).isdigit():
                cursor.execute(f"SELECT * FROM `{table}` WHERE `{column}` LIKE %s LIMIT 1", [f"%{value}%"])
                row = cursor.fetchone()
            if row is None:
                return {"error": f"No row with {column} = '{value}' in '{table}'."}
            return {"success": True, "row": row}
        else:
            return {"error": "Provide a key, an id, or column & value to lookup."}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


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

    composite = COMPOSITE_KEYS.get(table)
    pk = get_primary_key(table)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if composite:
            # marks / performance: no PK in MySQL, so check the combined key here
            where, params, err = _composite_where(table, data)
            if err:
                return {"error": err}
            cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE {where}", params)
            if cursor.fetchone()[0] > 0:
                return {"error": f"A row with this {' + '.join(composite)} already exists. Use Update instead."}

        elif pk != "id":
            # student_info, employee_info, project, subject, course, department:
            # the key is NOT auto-increment, so it must be supplied and unique
            key_value = str(data.get(pk, "")).strip()
            if key_value == "":
                return {"error": f"{pk} is required - it is not auto-generated."}
            cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE `{pk}` = %s", [key_value])
            if cursor.fetchone()[0] > 0:
                return {"error": f"{pk} {key_value} already exists in '{table}'. Choose a different value."}

        cursor.execute(sql, values)
        conn.commit()

        if composite:
            new_id = " / ".join(str(data[c]).strip() for c in composite)
        else:
            new_id = cursor.lastrowid or data.get(pk)
        return {"success": True, "id": new_id}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


def update_row(table, row_id, data, key=None):
    if not data:
        return {"error": "No data provided."}

    error = _validate_table_and_columns(table, data.keys())
    if error:
        return {"error": error}

    if key is not None:
        where, key_params, err = _composite_where(table, key)
        if err:
            return {"error": err}
        # the key identifies the row, so it is never rewritten
        data = {c: v for c, v in data.items() if c not in COMPOSITE_KEYS[table]}
        if not data:
            return {"error": "Change at least one non-key field."}
        where_sql, where_params = where, key_params
    else:
        pk = get_primary_key(table)
        if pk not in get_schema().get(table, {}):
            return {"error": f"Table '{table}' has no primary key column to update by."}
        where_sql, where_params = f"`{pk}` = %s", [row_id]

    set_clause = ", ".join(f"`{col}` = %s" for col in data.keys())
    values = list(data.values()) + where_params
    sql = f"UPDATE `{table}` SET {set_clause} WHERE {where_sql}"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(sql, values)
        conn.commit()
        if cursor.rowcount == 0:
            return {"error": f"No matching row in '{table}' (or nothing changed)."}
        return {"success": True, "rows_affected": cursor.rowcount}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()


def delete_row(table, row_id=None, data=None, confirm=False, key=None):
    """
    Deletes one row, addressed by composite key (`key`), primary key
    (`row_id`), or a dict of column criteria (`data`, bulk-guarded).
    """
    if table in EXCLUDED_TABLES:
        return {"error": f"'{table}' can't be modified through this form."}

    schema = get_schema()

    if table not in schema:
        return {"error": f"Unknown table '{table}'."}

    pk = get_primary_key(table)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if key is not None:
            where, params, err = _composite_where(table, key)
            if err:
                return {"error": err}
            sql = f"DELETE FROM `{table}` WHERE {where}"

        elif row_id is not None and str(row_id).strip() != "":
            if pk not in schema[table]:
                return {"error": f"Table '{table}' has no primary key column to delete by."}
            sql = f"DELETE FROM `{table}` WHERE `{pk}` = %s LIMIT 1"
            params = [row_id]

        elif data and isinstance(data, dict) and len(data) > 0:
            error = _validate_table_and_columns(table, data.keys())
            if error:
                return {"error": error}

            null_cols = [col for col, val in data.items() if val is None]
            if null_cols:
                return {
                    "error": "Can't match on an empty value - "
                             f"{', '.join(null_cols)} would need to be NULL, which no row satisfies."
                }

            where_sql = " AND ".join(f"`{col}` = %s" for col in data.keys())
            params = list(data.values())

            cursor.execute(f"SELECT COUNT(*) FROM `{table}` WHERE {where_sql}", params)
            matched = cursor.fetchone()[0]

            if matched == 0:
                return {"error": f"No matching row found in '{table}' to delete."}

            if matched > 1 and not confirm:
                return {
                    "error": f"{matched} rows in '{table}' match those values. Narrow the "
                             f"criteria down to one row, or resend with confirm=true to "
                             f"delete all {matched} of them.",
                    "matches": matched,
                    "requires_confirmation": True,
                }

            sql = f"DELETE FROM `{table}` WHERE {where_sql}"
        else:
            return {"error": "Provide a key, row ID or column values to delete."}

        cursor.execute(sql, params)

        if cursor.rowcount == 0:
            return {"error": f"No matching row found in '{table}' to delete."}

        conn.commit()
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


# ==================== TABLE MANAGEMENT ====================
# Whole-table create/drop. Same validation posture as everything else in
# this file: identifiers and column types are regex-whitelisted (they
# can't be parameterized in DDL), app_users is off-limits, and drop is
# irreversible so it requires an explicit confirm flag from the caller -
# the frontend should make the admin type the table name to set that,
# not just click a button.

def create_table(table_name, columns=None):
    """
    Creates a new table with an auto-incrementing `id` primary key, plus
    any additional columns supplied in `columns`. Each entry in `columns`
    is a dict: {"name": ..., "type": ..., "nullable": bool, "default": ...}
    - same shape and validation as add_column().

    If `columns` is omitted or empty, the table is created with just
    `id` - columns can be added afterward via /admin/column/add, the same
    way as for any other existing table.
    """
    err = _validate_identifier(table_name, "table name")
    if err:
        return {"error": err}

    if table_name in EXCLUDED_TABLES:
        return {"error": f"'{table_name}' is a reserved table name and can't be created through this form."}

    schema = get_schema()
    if table_name in schema:
        return {"error": f"Table '{table_name}' already exists."}

    column_defs = ["`id` INT AUTO_INCREMENT PRIMARY KEY"]
    params = []
    seen_names = {"id"}

    for col in (columns or []):
        name = col.get("name")
        col_type = col.get("type")
        nullable = col.get("nullable", True)
        default = col.get("default")

        err = _validate_identifier(name, "column name")
        if err:
            return {"error": err}

        if name in seen_names:
            return {"error": f"Duplicate column name '{name}'."}
        seen_names.add(name)

        err = _validate_column_type(col_type)
        if err:
            return {"error": err}

        null_sql = "NULL" if nullable else "NOT NULL"
        col_def = f"`{name}` {col_type} {null_sql}"
        if default not in (None, ""):
            col_def += " DEFAULT %s"
            params.append(default)
        column_defs.append(col_def)

    sql = f"CREATE TABLE `{table_name}` (" + ", ".join(column_defs) + ")"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        conn.commit()
        return {"success": True, "table": table_name}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()
        invalidate_schema_cache()


def drop_table(table_name, confirm=False):
    """
    Drops a table entirely - irreversible. Requires confirm=True on top
    of the usual EXCLUDED_TABLES protection for app_users, so a stray/
    accidental request can't silently delete a table.

    `confirm` is checked against the boolean True specifically, not merely
    for truthiness: JSON lets a client send the *string* "false" or "0",
    both of which are truthy in Python, so a plain `if not confirm` would
    have dropped the table on a request that explicitly said not to.
    """
    if table_name in EXCLUDED_TABLES:
        return {"error": f"'{table_name}' can't be dropped through this form."}

    schema = get_schema()
    if table_name not in schema:
        return {"error": f"Unknown table '{table_name}'."}

    if confirm is not True:
        return {"error": "Dropping a table is irreversible - resend the request with confirm=true."}

    sql = f"DROP TABLE `{table_name}`"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
        return {"success": True, "table": table_name}
    except Exception as e:
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()
        invalidate_schema_cache()


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
        invalidate_schema_cache()


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
        invalidate_schema_cache()


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
        invalidate_schema_cache()