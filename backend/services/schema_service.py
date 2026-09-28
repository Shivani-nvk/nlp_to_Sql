import time
from db import get_db_connection

_schema_cache = None
_schema_cache_time = 0
_SCHEMA_CACHE_TTL = 30  # seconds

_pk_cache = None
_pk_cache_time = 0

_values_cache = None
_values_cache_time = 0

# A column only gets its values sampled when it is a text-ish column AND has
# at most this many distinct values. The cap is what keeps the sample useful
# (a low-cardinality column like Result/Exam/Address is exhaustively
# enumerable, so we can hand the model the complete set) and cheap (a
# high-cardinality column like an email or a free-text note is skipped
# rather than shipping a meaningless wall of rows to the prompt).
_MAX_SAMPLED_VALUES = 50

# Text-ish MySQL types whose values are worth grounding. Numeric, date and
# blob columns are excluded: the engine never guesses a numeric literal or a
# date format out of thin air, and neither is what this is here to fix.
_VALUE_SAMPLE_TYPE_PREFIXES = ("char", "varchar", "text", "enum", "tinytext",
                               "mediumtext", "longtext")


def get_column_values(max_values=_MAX_SAMPLED_VALUES):
    """
    Returns {table: {column: [distinct values]}} for every low-cardinality
    text column in the current database (app_users excluded - the auth table
    is never exposed to the AI or the rule engine, not even its data).

    This exists to fix a class of bug that the schema alone cannot fix.
    A column NAME tells the model that `Student_Name` holds a student and
    that `Exam` holds an exam, so it happily writes:

        WHERE Student_Name = 'Ananya'   -- real value is 'Ananya Singh'
        WHERE Exam = 'final'            -- real values are 'Internal 1',
                                          --  'Semester'; there is no final

    Both statements are valid SQL, execute cleanly, and return zero rows,
    and the pipeline has no reason to think anything went wrong. Giving the
    model the actual values lets it write `LIKE '%Ananya%'` or notice that
    no final exam exists at all, instead of inventing a literal that can
    never match.

    Columns with more than max_values distinct values are omitted entirely -
    for those, an incomplete sample would be worse than none, because the
    model would reasonably (but wrongly) conclude the value it wants is
    absent from the sample.

    Cached the same way get_schema() is, and invalidated together with it.
    Returns {} if the database is unreachable, so callers can treat "no
    value hints" as a normal outcome rather than an error.
    """
    global _values_cache, _values_cache_time

    if _values_cache is not None and (time.time() - _values_cache_time) < _SCHEMA_CACHE_TTL:
        return _values_cache

    schema = get_schema()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
    except Exception:
        _values_cache = {}
        _values_cache_time = time.time()
        return _values_cache

    values = {}

    try:
        for table, columns in schema.items():
            if table == "app_users":
                continue

            for column, dtype in columns.items():
                base_type = (dtype or "").lower().split("(")[0].strip()
                if not base_type.startswith(_VALUE_SAMPLE_TYPE_PREFIXES):
                    continue

                # Identifiers come from information_schema, so they are
                # trusted, but they are still backtick-quoted rather than
                # interpolated raw.
                try:
                    cursor.execute(
                        f"SELECT DISTINCT `{column}` FROM `{table}` "
                        f"LIMIT {max_values + 1}"
                    )
                    rows = [r[0] for r in cursor.fetchall()]
                except Exception:
                    continue

                # max_values + 1 rows means "more than we want" - skip the
                # column rather than storing a misleading partial sample.
                if len(rows) > max_values:
                    continue

                # NULL is not a value the model can put in a WHERE clause.
                clean = [str(r) for r in rows if r is not None]
                if not clean:
                    continue

                values.setdefault(table, {})[column] = sorted(set(clean))

        cursor.close()
        conn.close()
    except Exception:
        pass

    _values_cache = values
    _values_cache_time = time.time()

    return _values_cache


def get_schema():
    global _schema_cache, _schema_cache_time

    if _schema_cache is not None and (time.time() - _schema_cache_time) < _SCHEMA_CACHE_TTL:
        return _schema_cache

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

    _schema_cache = schema
    _schema_cache_time = time.time()

    return schema


def get_primary_keys():
    """
    Returns {table: primary_key_column} for every table in the current
    database, read straight from information_schema (COLUMN_KEY = 'PRI').

    This exists because not every table uses a column literally named
    'id' as its primary key (e.g. students.student_id, classes.class_id,
    faculty.faculty_id, exams.exam_id, results.result_id) - admin CRUD
    and the frontend admin panel need to know the REAL key column per
    table instead of assuming 'id' everywhere.

    Cached the same way get_schema() is, and invalidated together with it.
    """
    global _pk_cache, _pk_cache_time

    if _pk_cache is not None and (time.time() - _pk_cache_time) < _SCHEMA_CACHE_TTL:
        return _pk_cache

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND column_key = 'PRI'
        ORDER BY ordinal_position
    """)

    pks = {}
    for table, column in cursor.fetchall():
        # a composite primary key would list more than one column per
        # table here - the first one (by ordinal_position) wins, which is
        # correct for every table in this schema (all single-column PKs)
        if table not in pks:
            pks[table] = column

    cursor.close()
    conn.close()

    _pk_cache = pks
    _pk_cache_time = time.time()

    return pks


def get_primary_key(table, default="id"):
    """Convenience accessor: the PK column for one table, falling back to
    'id' if the table isn't found (keeps old behaviour for callers that
    haven't been updated, and is a safe default since 'id' is still the
    PK on employees/projects)."""
    return get_primary_keys().get(table, default)


def invalidate_schema_cache():
    global _schema_cache, _schema_cache_time, _pk_cache, _pk_cache_time
    global _values_cache, _values_cache_time
    _schema_cache = None
    _schema_cache_time = 0
    _pk_cache = None
    _pk_cache_time = 0
    _values_cache = None
    _values_cache_time = 0