TEMPLATES = {
    "select_all": "SELECT * FROM {table}",
    "count": "SELECT COUNT(*) FROM {table}",
    "above": "SELECT * FROM {table} WHERE {column} > {value}",
    "below": "SELECT * FROM {table} WHERE {column} < {value}",
    "highest": "SELECT * FROM {table} ORDER BY {column} DESC LIMIT 1",
    "lowest": "SELECT * FROM {table} ORDER BY {column} ASC LIMIT 1"
}

def build_condition_query(table, column, operator, value):
    return f"SELECT * FROM {table} WHERE {column} {operator} '{value}'"