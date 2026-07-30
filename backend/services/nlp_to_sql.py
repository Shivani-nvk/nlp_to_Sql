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

SELECT_INTENT_WORDS = ["show", "display", "list"]

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

    "below": "below",
    "less": "below",
    "under": "below",

    "highest": "highest",
    "top": "highest",

    "lowest": "lowest",
    "least": "lowest",
    "bottom": "lowest",
    "last": "lowest",

    "equal": "equal",
    "equals": "equal",
    "is": "equal",

    "before": "below",
    "after": "above",

    "since": "on_or_after",
    "till": "on_or_before",
    "until": "on_or_before"
}

# CONDITION_MAP values that pick a *record* (ORDER BY ... LIMIT), as opposed
# to a WHERE comparison value
RECORD_CONDITION_TYPES = {"highest", "lowest"}

# CONDITION_MAP values that build a WHERE numeric comparison
VALUE_CONDITION_TYPES = {"above", "below", "equal", "on_or_after", "on_or_before"}

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
    "staff": "employees"
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

    # common
    "id": "id",
    "ids": "id",
    "age": "age",
    "ages": "age",
    "department": "department",
    "departments": "department",
    "dept": "department",
    "depts": "department",
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


def convert_to_sql(question):

    question = question.lower()
    tokens = word_tokenize(question)
    tokens = words_to_numbers(tokens)

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
        if word in TABLE_MAP:
            table = TABLE_MAP[word]
            if table_word_idx is None:
                table_word_idx = i

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
        if word in CONDITION_MAP:
            mapped = CONDITION_MAP[word]

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
        for keyword in ["by", "per"]:
            if keyword in tokens:
                idx = tokens.index(keyword)
                if idx + 1 < len(tokens):
                    next_word = tokens[idx + 1]
                    if next_word in COLUMN_MAP:
                        group_by_column = COLUMN_MAP[next_word]

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

    numeric_candidates = [
        (i, COLUMN_MAP[word])
        for i, word in enumerate(tokens)
        if word in COLUMN_MAP and COLUMN_MAP[word] not in CATEGORICAL_COLUMNS
    ]

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
                if w in COLUMN_MAP and COLUMN_MAP[w] not in CATEGORICAL_COLUMNS:
                    order_by_column = COLUMN_MAP[w]
                if w in SORT_DIRECTION_MAP:
                    order_by_direction = SORT_DIRECTION_MAP[w]
            break

    # ---------------- SELECTED COLUMNS ("show name and marks of students") ----------------

    STOP_WORDS_FOR_COLUMNS = {
        "where", "whose", "with", "having",
        "between",
        "above", "below", "over", "under", "greater", "less", "more",
        "order", "sort", "arrange",
        "limit",
        "like", "contains", "containing", "starting", "starts", "ending", "ends",
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

        for word in tokens[intent_word_idx + 1:end_idx]:
            if word in COLUMN_MAP:
                col = COLUMN_MAP[word]
                if col not in selected_columns:
                    selected_columns.append(col)

    select_columns_sql = ", ".join(selected_columns) if selected_columns else "*"

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

    elif value_condition == "above" and value:
        conditions.append(
            f"{condition_column} > {value}"
        )

    elif value_condition == "below" and value:
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

    # ---------------- WHERE ----------------

    where_clause = ""

    if conditions:
        where_clause = (
            " WHERE " +
            " AND ".join(conditions)
        )

    # ---------------- GROUP BY ----------------

    group_by_clause = ""

    if group_by_column:
        group_by_clause = f" GROUP BY {group_by_column}"

    # ---------------- ORDER BY / LIMIT (for the default / non-aggregate paths) ----------------

    order_by_clause = ""
    limit_clause = ""

    if record_condition is None:

        if order_requested and order_by_column:
            order_by_clause = f" ORDER BY {order_by_column} {order_by_direction}"

        if limit_value:
            limit_clause = f" LIMIT {limit_value}"

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

        return f"""
        SELECT {select_cols}
        FROM {table}
        {where_clause}{group_by_clause}
        """.strip()

    # ---------------- COUNT ----------------

    if intent == "count":

        select_cols = "COUNT(*)"

        if group_by_column:
            select_cols = f"{group_by_column}, COUNT(*)"

        return f"""
        SELECT {select_cols}
        FROM {table}
        {where_clause}{group_by_clause}
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