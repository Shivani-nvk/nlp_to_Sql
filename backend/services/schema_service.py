
def get_schema():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
    """)

    schema = {}

    for table, column, dtype in cursor.fetchall():
        if table not in schema:
            schema[table] = {}
        schema[table][column] = dtype

    cursor.close()
    conn.close()

    return schema
