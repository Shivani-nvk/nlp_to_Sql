# Shivani's part

import nltk
from nltk.tokenize import word_tokenize

# ---------------- INTENT MAP ----------------

INTENT_MAP = {
    "show": "select",
    "display": "select",
    "list": "select",
    "count": "count",
    "total": "count",
}

SELECT_INTENT_WORDS = ["show", "display", "list", "get", "find"]

# ---------------- AGGREGATE MAP ----------------

AGGREGATE_MAP = {
    "average": "AVG",
    "avg": "AVG",

    "sum": "SUM",

    "minimum": "MIN",
    "min": "MIN",

    "maximum": "MAX",
    "max": "MAX",
    
    "distinct": "DISTINCT",
    "unique": "DISTINCT"
}

# ---------------- CONDITION MAP ----------------

CONDITION_MAP = {
    "above": "above",
    "greater": "above",
    "more": "above",
    "over": "above",
    ">": "above",
    ">=": "on_or_after",

    "below": "below",
    "less": "below",
    "lesser": "below",
    "under": "below",
    "<": "below",
    "<=": "on_or_before",

    "highest": "highest",
    "top": "highest",

    "lowest": "lowest",
    "least": "lowest",
    "bottom": "lowest",
    "last": "lowest",

    "equal": "equal",
    "equals": "equal",
    "is": "equal",
    "=": "equal",

    "before": "below",
    "after": "above",

    "since": "on_or_after",
    "till": "on_or_before",
    "until": "on_or_before",

    "older": "above",
    "younger": "below",

    # sentinel tokens produced by merge_comparison_phrases() below, standing
    # in for multi-word >=/<= phrasings ("at least", "3 or more", "equal to
    # or greater than", etc.) that a single-token scan can't recognize
    "AT_LEAST": "gte",
    "AT_MOST": "lte"
}

# CONDITION_MAP values that pick a *record* (ORDER BY ... LIMIT), as opposed
# to a WHERE comparison value
RECORD_CONDITION_TYPES = {"highest", "lowest"}

# CONDITION_MAP values that build a WHERE numeric comparison
VALUE_CONDITION_TYPES = {"above", "below", "equal", "on_or_after", "on_or_before", "gte", "lte"}

# raw trigger words that are always about the joining/hiring date, regardless
# of which column word (if any) happens to sit nearby
DATE_TRIGGER_WORDS = {"before", "after", "since", "till", "until"}

# ---------------- TABLE MAP ----------------

TABLE_MAP = {
    "student": "students",
    "students": "students",
    "stu": "students",

    "employee": "employees",
    "employees": "employees",
    "emp": "employees",
    "staff": "employees",

    "department": "departments",
    "departments": "departments",
    "dept": "departments",

    "course": "courses",
    "courses": "courses",

    "teacher": "teachers",
    "teachers": "teachers",

    "enrollment": "enrollments",
    "enrollments": "enrollments",

    "attendance_record": "attendance",   # to avoid clash with students.attendance
    "attendance_records": "attendance"
}

# ---------------- COLUMN MAP ----------------

COLUMN_MAP = {

    # students
    "marks": "marks",
    "mark": "marks",
    "attendance": "attendance",
    "semester": "semester",
    "semesters": "semester",
    "subject": "subject",
    "subjects": "subject",

    # employees
    "salary": "salary",
    "salaries": "salary",
    "experience": "experience",
    "joining": "joining_year",
    "joined": "joining_year",
    "hired": "joining_year",
    "year": "joining_year",
    "years": "joining_year",
    "joining_year": "joining_year",

    # departments
    "department_id": "departments.department_id",
    "department_name": "departments.department_name",
    "dept_name": "departments.department_name",
    "location": "departments.location",

    # courses
    "course_id": "courses.course_id",
    "course_name": "courses.course_name",
    "credits": "courses.credits",
    # FKs (we’ll expose them as plain columns for simple filters)
    "department_id": "courses.department_id",   # already covered; keep if you want plain
    "teacher_id": "courses.teacher_id",

    # teachers
    "teacher_id": "teachers.teacher_id",
    "teacher_name": "teachers.teacher_name",
    "email": "teachers.email",
    "teacher_department_id": "teachers.department_id",

    # enrollments
    "enrollment_id": "enrollments.enrollment_id",
    "student_id": "enrollments.student_id",
    "course_id": "enrollments.course_id",
    "enrollment_date": "enrollments.enrollment_date",
    "grade": "enrollments.grade",

    # attendance (log)
    "attendance_id": "attendance.attendance_id",
    "att_student_id": "attendance.student_id",
    "att_course_id": "attendance.course_id",
    "attendance_date": "attendance.attendance_date",
    "status": "attendance.status",
    # alias for the summary column already in students:
    "attendance_pct": "students.attendance",

    # common
    "id": "id",
    "ids": "id",
    "age": "age",
    "ages": "age",
    "name": "name",
    "names": "name",
    "city": "city",
    "cities": "city",
    "gender": "gender",
    "genders": "gender"
}

# columns that should never be treated as the "numeric_column" used in
# aggregates / above / below / equal / highest / lowest
CATEGORICAL_COLUMNS = ["department", "city", "gender", "name", "subject"]

# Tables that have a 'city' column (used for shared-column joins)
TABLES_WITH_CITY = {"students", "employees"}

# ---------------- DEPARTMENTS ----------------

DEPARTMENTS = [
    "it",
    "hr",
    "finance",
    "sales",
    "marketing"
]

# ---------------- CITIES ----------------

CITIES = [
    "bangalore",
    "mysore",
    "mangalore",
    "hubli",
    "belgaum"
]

# ---------------- GENDERS ----------------

GENDERS = [
    "male",
    "female"
]

# ---------------- LIKE ----------------

LIKE_KEYWORDS = ["like", "contains", "containing"]
STARTS_KEYWORDS = ["starting", "starts"]
ENDS_KEYWORDS = ["ending", "ends"]
LIKE_FILLER_WORDS = {"with", "the", "in", "of"}

# ---------------- ORDER BY ----------------

ORDER_TRIGGER_WORDS = ["order", "sort", "arrange"]

SORT_DIRECTION_MAP = {
    "ascending": "ASC",
    "asc": "ASC",
    "increasing": "ASC",

    "descending": "DESC",
    "desc": "DESC",
    "decreasing": "DESC",
}

# ---------------- JOIN ----------------

JOIN_TRIGGER_WORDS = ["join", "joined", "combined", "along", "same", "match", "matches", "matching"]

JOIN_TYPE_MAP = {
    "inner": "INNER JOIN",
    "left": "LEFT JOIN",
    "right": "RIGHT JOIN",
    "outer": "FULL OUTER",   # Special marker for full outer join simulation
    "full": "FULL OUTER",    # Special marker for full outer join simulation
    "cross": "CROSS JOIN",
}

# department only exists on employees - it is NOT shared with students,
# so it can't be a safe default join/compare key. name, age, gender, and
# city are the columns both tables actually have (confirmed against the
# real schema); city is the most meaningful one to match students and
# employees on by default when no join column is stated explicitly.
SHARED_COLUMN = "city"

# ---------------- RELATIONSHIPS ----------------
# Format: (local_table, local_col, foreign_table, foreign_col)
RELATIONSHIPS = [
    # courses → departments
    ("courses", "department_id", "departments", "department_id"),
    # courses → teachers
    ("courses", "teacher_id", "teachers", "teacher_id"),
    # teachers → departments
    ("teachers", "department_id", "departments", "department_id"),
    # enrollments → students
    ("enrollments", "student_id", "students", "id"),
    # enrollments → courses
    ("enrollments", "course_id", "courses", "course_id"),
    # attendance → students
    ("attendance", "student_id", "students", "id"),
    # attendance → courses
    ("attendance", "course_id", "courses", "course_id"),
]

# ---------------- NULL ----------------

NULL_TRIGGER_WORDS = ["null", "missing", "blank", "empty"]

# ---------------- HAVING ----------------

HAVING_TRIGGER_WORDS = ["having"]

# ---------------- EXISTS ----------------

EXISTS_TRIGGER_WORDS = ["exists", "exist", "belong", "belongs", "live", "lives", "lived"]

# ---------------- ANY / ALL ----------------

ANY_ALL_TRIGGER_WORDS = {"any": "ANY", "all": "ALL"}

# ---------------- UNION ----------------

UNION_TRIGGER_WORDS = ["union"]

# ---------------- CASE ----------------

CASE_TRIGGER_WORDS = ["label", "case"]

# ---------------- NULL FUNCTIONS (IFNULL / COALESCE) ----------------

IFNULL_TRIGGER_WORDS = ["ifnull", "coalesce"]


# ---------------- WORD NUMBERS ("fifty", "one hundred and five") ----------------

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

SCALE_WORDS = {
    "hundred": 100,
    "thousand": 1000,
}


def words_to_numbers(tokens):
    """
    Replaces sequences of English number words with a single digit-string
    token, e.g. ["more", "than", "fifty"] -> ["more", "than", "50"],
    ["one", "hundred", "and", "five"] -> ["105"].

    "and" only bridges two number words when it directly follows a scale
    word (hundred/thousand) - this keeps "between twenty and fifty" as two
    separate numbers (20, 50) instead of merging them into one.
    """
    result = []
    i = 0
    n = len(tokens)

    while i < n:
        word = tokens[i]

        if word in NUMBER_WORDS or word in SCALE_WORDS:
            total = 0
            current = 0
            matched = False
            after_scale = False
            j = i

            while j < n:
                w = tokens[j]

                if w in NUMBER_WORDS:
                    current += NUMBER_WORDS[w]
                    matched = True
                    after_scale = False
                    j += 1

                elif w in SCALE_WORDS:
                    if current == 0:
                        current = 1
                    current *= SCALE_WORDS[w]
                    total += current
                    current = 0
                    matched = True
                    after_scale = True
                    j += 1

                elif w == "and" and after_scale:
                    after_scale = False
                    j += 1

                else:
                    break

            total += current

            if matched:
                result.append(str(total))
                i = j
                continue

        result.append(word)
        i += 1

    return result


def is_negated(tokens, idx, window=3):
    """Checks if the word 'not' appears shortly before tokens[idx]."""
    start = max(0, idx - window)
    return "not" in tokens[start:idx]


def build_categorical_condition(column, values, use_in, not_in=False):
    """
    values: list of (value, negated) tuples, in the order they were found.
    - if multiple values + 'or'/'in' present -> IN (...) / NOT IN (...) clause
    - otherwise -> use the last value found (keeps old behaviour), = or !=
    """
    if not values:
        return None

    if len(values) > 1 and use_in:
        in_list = ", ".join(f"'{v}'" for v, _ in values)
        keyword = "NOT IN" if not_in else "IN"
        return f"{column} {keyword} ({in_list})"

    val, negated = values[-1]
    operator = "!=" if negated else "="
    return f"{column} {operator} '{val}'"


def parse_or_clause(tokens, default_column=None):
    """
    Parses one half of an 'X or Y' sentence into a single WHERE condition
    string, e.g. ['below', '40'] -> 'marks < 40', or
    ['department', 'is', 'hr'] -> "department = 'HR'".
    default_column fills in the column when a clause only gives an
    operator + value (e.g. "or below 40" with no column word of its own).
    Returns None if nothing usable was found in this clause.
    """
    col = None
    operator_word = None
    val = None
    text_col = None
    text_val = None

    for word in tokens:
        if word in COLUMN_MAP and COLUMN_MAP[word] not in CATEGORICAL_COLUMNS:
            col = COLUMN_MAP[word]
        if word in DEPARTMENTS:
            text_col = "department"
            text_val = word.upper()
        if word in CITIES:
            text_col = "city"
            text_val = word.title()
        if word in GENDERS:
            text_col = "gender"
            text_val = word.capitalize()
        if word in CONDITION_MAP and CONDITION_MAP[word] in VALUE_CONDITION_TYPES:
            operator_word = CONDITION_MAP[word]
        if word.isdigit():
            val = word

    if text_col and text_val:
        return f"{text_col} = '{text_val}'"

    if not col:
        col = default_column

    op_symbol_map = {"above": ">", "below": "<", "equal": "=", "on_or_after": ">=", "on_or_before": "<=", "gte": ">=", "lte": "<="}

    if col and operator_word and val:
        return f"{col} {op_symbol_map[operator_word]} {val}"

    return None


def merge_comparison_phrases(tokens):
    """
    Collapses multi-word >=/<= phrasings ('at least', 'equal to or greater
    than', '3 or more', etc.) into single sentinel tokens (AT_LEAST /
    AT_MOST) before any other parsing happens.

    This has to run first, because several of these phrases are built out
    of words that already mean something else on their own - "least" alone
    means "lowest" (ORDER BY ... LIMIT 1), and "more"/"greater" alone mean
    a strict ">". Collapsing the whole phrase up front stops those other
    rules from firing on words that are actually part of a >=/<= phrase.
    """
    AT_LEAST_PHRASES = [
        ("at", "least"),
        ("equal", "to", "or", "more", "than"),
        ("equal", "to", "or", "greater", "than"),
        ("equal", "to", "and", "more", "than"),
        ("equal", "to", "and", "greater", "than"),
        ("greater", "than", "or", "equal", "to"),
        ("more", "than", "or", "equal", "to"),
        ("or", "more"),
        ("or", "greater"),
        (">", "="),
    ]
    AT_MOST_PHRASES = [
        ("at", "most"),
        ("equal", "to", "or", "less", "than"),
        ("equal", "to", "or", "lesser", "than"),
        ("equal", "to", "and", "less", "than"),
        ("equal", "to", "and", "lesser", "than"),
        ("less", "than", "or", "equal", "to"),
        ("lesser", "than", "or", "equal", "to"),
        ("or", "less"),
        ("or", "fewer"),
        ("<", "="),
    ]

    # longest phrases first, so e.g. "...or more than" matches whole
    # before the shorter "or more" tail could match it partially
    all_phrases = sorted(
        [(p, "AT_LEAST") for p in AT_LEAST_PHRASES] + [(p, "AT_MOST") for p in AT_MOST_PHRASES],
        key=lambda pair: -len(pair[0])
    )

    result = []
    i = 0
    n = len(tokens)

    while i < n:
        matched = False
        for phrase, sentinel in all_phrases:
            plen = len(phrase)
            if tuple(tokens[i:i + plen]) == phrase:
                result.append(sentinel)
                i += plen
                matched = True
                break
        if not matched:
            result.append(tokens[i])
            i += 1

    return result


def convert_to_sql(question):

    question = question.lower()
    tokens = word_tokenize(question)
    tokens = words_to_numbers(tokens)
    tokens = merge_comparison_phrases(tokens)

    table = "students"
    intent = "select"
    aggregate_function = None

    record_condition = None
    record_condition_idx = None

    value_condition = None
    value_condition_idx = None
    value_condition_word = None

    value = None

    numeric_column = None
    condition_column = None
    column_aliases = {}

    department_values = []
    city_values = []
    gender_values = []
    name_value = None
    subject_value = None

    group_by_column = None
    limit_value = None
    between_values = None

    order_by_column = None
    order_by_direction = "ASC"
    order_requested = False

    like_column = None
    like_pattern = None
    like_mode = "contains"
    like_negated = False

    conditions = []
    selected_columns = []  # list of column name strings for UNION section
    selected = []  # list of (column, source_table) tuples

    # ---------------- SUBJECT DETECTION ----------------

    if "computer science" in question:
        subject_value = "Computer Science"

    elif "mathematics" in question:
        subject_value = "Mathematics"

    elif "science" in question:
        subject_value = "Science"

    elif "english" in question:
        subject_value = "English"

    # ---------------- TABLE ----------------

    table_word_idx = None

    for i, word in enumerate(tokens):
        # Check for dotted table names (e.g., students.name)
        table_key = word
        if '.' in word:
            parts = word.split('.')
            if len(parts) == 2 and parts[0] in TABLE_MAP:
                table_key = parts[0]
        if table_key in TABLE_MAP and table_word_idx is None:
            table = TABLE_MAP[table_key]
            table_word_idx = i

    # If no explicit table was mentioned, infer table from column references
    if table_word_idx is None:
        # Count column references per table to determine most likely table
        table_column_counts = {}
        for word in tokens:
            # Check for dotted column names (e.g., students.name)
            col_key = word
            prefix_table = None
            if '.' in word:
                parts = word.split('.')
                if len(parts) == 2:
                    if parts[0] in TABLE_MAP:
                        prefix_table = TABLE_MAP[parts[0]]
                    if parts[1] in COLUMN_MAP:
                        col_key = parts[1]
            if col_key in COLUMN_MAP:
                column = COLUMN_MAP[col_key]
                # Determine which table this column belongs to
                if prefix_table is not None:
                    # Use the table indicated by the prefix
                    table_name = prefix_table
                else:
                    # Determine which table this column belongs to based on column name
                    if column in ["marks", "attendance", "semester", "subject", "blood_groupp"]:
                        table_name = "students"
                    elif column in ["salary", "experience", "joining_year", "department", "age", "gender", "city", "id", "name"]:
                        # These columns exist in both tables
                        if column in ["salary", "experience", "joining_year", "department"]:
                            # Strongly associated with employees
                            table_name = "employees"
                        else:
                            # For shared columns (age, gender, city, id, name), default to students
                            # but we'll use tie-breaking logic later if needed
                            table_name = "students"
                    else:
                        # Default fallback
                        table_name = "students"

                table_column_counts[table_name] = table_column_counts.get(table_name, 0) + 1

        # Select the table with the most column references
        if table_column_counts:
            table = max(table_column_counts, key=table_column_counts.get)

    # ---------------- SECOND TABLE / JOIN ----------------

    join_type = None
    second_table = None
    join_columns = []
    join_trigger_idx = None
    join_related_indices = set()

    for word in tokens:
        if word in JOIN_TYPE_MAP:
            join_type = JOIN_TYPE_MAP[word]

    if any(w in tokens for w in JOIN_TRIGGER_WORDS):
        tables_found = []
        for word in tokens:
            # Check for dotted table names (e.g., students.name)
            table_key = word
            if '.' in word:
                parts = word.split('.')
                if len(parts) == 2 and parts[0] in TABLE_MAP:
                    table_key = parts[0]
            if table_key in TABLE_MAP and TABLE_MAP[table_key] not in tables_found:
                tables_found.append(TABLE_MAP[table_key])

        if len(tables_found) >= 2:
            table = tables_found[0]
            second_table = tables_found[1]
            if join_type is None:
                join_type = "INNER JOIN"   # default when no join type word is used

            # remember which token actually triggered the join (e.g. the
            # word "joined") so the selected-columns scan further down
            # doesn't also read it as the joining_year column
            join_trigger_idx = next(
                i for i, w in enumerate(tokens) if w in JOIN_TRIGGER_WORDS
            )
            join_related_indices.add(join_trigger_idx)

            # figure out which column(s) to join on instead of always
            # assuming department - "same <col> [and <col>]" and
            # "<col> [and <col>] match(es)" both work, scanning until a
            # sentence-boundary word so multiple columns can be picked up
            # (e.g. "whose age and city both match")
            for i, word in enumerate(tokens):
                if word in ("same", "matching"):
                    j = i + 1
                    while j < len(tokens) and tokens[j] not in ("match", "matches", "whose", "if"):
                        if tokens[j] in COLUMN_MAP:
                            col = COLUMN_MAP[tokens[j]]
                            if col not in join_columns:
                                join_columns.append(col)
                            join_related_indices.add(j)
                        j += 1
                if word in ("match", "matches"):
                    j = i - 1
                    while j >= 0 and tokens[j] not in ("whose", "if", "when"):
                        if tokens[j] in COLUMN_MAP:
                            col = COLUMN_MAP[tokens[j]]
                            if col not in join_columns:
                                join_columns.append(col)
                            join_related_indices.add(j)
                        j -= 1

            # If no specific join columns were mentioned, use the defined relationships
            if not join_columns:
                # Look for a relationship between the two tables
                for local_table, local_col, foreign_table, foreign_col in RELATIONSHIPS:
                    if (local_table == table and foreign_table == second_table) or \
                       (local_table == second_table and foreign_table == table):
                        # Found a relationship, use the appropriate columns
                        if local_table == table and foreign_table == second_table:
                            join_columns.append(local_col)
                        else:
                            join_columns.append(foreign_col)
                        break

    # ---------------- UNION ----------------

    union_second_table = None
    union_all = False

    # Explicit union detection (for the word "union")
    if any(w in tokens for w in UNION_TRIGGER_WORDS):
        union_all = "all" in tokens
        tables_found_union = []
        for word in tokens:
            if word in TABLE_MAP and TABLE_MAP[word] not in tables_found_union:
                tables_found_union.append(TABLE_MAP[word])

        if len(tables_found_union) >= 2:
            table = tables_found_union[0]
            union_second_table = tables_found_union[1]

    # Implicit table detection: if we haven't found a second table yet and we are not doing an explicit union,
    # look for two distinct table names in the tokens and only treat as a join if a join column can be found.
    if second_table is None and union_second_table is None:
        table_names = []
        for word in tokens:
            if word in TABLE_MAP:
                table_names.append(TABLE_MAP[word])
        # Remove duplicates while preserving order
        seen = set()
        distinct = []
        for t in table_names:
            if t not in seen:
                seen.add(t)
                distinct.append(t)
        if len(distinct) >= 2:
            # Try to find a join column between the first two distinct tables
            cand_table = distinct[0]
            cand_second = distinct[1]
            join_cols = []
            # 1) Check defined relationships
            for local_table, local_col, foreign_table, foreign_col in RELATIONSHIPS:
                if (local_table == cand_table and foreign_table == cand_second) or \
                   (local_table == cand_second and foreign_table == cand_table):
                    if local_table == cand_table and foreign_table == cand_second:
                        join_cols.append(local_col)
                    else:
                        join_cols.append(foreign_col)
                    break
            # 2) If no relationship, check if both tables have the shared column (city)
            if not join_cols:
                if cand_table in TABLES_WITH_CITY and cand_second in TABLES_WITH_CITY:
                    join_cols = [SHARED_COLUMN]
            # If we found at least one join column, set up the join
            if join_cols:
                table = cand_table
                second_table = cand_second
                join_type = "INNER JOIN"   # default join type
                join_columns = join_cols
                # No specific trigger word, so join_trigger_idx remains None
                # join_related_indices stays empty (no trigger token to skip)
            # If no join column found, we do NOT set second_table (leave as None) to avoid invalid joins

    # ---------------- INTENT ----------------

    for word in tokens:
        if word in INTENT_MAP:
            intent = INTENT_MAP[word]

    # ---------------- AGGREGATE ----------------

    aggregate_idx = None

    for i, word in enumerate(tokens):
        if word in AGGREGATE_MAP:
            aggregate_function = AGGREGATE_MAP[word]
            aggregate_idx = i

    # ---------------- CONDITION ----------------
    # split into "record" conditions (highest/lowest -> ORDER BY ... LIMIT)
    # and "value" conditions (above/below/since/etc -> WHERE comparison), so
    # a query using both doesn't let one silently overwrite the other.

    for i, word in enumerate(tokens):
        # Check for dotted column names (e.g., employees.salary)
        col_key = word
        if '.' in word:
            parts = word.split('.')
            if len(parts) == 2 and parts[1] in COLUMN_MAP:
                col_key = parts[1]
        if col_key in CONDITION_MAP:
            mapped = CONDITION_MAP[col_key]

            if mapped in RECORD_CONDITION_TYPES:
                record_condition = mapped
                record_condition_idx = i

            elif mapped in VALUE_CONDITION_TYPES:
                value_condition = mapped
                value_condition_idx = i
                value_condition_word = word

    # ---------------- GROUP BY ("... by department", "... per subject") ----------------
    # only meaningful alongside an aggregate or a count, otherwise "top 3 by
    # salary" would be mistaken for a GROUP BY instead of a sort column.

    if aggregate_function or intent == "count":
        for keyword in ["by", "per", "each"]:
            if keyword in tokens:
                idx = tokens.index(keyword)
                if idx + 1 < len(tokens):
                    next_word = tokens[idx + 1]
                    if next_word in COLUMN_MAP:
                        group_by_column = COLUMN_MAP[next_word]

        # implicit pattern: "cities where average marks..." / "departments
        # where avg salary..." - the categorical column mentioned before the
        # aggregate word is treated as the GROUP BY target when no explicit
        # by/per/each keyword was found
        if not group_by_column and aggregate_idx is not None:
            for word in tokens[:aggregate_idx]:
                if word in COLUMN_MAP and COLUMN_MAP[word] in ("department", "city", "gender"):
                    group_by_column = COLUMN_MAP[word]
                    break

    # implicit COUNT: "<column>s having more than N ..." with no explicit
    # "count"/aggregate word still means "how many rows per column value"
    if not group_by_column and "having" in tokens:
        having_word_idx = tokens.index("having")
        for word in tokens[:having_word_idx]:
            if word in COLUMN_MAP:
                group_by_column = COLUMN_MAP[word]
        if group_by_column and intent != "count" and not aggregate_function:
            intent = "count"

    # a numeric comparison alongside a GROUP BY + aggregate/count belongs in
    # HAVING (applied after grouping), not WHERE (applied before) - this
    # covers both "... having more than 2 ..." and "... average marks are
    # greater than 80" phrasings, so it's checked once here and reused both
    # to build HAVING later and to skip the normal WHERE numeric condition
    # (computed further down, right after `value` itself is resolved)

    # ---------------- BETWEEN ----------------

    between_negated = False
    between_idx = None

    if "between" in tokens:
        b_idx = tokens.index("between")
        between_idx = b_idx
        nums_after = [w for w in tokens[b_idx:] if w.isdigit()]
        if len(nums_after) >= 2:
            between_values = (nums_after[0], nums_after[1])
            between_negated = is_negated(tokens, b_idx, window=3)

    between_nums = set(between_values) if between_values else set()

    # ---------------- NUMERIC COLUMN RESOLUTION ----------------
    # numeric_column = the aggregate/sort target ("average SALARY", "highest MARKS")
    # condition_column = the WHERE-comparison column ("marks ABOVE 80", "joined SINCE 2015")
    # These can differ (e.g. "average salary ... since 2015" aggregates
    # salary but filters on joining_year), so they're resolved independently.

    numeric_candidates = []
    for i, word in enumerate(tokens):
        # Check for dotted column names (e.g., employees.salary)
        col_key = word
        if '.' in word:
            parts = word.split('.')
            if len(parts) == 2 and parts[1] in COLUMN_MAP:
                col_key = parts[1]
        if col_key in COLUMN_MAP and COLUMN_MAP[col_key] not in CATEGORICAL_COLUMNS:
            numeric_candidates.append((i, COLUMN_MAP[col_key]))

    def nearest_column(anchor_idx):
        if anchor_idx is None or not numeric_candidates:
            return None
        return min(
            numeric_candidates, key=lambda c: abs(c[0] - anchor_idx)
        )[1]

    # numeric_column: anchor on the aggregate word, else the highest/lowest
    # word, else just the last numeric-looking column mentioned
    sort_anchor_idx = None
    if aggregate_idx is not None:
        sort_anchor_idx = aggregate_idx
    elif record_condition_idx is not None:
        sort_anchor_idx = record_condition_idx

    if sort_anchor_idx is not None:
        numeric_column = nearest_column(sort_anchor_idx)
    elif numeric_candidates:
        numeric_column = numeric_candidates[-1][1]

    # condition_column: date words (before/after/since/till/until) always
    # mean the joining/hiring year, regardless of any other column mentioned
    if value_condition_word in DATE_TRIGGER_WORDS:
        condition_column = "joining_year"
    else:
        value_anchor_idx = value_condition_idx if value_condition_idx is not None else between_idx
        condition_column = nearest_column(value_anchor_idx)

    # "older/younger than" implies an age comparison even when the word
    # "age" itself is never mentioned - applies generally, not just inside
    # an ANY/ALL clause
    if "older" in tokens or "younger" in tokens:
        if condition_column is None:
            condition_column = "age"
        if numeric_column is None:
            numeric_column = "age"

    # ---------------- TOP / FIRST N / BOTTOM / LAST N ----------------
    # (computed before the generic number scan so its digit token can be
    # excluded from being treated as a WHERE comparison value)

    limit_value_idx = None

    for keyword in ["top", "first", "bottom", "last"]:
        if keyword in tokens:
            idx = tokens.index(keyword)
            for i, word in enumerate(tokens[idx:idx + 3], start=idx):
                if word.isdigit():
                    limit_value = word
                    limit_value_idx = i
                    break

    if limit_value is None and record_condition in ("highest", "lowest") and record_condition_idx is not None:
        window_start = max(0, record_condition_idx - 2)
        window_end = record_condition_idx + 3
        for i, word in enumerate(tokens[window_start:window_end], start=window_start):
            if word.isdigit():
                limit_value = word
                limit_value_idx = i
                break

    # ---------------- EXPLICIT LIMIT ----------------

    if limit_value is None and "limit" in tokens:
        idx = tokens.index("limit")
        for i, word in enumerate(tokens[idx:idx + 3], start=idx):
            if word.isdigit():
                limit_value = word
                limit_value_idx = i
                break

    # ---------------- NUMBER (generic comparison value) ----------------

    for i, word in enumerate(tokens):
        if word.isdigit() and word not in between_nums and i != limit_value_idx:
            value = word

    # a numeric comparison alongside a GROUP BY + aggregate/count belongs in
    # HAVING (applied after grouping), not WHERE (applied before) - this
    # covers both "... having more than 2 ..." and "... average marks are
    # greater than 80" phrasings
    condition_is_having = bool(
        group_by_column and (aggregate_function or intent == "count")
        and value_condition in ("above", "below", "gte", "lte") and value
    )

    # ---------------- DEPARTMENT ----------------

    for i, word in enumerate(tokens):
        if word in DEPARTMENTS:
            department_values.append((word.upper(), is_negated(tokens, i)))

    # ---------------- CITY ----------------

    for i, word in enumerate(tokens):
        if word in CITIES:
            city_values.append((word.title(), is_negated(tokens, i)))

    # ---------------- GENDER ----------------

    for i, word in enumerate(tokens):
        if word in GENDERS:
            gender_values.append((word.capitalize(), is_negated(tokens, i)))

    # ---------------- NAME ----------------

    if "named" in tokens:

        idx = tokens.index("named")

        if idx + 1 < len(tokens):
            name_value = tokens[idx + 1].capitalize()

    # ---------------- NULL CONDITION ----------------

    null_column = None
    null_negated = False

    for i, word in enumerate(tokens):
        if word in NULL_TRIGGER_WORDS:
            null_negated = is_negated(tokens, i, window=3)

            # the column can appear either before ("null marks") or after
            # ("missing department") the trigger word
            backward_window = tokens[max(0, i - 3):i]
            for w in backward_window:
                if w in COLUMN_MAP:
                    null_column = COLUMN_MAP[w]

            if null_column is None:
                forward_window = tokens[i + 1:i + 4]
                for w in forward_window:
                    if w in COLUMN_MAP:
                        null_column = COLUMN_MAP[w]
                        break
            break

    if null_column is None and "no" in tokens:
        idx = tokens.index("no")
        if idx + 1 < len(tokens):
            next_word = tokens[idx + 1]
            if next_word in COLUMN_MAP:
                null_column = COLUMN_MAP[next_word]

    # ---------------- NO TABLE (for relationships) ----------------
    no_table = None
    if "no" in tokens:
        idx = tokens.index("no")
        if idx + 1 < len(tokens):
            next_word = tokens[idx + 1]
            if next_word in TABLE_MAP:
                no_table = TABLE_MAP[next_word]

    if no_table and no_table != table:
        # Find a relationship between table and no_table
        found = False
        for local_table, local_col, foreign_table, foreign_col in RELATIONSHIPS:
            if local_table == no_table and foreign_table == table:
                # no_table has a foreign key to table
                conditions.append(f"NOT EXISTS (SELECT 1 FROM {no_table} WHERE {no_table}.{local_col} = {table}.{foreign_col})")
                found = True
                break
            elif local_table == table and foreign_table == no_table:
                # table has a foreign key to no_table
                conditions.append(f"NOT EXISTS (SELECT 1 FROM {no_table} WHERE {no_table}.{foreign_col} = {table}.{local_col})")
                found = True
                break
        if not found:
            # Fallback: try to use SHARED_COLUMN? But we don't know.
            # For now, do nothing and maybe the query will be wrong.
            pass

     # ---------------- EXISTS ----------------

    exists_second_table = None
    exists_column = SHARED_COLUMN

    if any(w in tokens for w in EXISTS_TRIGGER_WORDS):
        tables_found_exists = []
        for word in tokens:
            if word in TABLE_MAP and TABLE_MAP[word] not in tables_found_exists:
                tables_found_exists.append(TABLE_MAP[word])

        if len(tables_found_exists) >= 2:
            table = tables_found_exists[0]
            exists_second_table = tables_found_exists[1]

        # the column both tables should match on - the first COLUMN_MAP
        # word anywhere in the sentence, defaulting to department if none
        # is mentioned at all
        for word in tokens:
            if word in COLUMN_MAP:
                exists_column = COLUMN_MAP[word]
                break

    # ---------------- ANY / ALL ----------------

    any_all_keyword = None
    any_all_sub_table = None
    any_all_sub_column = None

    for i, word in enumerate(tokens):
        if word in ANY_ALL_TRIGGER_WORDS:
            any_all_keyword = ANY_ALL_TRIGGER_WORDS[word]
            # the comparison table is whichever TABLE_MAP word appears at
            # or after ANY/ALL (e.g. "... ANY EMPLOYEE in HR" -> employees);
            # falls back to the same table as the main query if none found
            for t in tokens[i:]:
                if t in TABLE_MAP:
                    any_all_sub_table = TABLE_MAP[t]
                    break

            # the column being compared INSIDE the subquery isn't
            # necessarily the same as the outer column - "salary above any
            # STUDENT MARKS" compares employees.salary against
            # students.marks, not students.salary. Look for a column word
            # after the ANY/ALL keyword; only fall back to reusing the
            # outer condition_column if the sentence never names one.
            for t in tokens[i:]:
                if t in COLUMN_MAP and COLUMN_MAP[t] not in CATEGORICAL_COLUMNS:
                    any_all_sub_column = COLUMN_MAP[t]
                    break

    # ---------------- CASE ----------------
    # e.g. "label employees as high earner if salary above 50000 else low earner"

    case_label_true = None
    case_label_false = None
    case_column = None
    case_operator = None
    case_value = None

    if any(w in tokens for w in CASE_TRIGGER_WORDS) and "if" in tokens and "else" in tokens:
        if_idx = tokens.index("if")
        else_idx = tokens.index("else")

        if "as" in tokens:
            as_idx = tokens.index("as")
            if as_idx < if_idx:
                case_label_true = " ".join(tokens[as_idx + 1:if_idx]).strip()

        condition_tokens = tokens[if_idx + 1:else_idx]
        for word in condition_tokens:
            if word in COLUMN_MAP and COLUMN_MAP[word] not in CATEGORICAL_COLUMNS:
                case_column = COLUMN_MAP[word]
            if word in CONDITION_MAP and CONDITION_MAP[word] in VALUE_CONDITION_TYPES:
                case_operator = CONDITION_MAP[word]
            if word.isdigit():
                case_value = word

        case_label_false = " ".join(tokens[else_idx + 1:]).strip()

    is_case_query = bool(
        case_column and case_operator and case_value and case_label_true and case_label_false
    )
    if is_case_query:
        # This condition belongs to the CASE expression, not a WHERE
        # filter - the whole point of a label is to bucket every row into
        # one branch or the other, not exclude rows from the result.
        value_condition = None
        value = None

    # ---------------- NULL FUNCTIONS (IFNULL / COALESCE) ----------------
    # e.g. "show salary or 0 if salary is null", "replace missing department with unknown"

    ifnull_column = None
    ifnull_default = None

    if "replace" in tokens and "missing" in tokens and "with" in tokens:
        missing_idx = tokens.index("missing")
        with_idx = tokens.index("with")

        if missing_idx + 1 < len(tokens):
            candidate_col = tokens[missing_idx + 1]
            if candidate_col in COLUMN_MAP:
                ifnull_column = COLUMN_MAP[candidate_col]

        if with_idx + 1 < len(tokens):
            ifnull_default = tokens[with_idx + 1]

    elif "null" in tokens and "or" in tokens:
        or_idx = tokens.index("or")

        if or_idx > 0 and tokens[or_idx - 1] in COLUMN_MAP:
            ifnull_column = COLUMN_MAP[tokens[or_idx - 1]]

        if or_idx + 1 < len(tokens):
            ifnull_default = tokens[or_idx + 1]

    # ---------------- LIKE ----------------

    like_trigger_idx = None

    for i, word in enumerate(tokens):
        if word in LIKE_KEYWORDS:
            like_trigger_idx = i
            like_mode = "contains"
            break
        if word in STARTS_KEYWORDS:
            like_trigger_idx = i
            like_mode = "starts"
            break
        if word in ENDS_KEYWORDS:
            like_trigger_idx = i
            like_mode = "ends"
            break

    if like_trigger_idx is not None:

        like_negated = is_negated(tokens, like_trigger_idx, window=3)

        # nearest text-like column mentioned before the trigger word
        text_candidates = [
            (i, word) for i, word in enumerate(tokens[:like_trigger_idx])
            if word in COLUMN_MAP
        ]

        if text_candidates:
            like_column = COLUMN_MAP[text_candidates[-1][1]]
        else:
            like_column = "name"

        for word in tokens[like_trigger_idx + 1:]:
            if word.isalpha() and word not in LIKE_FILLER_WORDS:
                like_pattern = word.capitalize() if like_column == "name" else word
                break

    # ---------------- ORDER BY ----------------

    for i, word in enumerate(tokens):
        if word in ORDER_TRIGGER_WORDS:
            order_requested = True
            window_start = max(0, i - 3)
            window = tokens[window_start:i] + tokens[i:i + 6]
            for w in window:
                if w in COLUMN_MAP:
                    order_by_column = COLUMN_MAP[w]
                if w in SORT_DIRECTION_MAP:
                    order_by_direction = SORT_DIRECTION_MAP[w]
            break

    # ---------------- SELECTED COLUMNS ("show name and marks of students") ----------------

    STOP_WORDS_FOR_COLUMNS = {
        "where", "whose", "having",
        "between",
        "above", "below", "over", "under", "greater", "less", "more",
        "order", "sort", "arrange",
        "limit",
        "like", "contains", "containing", "starting", "starts", "ending", "ends",
        "on",  # Stop at JOIN conditions
    }

    # Map generic column names to table-specific column names when needed
    TABLE_NAME_COLUMN = {
        "departments": "department_name",
        "courses": "course_name",
        "teachers": "teacher_name",
        # students and employees already have "name" column
        # enrollments and attendance have no meaningful "name" column
    }

    selected_columns = []

    intent_word_idx = None
    for i, word in enumerate(tokens):
        if word in SELECT_INTENT_WORDS:
            intent_word_idx = i
            break

    if intent_word_idx is not None and intent != "count" and aggregate_function is None:

        end_idx = len(tokens)
        for i in range(intent_word_idx + 1, len(tokens)):
            if tokens[i] in STOP_WORDS_FOR_COLUMNS:
                end_idx = i
                break

        # A value immediately followed by its own category name -
        # "bangalore CITY", "hr DEPARTMENT", "male GENDER" - is the value
        # being described, not that column being requested. Without this,
        # "get name of employees from bangalore city" would incorrectly
        # select both name AND city, when only name was actually asked for.
        DESCRIPTOR_VALUE_LISTS = {"city": CITIES, "department": DEPARTMENTS, "gender": GENDERS}

        # Reset for this query
        selected.clear()
        selected_columns.clear()
        for i, word in enumerate(tokens[intent_word_idx + 1:end_idx], start=intent_word_idx + 1):
            if i in join_related_indices:
                continue
            # Check for dotted column names (e.g., students.name)
            col_key = word
            src_table_guess = None
            if '.' in word:
                parts = word.split('.')
                if len(parts) == 2 and parts[1] in COLUMN_MAP:
                    col_key = parts[1]
                    src_table_guess = parts[0]  # could be table name or alias
            if col_key in COLUMN_MAP:
                col = COLUMN_MAP[col_key]
                # Determine source table for this column
                src_table = None
                # If we have a src_table_guess from dotted notation, use it if it's a known table
                if src_table_guess and src_table_guess in TABLE_MAP:
                    src_table = TABLE_MAP[src_table_guess]
                # Handle special case for "name"/"names" where preceding table name indicates the column's table
                elif word in ("name", "names"):
                    if i > 0 and tokens[i-1] in TABLE_MAP:
                        prev_table_word = tokens[i-1]
                        prev_table = TABLE_MAP[prev_table_word]
                        if prev_table in TABLE_NAME_COLUMN:
                            col = TABLE_NAME_COLUMN[prev_table]
                            src_table = prev_table
                        else:
                            # No special mapping, column belongs to the preceding table
                            src_table = prev_table
                    else:
                        # No preceding table word; use current table context
                        src_table = table
                        if table and table in TABLE_NAME_COLUMN:
                            col = TABLE_NAME_COLUMN[table]
                else:
                    # For other columns, check if preceding token is a table name
                    if i > 0 and tokens[i-1] in TABLE_MAP:
                        src_table = TABLE_MAP[tokens[i-1]]
                    else:
                        src_table = table
                # If we still don't have a source table, default to the main table
                if src_table is None:
                    src_table = table
                # Skip if this column is merely describing a value (e.g., "bangalore CITY")
                prev_word = tokens[i - 1] if i > 0 else None
                value_list = DESCRIPTOR_VALUE_LISTS.get(col)
                if value_list is not None and prev_word in value_list:
                    continue
                # Avoid duplicate (column, source_table) entries
                if (col, src_table) not in selected:
                    selected.append((col, src_table))
                    selected_columns.append(col)
            # Debug print
            print("DEBUG: selected:", selected)

        # Build select_parts from selected (column, source_table) tuples
        if selected:
            select_parts = []
            for col, src in selected:
                # Apply column aliases if any
                if col in column_aliases:
                    alias = column_aliases[col]
                    if second_table:
                        select_parts.append(f"{src}.{col} AS {alias}")
                    else:
                        select_parts.append(f"{col} AS {alias}")
                else:
                    if second_table:
                        select_parts.append(f"{src}.{col}")
                    else:
                        select_parts.append(col)
            select_columns_sql = ", ".join(select_parts)
        else:
            select_columns_sql = "*"

    # ---------------- ALIASES (AS) ----------------
    # e.g. "show salary as pay" -> SELECT salary AS pay

    for i, word in enumerate(tokens):
        if word == "as" and i > 0 and i + 1 < len(tokens):
            prev_word = tokens[i - 1]
            if prev_word in COLUMN_MAP:
                column_aliases[COLUMN_MAP[prev_word]] = tokens[i + 1]

    # Rebuild select_columns_sql with aliases applied
    if selected:
        select_parts = []
        for col, src in selected:
            if col in column_aliases:
                alias = column_aliases[col]
                if second_table:
                    select_parts.append(f"{src}.{col} AS {alias}")
                else:
                    select_parts.append(f"{col} AS {alias}")
            else:
                if second_table:
                    select_parts.append(f"{src}.{col}")
                else:
                    select_parts.append(f"{src}.{col}")
        select_columns_sql = ", ".join(select_parts)
    else:
        select_columns_sql = "*"

    # ---------------- DEFAULT NUMERIC COLUMN ----------------

    if not numeric_column:

        if table == "students":
            numeric_column = "marks"

        elif table == "employees":
            numeric_column = "salary"

    if order_requested and not order_by_column:
        order_by_column = numeric_column

    if condition_column is None:
        condition_column = numeric_column

    # ---------------- DEFAULT EQUAL ----------------

    if value and value_condition is None:
        value_condition = "equal"

    use_in = "or" in tokens or "in" in tokens
    has_not_in = "not in" in question

    # ---------------- OR CONDITION (true OR across different conditions) ----------------
    # A plain "IT or HR" list for one categorical column is already handled
    # as an IN (...) clause above (via department_values/city_values/
    # gender_values + use_in) - this block only kicks in when " or " joins
    # two genuinely different conditions (different columns, or a numeric
    # comparison), which the IN path can't express. When it does trigger,
    # it replaces the whole WHERE clause with the OR expression - other
    # AND-style filters in the same sentence aren't combined with it.

    or_where_clause = None

    if " or " in question:
        or_parts = question.split(" or ")

        if len(or_parts) >= 2:
            parsed_or_conditions = []

            for part in or_parts:
                part_tokens = word_tokenize(part)
                part_tokens = words_to_numbers(part_tokens)
                cond = parse_or_clause(part_tokens, default_column=numeric_column)
                if cond:
                    parsed_or_conditions.append(cond)

            if len(parsed_or_conditions) >= 2:
                cols_in_or = {c.split(" ")[0] for c in parsed_or_conditions}
                all_equality = all(" = " in c for c in parsed_or_conditions)
                same_column_list = (len(cols_in_or) == 1 and all_equality)

                if not same_column_list:
                    or_where_clause = " OR ".join(parsed_or_conditions)

    # ---------------- BUILD CONDITIONS ----------------

    # department only for employees
    if table == "employees":
        dept_condition = build_categorical_condition(
            "department", department_values, use_in, not_in=has_not_in
        )
        if dept_condition:
            conditions.append(dept_condition)

    city_condition = build_categorical_condition(
        "city", city_values, use_in, not_in=has_not_in
    )
    if city_condition:
        conditions.append(city_condition)

    gender_condition = build_categorical_condition(
        "gender", gender_values, use_in, not_in=has_not_in
    )
    if gender_condition:
        conditions.append(gender_condition)

    if subject_value and table == "students":
        conditions.append(
            f"subject = '{subject_value}'"
        )

    if name_value:
        conditions.append(
            f"name = '{name_value}'"
        )

    if null_column:
        null_keyword = "IS NOT NULL" if null_negated else "IS NULL"
        conditions.append(f"{null_column} {null_keyword}")

    # ---------------- LIKE CONDITION ----------------

    if like_column and like_pattern:

        if like_mode == "starts":
            pattern_sql = f"{like_pattern}%"
        elif like_mode == "ends":
            pattern_sql = f"%{like_pattern}"
        else:
            pattern_sql = f"%{like_pattern}%"

        like_keyword = "NOT LIKE" if like_negated else "LIKE"
        conditions.append(f"{like_column} {like_keyword} '{pattern_sql}'")

    # ---------------- NUMERIC CONDITIONS ----------------

    if between_values:
        between_keyword = "NOT BETWEEN" if between_negated else "BETWEEN"
        conditions.append(
            f"{condition_column} {between_keyword} {between_values[0]} AND {between_values[1]}"
        )

    elif value_condition == "above" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} > {value}"
        )

    elif value_condition == "below" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} < {value}"
        )

    elif value_condition == "on_or_after" and value:
        conditions.append(
            f"{condition_column} >= {value}"
        )

    elif value_condition == "on_or_before" and value:
        conditions.append(
            f"{condition_column} <= {value}"
        )

    elif value_condition == "equal" and value:
        conditions.append(
            f"{condition_column} = {value}"
        )

    elif value_condition == "gte" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} >= {value}"
        )

    elif value_condition == "lte" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} <= {value}"
        )

    # ---------------- WHERE ----------------

    where_clause = ""

    if or_where_clause:
        where_clause = f" WHERE ({or_where_clause})"
    elif conditions:
        where_clause = (
            " WHERE " +
            " AND ".join(conditions)
        )

    # ---------------- GROUP BY ----------------

    group_by_clause = ""

    if group_by_column:
        group_by_clause = f" GROUP BY {group_by_column}"


        # ---------------- HAVING ----------------

    having_clause = ""

    if condition_is_having:
        op_symbol_map = {"above": ">", "below": "<", "gte": ">=", "lte": "<="}
        having_agg = "COUNT(*)" if intent == "count" else f"{aggregate_function}({numeric_column})"
        having_clause = f" HAVING {having_agg} {op_symbol_map[value_condition]} {value}"


    # ---------------- ORDER BY / LIMIT (for the default / non-aggregate paths) ----------------

    order_by_clause = ""
    limit_clause = ""

    if record_condition is None:

        if order_requested and order_by_column:
            order_by_clause = f" ORDER BY {order_by_column} {order_by_direction}"

        if limit_value:
            limit_clause = f" LIMIT {limit_value}"

            # ---------------- JOIN QUERY ----------------

    if second_table:

        # Handle FULL OUTER JOIN simulation using UNION of LEFT and RIGHT joins
        if join_type == "FULL OUTER":
            # Determine which columns to join on
            if join_columns:
                cols_to_join = join_columns
            elif table in TABLES_WITH_CITY and second_table in TABLES_WITH_CITY:
                cols_to_join = [SHARED_COLUMN]
            else:
                # No common join column; use cross join (no ON clause)
                cols_to_join = []

            # Build SELECT clause - handle specific columns or wildcard
            if select_columns_sql == "*":
                select_cols = f"{table}.*, {second_table}.*"
            else:
                select_cols = select_columns_sql

            # Build the ON clause for the join
            if cols_to_join:
                on_clause = " AND ".join(f"{table}.{c} = {second_table}.{c}" for c in cols_to_join)
            else:
                on_clause = ""  # For cross join style

            # Build each part of the query
            # LEFT JOIN part
            left_join_part = f"FROM {table} LEFT JOIN {second_table}"
            if on_clause:
                left_join_part += f" ON {on_clause}"
            if where_clause:
                left_join_part += f" {where_clause}"

            # RIGHT JOIN part
            right_join_part = f"FROM {table} RIGHT JOIN {second_table}"
            if on_clause:
                right_join_part += f" ON {on_clause}"
            if where_clause:
                right_join_part += f" {where_clause}"

            # Build GROUP BY, HAVING, ORDER BY, LIMIT clauses that apply to the final result
            extra_clauses = f"{group_by_clause}{having_clause}{order_by_clause}{limit_clause}"

            if cols_to_join:
                # Standard case: we have specific columns to join on
                return f"""
        SELECT {select_cols}
        {left_join_part}
        UNION
        SELECT {select_cols}
        {right_join_part}
        {extra_clauses}
        """.strip()
            else:
                # No join columns - simulate FULL OUTER JOIN using UNION of CROSS JOINs
                # This is equivalent to (table1 CROSS JOIN table2) UNION (table1 CROSS JOIN table2)
                # which is just table1 CROSS JOIN table2, but we follow the pattern for consistency
                cross_join_part = f"FROM {table} CROSS JOIN {second_table}"
                if where_clause:
                    cross_join_part += f" {where_clause}"

                return f"""
        SELECT {select_cols}
        {cross_join_part}
        {extra_clauses}
        """.strip()

        if join_type == "CROSS JOIN":
            join_clause = f" CROSS JOIN {second_table}"   # no ON - true Cartesian product
        else:
            # Determine which columns to join on
            if join_columns:
                cols_to_join = join_columns
            elif table in TABLES_WITH_CITY and second_table in TABLES_WITH_CITY:
                cols_to_join = [SHARED_COLUMN]
            else:
                # No common join column; use cross join (no ON clause)
                join_clause = f" CROSS JOIN {second_table}"
                # Skip the rest of the join processing for this case
                join_select_cols = f"{table}.*, {second_table}.*" if select_columns_sql == "*" else select_columns_sql
                return f"""
        SELECT {join_select_cols}
        FROM {table}
        {join_clause}
        {where_clause}
        {group_by_clause}{having_clause}{order_by_clause}{limit_clause}
        """.strip()

            # If we have columns to join on, build the ON clause
            on_clause = " AND ".join(f"{table}.{c} = {second_table}.{c}" for c in cols_to_join)
            join_clause = f" {join_type} {second_table} ON {on_clause}"

        join_select_cols = f"{table}.*, {second_table}.*" if select_columns_sql == "*" else select_columns_sql

        return f"""
        SELECT {join_select_cols}
        FROM {table}
        {join_clause}
        {where_clause}
        {group_by_clause}{having_clause}{order_by_clause}{limit_clause}
        """.strip()

    # ---------------- UNION QUERY ----------------

    # Columns (and WHERE conditions, further below) that actually exist on
    # BOTH students and employees - same set the JOIN logic already treats
    # as the only safe cross-table columns (see SHARED_COLUMN above). Kept
    # as an ordered list (not a set) so the default "show everything safe"
    # case below always renders columns in the same, predictable order.
    UNION_SHARED_COLUMNS = ["id", "name", "age", "gender", "city"]

    if union_second_table:

        # SELECT * across two differently-shaped tables would break a UNION
        # (mismatched column counts). If specific columns were genuinely
        # requested, keep only the ones valid on both sides (e.g. "marks"
        # or "salary" only exist on one table and would error out on the
        # other). If NOTHING was requested (or nothing requested survived
        # that filter), default to every column common to both tables -
        # as close to "show everything" as a UNION can safely get, rather
        # than an arbitrary single column.
        if selected_columns:
            safe_cols = [c for c in selected_columns if c in UNION_SHARED_COLUMNS]
        else:
            safe_cols = []
        union_cols = ", ".join(safe_cols) if safe_cols else ", ".join(UNION_SHARED_COLUMNS)

        union_keyword = "UNION ALL" if union_all else "UNION"

        # Only reuse WHERE conditions built on columns common to both
        # tables (city/gender/age/name/id) - department, marks, salary,
        # subject, joining_year, etc. are table-specific and would error
        # out on whichever side of the UNION doesn't have that column.
        union_safe_conditions = [
            c for c in conditions
            if c.split(" ")[0] in UNION_SHARED_COLUMNS
        ]
        union_where = ""
        if union_safe_conditions:
            union_where = " WHERE " + " AND ".join(union_safe_conditions)

        return f"""
        SELECT {union_cols} FROM {table}{union_where}
        {union_keyword}
        SELECT {union_cols} FROM {union_second_table}{union_where}
        """.strip()

    # ---------------- CASE QUERY ----------------

    if case_column and case_operator and case_value and case_label_true and case_label_false:

        op_symbol_map = {"above": ">", "below": "<", "equal": "=", "gte": ">=", "lte": "<="}
        op_symbol = op_symbol_map.get(case_operator, "=")

        case_sql = (
            f"CASE WHEN {case_column} {op_symbol} {case_value} "
            f"THEN '{case_label_true}' ELSE '{case_label_false}' END AS category"
        )

        return f"""
        SELECT *, {case_sql}
        FROM {table}
        {where_clause}
        """.strip()

    # ---------------- IFNULL / COALESCE QUERY ----------------

    if ifnull_column and ifnull_default:

        default_sql = ifnull_default if ifnull_default.isdigit() else f"'{ifnull_default}'"

        return f"""
        SELECT IFNULL({ifnull_column}, {default_sql}) AS {ifnull_column}
        FROM {table}
        """.strip()

    # ---------------- EXISTS QUERY ----------------

    if exists_second_table:

        exists_where = (
            f" WHERE EXISTS (SELECT 1 FROM {exists_second_table} "
            f"WHERE {exists_second_table}.{exists_column} = {table}.{exists_column})"
        )

        return f"""
        SELECT {select_columns_sql}
        FROM {table}
        {exists_where}
        """.strip()

    # ---------------- ANY / ALL QUERY ----------------

    if any_all_keyword and value_condition in ("above", "below", "gte", "lte") and condition_column:

        op_symbol_map = {"above": ">", "below": "<", "gte": ">=", "lte": "<="}
        sub_table = any_all_sub_table if any_all_sub_table else table
        sub_column = any_all_sub_column if any_all_sub_column else condition_column

        # scope the subquery to whichever qualifier was mentioned -
        # department, city, or a specific semester number - falling back
        # to no filter (compare against every row of sub_table) if none
        scope_column = None
        scope_value = None

        if department_values:
            scope_column = "department"
            scope_value = f"'{department_values[-1][0]}'"
        elif city_values:
            scope_column = "city"
            scope_value = f"'{city_values[-1][0]}'"
        elif "semester" in tokens:
            sem_idx = tokens.index("semester")
            for t in tokens[sem_idx:sem_idx + 3]:
                if t.isdigit():
                    scope_column = "semester"
                    scope_value = t
                    break

        sub_where = f" WHERE {scope_column} = {scope_value}" if scope_column else ""

        any_all_where = (
            f" WHERE {condition_column} {op_symbol_map[value_condition]} {any_all_keyword} "
            f"(SELECT {sub_column} FROM {sub_table}{sub_where})"
        )

        return f"""
        SELECT {select_columns_sql}
        FROM {table}
        {any_all_where}
        """.strip()

    # ---------------- DISTINCT ----------------

    if aggregate_function == "DISTINCT":

        distinct_column = None

        for word in tokens:

            if word in COLUMN_MAP:
                distinct_column = COLUMN_MAP[word]

        if distinct_column:

            return f"""
            SELECT DISTINCT {distinct_column}
            FROM {table}
            {where_clause}
            """.strip()

    # ---------------- AVG / SUM / MIN / MAX ----------------

    if aggregate_function in ("AVG", "SUM", "MIN", "MAX"):

        select_cols = f"{aggregate_function}({numeric_column})"

        if group_by_column:
            select_cols = f"{group_by_column}, {select_cols}"

        # "average salary of top 4 employees", "sum of marks of bottom 3
        # students", etc: the aggregate should run over just the top/bottom
        # N rows (ranked by numeric_column), not the whole table. A plain
        # LIMIT on the outer aggregate query wouldn't do anything - an
        # aggregate always collapses the result to a single row - so this
        # needs a subquery: rank + limit first, then aggregate over that
        # subset. Only applies when there's no GROUP BY; "top N rows
        # overall" and "grouped by department/city/etc" are two different
        # requests that don't currently combine.
        if record_condition in ("highest", "lowest") and limit_value and not group_by_column:
            sort_dir = "DESC" if record_condition == "highest" else "ASC"
            subquery = (
                f"SELECT * FROM {table}"
                f"{where_clause}"
                f" ORDER BY {numeric_column} {sort_dir}"
                f" LIMIT {limit_value}"
            )
            return f"""
            SELECT {select_cols}
            FROM ({subquery}) AS top_rows
            """.strip()

        return f"""
        SELECT {select_cols}
        FROM {table}
        {where_clause}{group_by_clause}{having_clause}
        """.strip()

    # ---------------- COUNT ----------------

    if intent == "count":

        select_cols = "COUNT(*)"

        if group_by_column:
            select_cols = f"{group_by_column}, COUNT(*)"

        return f"""
        SELECT {select_cols}
        FROM {table}
        {where_clause}{group_by_clause}{having_clause}
        """.strip()

    # ---------------- HIGHEST ----------------

    if record_condition == "highest":

        limit_n = limit_value if limit_value else "1"

        return f"""
        SELECT {select_columns_sql}
        FROM {table}
        {where_clause}
        ORDER BY {numeric_column} DESC
        LIMIT {limit_n}
        """.strip()

    # ---------------- LOWEST ----------------

    if record_condition == "lowest":

        limit_n = limit_value if limit_value else "1"

        return f"""
        SELECT {select_columns_sql}
        FROM {table}
        {where_clause}
        ORDER BY {numeric_column} ASC
        LIMIT {limit_n}
        """.strip()

    # ---------------- DEFAULT SELECT ----------------

    return f"""
    SELECT {select_columns_sql}
    FROM {table}
    {where_clause}{order_by_clause}{limit_clause}
    """.strip()