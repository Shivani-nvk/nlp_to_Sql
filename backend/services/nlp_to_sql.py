# Shivani's part

import re

import nltk
from nltk.tokenize import word_tokenize

from services.schema_service import get_schema, get_primary_keys

try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    nltk.download("punkt_tab", quiet=True)

# Comparison phrases for merge_comparison_phrases(), pre-computed once at
# module load so they aren't rebuilt on every /query call. Longest phrases
# first, so e.g. "...or more than" matches whole before the shorter
# "or more" tail could match it partially.
_AT_LEAST_PHRASES = [
    ("at", "least"),
    ("equal", "to", "or", "more", "than"),
    ("equal", "to", "or", "greater", "than"),
    ("equal", "to", "and", "more", "than"),
    ("equal", "to", "and", "greater", "than"),
    ("greater", "than", "or", "equal", "to"),
    ("more", "than", "or", "equal", "to"),
    ("or", "more"),
    ("or", "greater"),
]
_AT_MOST_PHRASES = [
    ("at", "most"),
    ("equal", "to", "or", "less", "than"),
    ("equal", "to", "or", "lesser", "than"),
    ("equal", "to", "and", "less", "than"),
    ("equal", "to", "and", "lesser", "than"),
    ("less", "than", "or", "equal", "to"),
    ("lesser", "than", "or", "equal", "to"),
    ("or", "less"),
    ("or", "fewer"),
]
_ALL_PHRASES = sorted(
    [(p, "AT_LEAST") for p in _AT_LEAST_PHRASES] + [(p, "AT_MOST") for p in _AT_MOST_PHRASES],
    key=lambda pair: -len(pair[0])
)

# ---------------- INTENT MAP ----------------

INTENT_MAP = {
    "show": "select",
    "display": "select",
    "list": "select",
    "count": "count",
    # "the number of students per course" is a COUNT that happens to be
    # phrased as a noun phrase instead of a verb
    "number": "count",
    "numbers": "count",
}

SELECT_INTENT_WORDS = ["show", "display", "list", "get", "find"]

# ---------------- AGGREGATE MAP ----------------

AGGREGATE_MAP = {
    "average": "AVG",
    "avg": "AVG",

    "sum": "SUM",
    "total": "SUM",

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
    "higher": "above",
    "exceed": "above",
    "exceeds": "above",
    "exceeding": "above",
    "exceeded": "above",

    "below": "below",
    "less": "below",
    "lesser": "below",
    "under": "below",
    "lower": "below",

    "highest": "highest",
    "top": "highest",
    "highest-paid": "highest",
    "highest paid": "highest",

    "lowest": "lowest",
    "least": "lowest",
    "bottom": "lowest",
    "last": "lowest",
    "lowest-paid": "lowest",
    "lowest paid": "lowest",

    "equal": "equal",
    "equals": "equal",
    "is": "equal",

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

# words that unambiguously signal a numeric comparison ("x GREATER than
# the average y"). Plain "is"/"equals" is excluded so "what IS the average
# salary" stays a plain aggregate, not salary = (SELECT AVG ...).
STRONG_COMPARISON_WORDS = {
    "above", "greater", "more", "over", "higher",
    "below", "less", "lesser", "under", "lower",
    "before", "after", "since", "till", "until",
    "older", "younger",
    "AT_LEAST", "AT_MOST",
}

# raw trigger words that are always about the joining/hiring date, regardless
# of which column word (if any) happens to sit nearby
DATE_TRIGGER_WORDS = {"before", "after", "since", "till", "until"}

# ---------------- LIVE SCHEMA (authoritative) ----------------
# Mirrors the real nlp_db schema so the engine still works when the database
# is unreachable (the maps below are refreshed from information_schema on
# every conversion, see refresh_schema_maps(), but a lot of rules need to
# know what a table CONTAINS before that refresh can be relied on).
#
#   student_info (Student_ID, Student_Name, Course_ID, Address, Phone_No)
#   course       (Course_ID, Course_Name)
#   department   (Department_ID, Department_Name)
#   subject      (Subject_ID, Subject_Name, Course_ID, Semester, Max_Marks)
#   marks        (Student_ID, Subject_ID, Exam, Marks, Result)
#   employee_info(Employee_ID, Employee_Name, Department_ID, Address, Phone_No)
#   project      (Project_ID, Project_Name, Department_ID, Start_Year, Budget)
#   performance  (Employee_ID, Project_ID, Rating, Result)
#
# Every key here is lower snake_case because questions are lowercased
# before they are looked up, and the generated SQL relies on MySQL's
# case-insensitive column names to bridge "student_name" -> Student_Name.
STATIC_TABLE_COLUMNS = {
    "student_info": {"student_id", "student_name", "course_id", "address", "phone_no"},
    "course": {"course_id", "course_name"},
    "department": {"department_id", "department_name"},
    "subject": {"subject_id", "subject_name", "course_id", "semester", "max_marks"},
    "marks": {"student_id", "subject_id", "exam", "marks", "result"},
    "employee_info": {"employee_id", "employee_name", "department_id", "address", "phone_no"},
    "project": {"project_id", "project_name", "department_id", "start_year", "budget"},
    "performance": {"employee_id", "project_id", "rating", "result"},
}

# The human-readable name column of each table. "name" is an abstract keyword
# ("show the names of ...") that has to land on whichever of these the
# question is actually about - the old schema had a literal `name` column on
# employees, this one names every table with a <thing>_name column.
NAME_COLUMN_BY_TABLE = {
    "student_info": "student_name",
    "employee_info": "employee_name",
    "subject": "subject_name",
    "course": "course_name",
    "department": "department_name",
    "project": "project_name",
}
DEFAULT_NAME_COLUMN = "employee_name"


def table_columns(table):
    """
    Lower-cased column set for one table, read from the live schema when it
    is reachable and from STATIC_TABLE_COLUMNS otherwise.

    Used to keep rules from emitting columns a table doesn't have - e.g. a
    department filter must be dropped for student_info, which has no
    Department_ID, instead of generating SQL that errors out.
    """
    try:
        columns = get_schema().get(table, {})
        if columns:
            return {c.lower() for c in columns}
    except Exception:
        pass
    return set(STATIC_TABLE_COLUMNS.get(table, ()))


def resolve_column(column, table):
    """
    Maps an abstract keyword onto a real column of `table`. Only "name" is
    abstract - it means "the name column of whatever this question is
    about" - every other canonical column is already a real column name.
    """
    if column == "name":
        return NAME_COLUMN_BY_TABLE.get(table, DEFAULT_NAME_COLUMN)
    return column


# The numeric column each table falls back to when a question asks for a
# ranking or an aggregate without naming a column ("the highest project",
# "average marks per subject"). Every table in the live schema has one.
DEFAULT_NUMERIC_COLUMN = {
    "student_info": "student_id",
    "course": "course_id",
    "department": "department_id",
    "subject": "max_marks",
    "marks": "marks",
    "employee_info": "employee_id",
    "project": "project_id",
    "performance": "rating",
}


# which column each table's date-word comparison should target ("projects
# started after 2024" -> project.Start_Year). Auto-syncs with new tables
# only when a column's MySQL type is DATE/DATETIME/TIMESTAMP.
DATE_COLUMNS = {
    "project": "start_year",
}

# ---------------- TABLE MAP ----------------

TABLE_MAP = {
    # student_info (Student_ID, Student_Name, Course_ID, Address, Phone_No)
    "student": "student_info",
    "students": "student_info",
    "stu": "student_info",
    "pupil": "student_info",
    "pupils": "student_info",
    "undergraduate": "student_info",
    "undergraduates": "student_info",

    # employee_info (Employee_ID, Employee_Name, Department_ID, Address, Phone_No)
    "employee": "employee_info",
    "employees": "employee_info",
    "emp": "employee_info",
    "staff": "employee_info",
    "worker": "employee_info",
    "workers": "employee_info",
    "personnel": "employee_info",

    # department (Department_ID, Department_Name)
    "department": "department",
    "departments": "department",
    "dept": "department",
    "depts": "department",

    # subject (Subject_ID, Subject_Name, Course_ID, Semester, Max_Marks)
    "subject": "subject",
    "subjects": "subject",
    "subj": "subject",

    # course (Course_ID, Course_Name)
    "course": "course",
    "courses": "course",

    # marks (Student_ID, Subject_ID, Exam, Marks, Result)
    "mark": "marks",
    "marks": "marks",
    "exam": "marks",
    "exams": "marks",
    "test": "marks",
    "tests": "marks",
    "result": "marks",
    "results": "marks",
    "score": "marks",
    "scores": "marks",
    "grade": "marks",
    "grades": "marks",

    # project (Project_ID, Project_Name, Department_ID, Start_Year, Budget)
    "project": "project",
    "projects": "project",

    # performance (Employee_ID, Project_ID, Rating, Result)
    "performance": "performance",
    "performances": "performance",
    "rating": "performance",
    "ratings": "performance",
}

# ---------------- COLUMN MAP ----------------

COLUMN_MAP = {

    # marks (the Exam / Result / Marks values proper to the marks table;
    # `Result` is also a column on performance, so one keyword serves both)
    "marks": "marks",
    "mark": "marks",
    "score": "marks",
    "scores": "marks",
    "grade": "marks",
    "grades": "marks",
    "exam": "exam",
    "exams": "exam",
    "examination": "exam",
    "examinations": "exam",
    "test": "exam",
    "tests": "exam",
    "result": "result",
    "results": "result",
    "outcome": "result",
    "outcomes": "result",

    # student_info
    "student_id": "student_id",
    "studentid": "student_id",
    "student_number": "student_id",
    "roll": "student_id",
    "roll_no": "student_id",
    "student_name": "student_name",
    "students_name": "student_name",
    "address": "address",
    "addresses": "address",
    "phone_no": "phone_no",
    "phone": "phone_no",
    "phones": "phone_no",
    "phone_number": "phone_no",
    "contact": "phone_no",
    "mobile": "phone_no",
    "mob": "phone_no",

    # course
    "course_id": "course_id",
    "courseid": "course_id",
    "course_name": "course_name",
    "coursename": "course_name",
    "courses": "course_id",
    "program": "course_name",
    "programs": "course_name",
    "programme": "course_name",
    "programmes": "course_name",
    "title": "course_name",

    # department
    "department": "department",
    "departments": "department",
    "dept": "department",
    "depts": "department",
    "department_name": "department_name",
    "department_names": "department_name",
    "department_id": "department_id",

    # subject
    "subject_id": "subject_id",
    "subjectid": "subject_id",
    "subject_name": "subject_name",
    "subjectname": "subject_name",
    "paper": "subject_name",
    "papers": "subject_name",
    "semester": "semester",
    "semesters": "semester",
    "sem": "semester",
    "term": "semester",
    "terms": "semester",
    "max_marks": "max_marks",
    "maxmark": "max_marks",
    "maximum_marks": "max_marks",
    "out_of": "max_marks",

    # employee_info
    "employee_id": "employee_id",
    "employeeid": "employee_id",
    "employee_name": "employee_name",
    "employees_name": "employee_name",
    "emp_name": "employee_name",

    # performance
    "rating": "rating",
    "ratings": "rating",
    "score_rating": "rating",
    "performance_rating": "rating",
    "star": "rating",
    "stars": "rating",

    # project
    "project_name": "project_name",
    "projects_name": "project_name",
    "project_id": "project_id",
    "budget": "budget",
    "budgets": "budget",
    "cost": "budget",
    "costs": "budget",
    "spending": "budget",
    "spend": "budget",
    "expense": "budget",
    "expenses": "budget",
    "start_year": "start_year",
    "year": "start_year",
    "years": "start_year",
    "started": "start_year",
    "starting_year": "start_year",
    "began": "start_year",
    "begun": "start_year",
    "launched": "start_year",
    "commenced": "start_year",

    # shared by student_info and employee_info
    "location": "address",
    "locations": "address",
    "place": "address",
    "places": "address",
    "city": "address",
    "cities": "address",
    "town": "address",
    "towns": "address",

    # abstract: resolved to the queried table's real name column
    "name": "name",
    "names": "name",

    # common
    "id": "id",
    "ids": "id",
}

# columns that should never be treated as the "numeric_column" used in
# aggregates / above / below / equal / highest / lowest - text/category
# columns (address, phone_no, every *_name, exam, result, ...) aren't
# numeric even though some numeric-looking id columns exist. Foreign-key/id
# columns (student_id, department_id, ...) ARE allowed as comparison targets,
# so they're deliberately NOT in this list.
CATEGORICAL_COLUMNS = [
    "name", "department",
    "address", "phone_no",
    "student_name", "employee_name", "subject_name", "course_name",
    "department_name", "project_name",
    "exam", "result",
]

# Categorical columns that make sense as a GROUP BY target on their own, used
# by the implicit "cities where average marks..." pattern when the question
# names no by/per/each keyword. "department" is abstract and resolved to
# department_name (or department_id) depending on the table being queried.
GROUPABLE_CATEGORICAL_COLUMNS = {
    "department", "address",
    "exam", "result",
    "semester",
    "course_id", "subject_id", "project_id",
    "rating",
    # readable variants that only exist once the table they name is joined in
    "department_name",
}

# Columns that scope a question rather than describe what to display. "show
# subjects of semester 3" is a request for subjects filtered to semester 3,
# not for a projection of the semester column - so a bare occurrence behind
# "of/in/for/from/with" is a filter, not a SELECT item. The table's own
# foreign keys are deliberately absent: "show the course id of each student"
# really is asking for course_id, and the "of" rule would swallow it.
FILTER_ONLY_COLUMNS = frozenset({
    "semester", "exam", "result", "rating", "address", "department_name",
})

# Tables whose row is identified by a name column that the engine can filter
# on, plus which column that is. `None` for the table means the name column
# isn't reachable from that table alone.
NAME_COLUMN_FOR_TABLE = NAME_COLUMN_BY_TABLE

# Words that name data this database simply does not have (no salary, age,
# gender, email, joining date, deadline, ...). They are deliberately NOT
# added to COLUMN_MAP, so a question about them can't produce a plausible-
# looking but wrong filter against some unrelated numeric column. Instead
# they're recorded here, and has_recognizable_keywords() reports the question
# as unrecognised so the agentic engine answers it against the real schema.
UNSUPPORTED_CONCEPT_WORDS = {
    "age", "ages", "aged", "older", "younger", "birth", "birthday", "dob",
    "salary", "salaries", "pay", "paid", "wage", "wages", "ctc", "compensation",
    "email", "emails", "mail", "gender", "genders", "male", "female", "sex",
    "experience", "experienced", "joining", "joined", "hired", "hiring",
    "manager", "managers", "manager_id", "reporting", "reports_to",
    "cgpa", "gpa", "sgpa", "attendance", "present", "credits", "credit",
    "blood_group", "blood", "scholarship", "guardian", "deadline", "deadlines",
    "due", "due_date", "active", "inactive", "is_active",
}

# Filled in by convert_to_sql() when the question asks for one of the
# concepts above, so the confidence check can send it to the AI layer.
# Reset at the start of every conversion, exactly like
# UNRESOLVED_ENTITY_TOKENS.
UNSUPPORTED_CONCEPT_TOKENS = set()

# Filled in by convert_to_sql() when the question is well understood but asks
# for something this single-table rule engine structurally cannot express -
# e.g. "departments with more than 2 employees" (a COUNT of one table grouped
# by a column of another, which needs a derived table) or "students ranked by
# marks" across three tables. Emitting a plausible-looking but wrong LIMIT
# instead would be worse than saying "I can't do this one"; the agentic layer
# gets the real schema and can build it properly. Reset every conversion, like
# UNSUPPORTED_CONCEPT_TOKENS.
ESCALATION_REASONS = set()

# ---------------- AUTO-SYNC WITH THE LIVE DATABASE ----------------
# The keyword maps above are the hand-curated baseline (the natural-language
# synonyms people actually use). On top of that, refresh_schema_maps() pulls
# every table/column name straight out of the live schema (via
# schema_service.get_schema(), itself cached) and derives automatic keywords
# for them - the raw snake_case name, its singular form for tables, the
# space-separated form of multi-word columns, and the base noun of *_id
# foreign-key columns. The result is merged INTO the module-level dicts in
# place, so anything that imported them (query_refiner, hybrid_router, ...)
# sees the freshly-synced keywords too.
#
# Because it runs on every rule-based conversion and only rebuilds when the
# schema fingerprint actually changes, a table or column added through the
# admin panel (or directly in MySQL) becomes queryable with no code changes:
#   CREATE TABLE courses (...);        -> "courses" + its columns are known
#   ALTER TABLE students ADD cgpa;     -> "cgpa" becomes a recognised word
#   ALTER TABLE exams ADD conducted_on DATE; -> date comparisons resolve
#                                          to exams.conducted_on

# MySQL column types that hold numbers. Everything else (VARCHAR, TEXT,
# DATE, ...) is treated as categorical/text - not a numeric comparison target.
NUMERIC_TYPE_PREFIXES = (
    "int", "integer", "tinyint", "smallint", "mediumint", "bigint",
    "decimal", "numeric", "float", "double", "real",
)

DATE_TYPE_PREFIXES = ("date", "datetime", "timestamp")

_schema_maps_fingerprint = None

# Real contents of low-cardinality text columns, e.g.
#   {"student_info": {"Student_Name": ["Ananya Singh", ...]},
#    "marks":        {"Exam": ["Internal 1", "Semester"], "Result": [...]}}
# Populated from the live database by refresh_column_values() and used to
# ground name/category literals. The keyword maps above know that a column
# called Student_Name holds a student; only this knows it holds "Ananya
# Singh" and not "Ananya", which is the difference between a WHERE clause
# that matches and one that silently returns nothing.
COLUMN_VALUES = {}


def refresh_column_values():
    """
    Pulls the real values of low-cardinality text columns into COLUMN_VALUES
    (mutated in place, same contract as the other maps). Safe to call on
    every conversion: the underlying sampler is cached, and an unreachable
    database simply leaves the map empty so the engine falls back to its
    static keyword behaviour.
    """
    try:
        from services.schema_service import get_column_values
        sampled = get_column_values()
    except Exception:
        return

    COLUMN_VALUES.clear()
    COLUMN_VALUES.update(sampled)


# Tokens that are function words or query grammar rather than entity names.
# A token in here is never treated as a name even if it happens to be a
# substring of some stored value.
_NAME_STOP_WORDS = {
    "show", "display", "list", "get", "find", "give", "tell", "fetch",
    "all", "any", "each", "every", "who", "whom", "whose", "which", "what",
    "the", "a", "an", "and", "or", "of", "for", "with", "in", "on", "at",
    "to", "from", "by", "as", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "me", "my", "please",
    "student", "students", "employee", "employees", "staff", "person",
    "people", "name", "names", "named", "called", "details", "detail",
    "info", "information", "record", "records", "row", "rows", "data",
    "only", "just", "also", "please", "there", "their", "them", "his", "her",
    "more", "most", "less", "least", "very", "much", "many", "total",
    "average", "count", "number", "sum", "max", "min", "highest", "lowest",
    "top", "bottom", "first", "last", "new", "old", "up", "down", "out",
    # grammar/query words that are also real values elsewhere in the schema
    "result", "results", "resulting", "internal", "final", "midterm",
    "semester", "course", "courses", "subject", "subjects",
    "project", "projects", "department", "departments", "performance",
    # past-tense verbs that follow the noun they modify ("the maximum marks
    # SCORED", "the highest budget SPENT") - without these the verb reads as a
    # person's name and produces a `name = 'Scored'` filter that silently
    # empties the result
    "scored", "spent", "earned", "awarded", "received", "obtained",
    "scoring", "spending", "earning", "awarding", "receiving",
    "obtained", "achieved", "held", "set", "given", "taken", "made",
    "belonging", "belonged", "assigned", "assigned", "joined", "ranked",
}


def _find_entity_match(token, tables=None):
    """
    Looks a bare question token up against the real column values and
    returns (table, column, stored_value, is_exact) if it names a row that
    actually exists, else None.

    Matching is per-WORD, not per-substring: the token has to equal a whole
    word of a stored value. Loose substring matching produced nonsense -
    "age" matched inside "Database Management Systems", "ananya" would have
    matched inside an unrelated value - and would have turned ordinary
    column questions into name filters. Per-word still gives the two cases
    that matter: the user said a whole word of a longer name ("ananya" for
    "Ananya Singh", "singh" for "Ananya Singh") or the exact value.

    Only true name columns are ever searched (see _NAME_COLUMNS_BY_TABLE), so
    a token can't be mistaken for a non-name value - without that, "show
    students from bengaluru" would match the Address value 'Bengaluru' and
    filter student_name by it.

    `tables` narrows the search to specific tables. Callers that only care
    about naming a *person* pass _PERSON_NAME_TABLES, which keeps
    "show ananya marks" escalating to the AI layer without also dragging
    every subject/course/project question there.

    is_exact is False when the token matched only part of a longer stored
    value, which is the signal that the filter has to be a LIKE rather than
    an equality - `= 'ananya'` would match nothing.
    """
    if not token or not token.isalpha() or len(token) < 3:
        return None
    if token in _NAME_STOP_WORDS:
        return None

    lowered = token.lower()
    best = None

    # A word that is a known COLUMN keyword is never a row name. "which project
    # has the lowest budget" contains a project literally called "Budget
    # Forecast", so without this the name matcher would claim "budget" and emit
    # `project_name LIKE '%Budget Forecast%'` alongside the real ORDER BY
    # budget - filtering to the wrong project entirely.
    if lowered in COLUMN_MAP:
        return None

    # People write possessives. Stored values never carry one, and matching is
    # whole-word exact, so "ananyas" matched nothing at all and the word was
    # then dropped as unknown - the question came back as an unfiltered
    # SELECT * over every mark row. Strip the ending and try again; the plain
    # word is always tried first, so this only ever adds matches.
    for candidate_word in (lowered, _strip_possessive(lowered)):
        if not candidate_word or len(candidate_word) < 3:
            continue
        for candidate_table, columns in COLUMN_VALUES.items():
            if candidate_table == "app_users":
                continue
            if tables is not None and candidate_table not in tables:
                continue
            for column in _NAME_COLUMNS_BY_TABLE.get(candidate_table, ()):
                for value in columns.get(column, ()):
                    if candidate_word == value.lower():
                        return candidate_table, column, value, True
                    if candidate_word in (w.lower() for w in value.split()):
                        # Prefer the shortest stored value that contains the
                        # token, so "singh" resolves to the one row it names
                        # rather than an arbitrary longer name.
                        if best is None or len(value) < len(best[2]):
                            best = (candidate_table, column, value, False)

    return best


def _strip_possessive(word):
    """
    Returns the bare form of an English possessive, or "" when there isn't
    one. "ananyas" -> "ananya", "amit's" -> "amit", "students" -> "student".
    Deliberately conservative about the length so a short word cannot be
    stripped into something meaningless.
    """
    if not word or len(word) < 5 or not word.isalpha():
        return ""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("es") and not word.endswith("ses"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return ""



# Tables whose name column identifies a *person*. The bare-name filter and
# its AI escalation are scoped to these on purpose: "show ananya marks" and
# "show ravi" are the questions this exists to fix, and scoping it here
# keeps unrelated questions ("students taking Computer Science", where
# "computer" is a word of a course name) on the rule engine as before.
_PERSON_NAME_TABLES = ("student_info", "employee_info")

# Comparison words whose NEXT token is a comparison target, not a filter.
# "salary greater than Amit" already resolves through the named-person
# subquery path, so the bare-name filter must not also fire on "Amit" and
# add a redundant `name = 'Amit'` alongside the subquery.
_COMPARISON_LEAD_WORDS = frozenset({
    "above", "below", "than", "greater", "less", "higher", "lower",
    "exceed", "exceeds", "exceeding", "under", "more", "most", "lesser",
})


# Which column stores the human-readable name in each table. A name filter
# may only ever be built against one of these, and a bare token is only
# treated as a name when it matches one of their values. Keys are the REAL
# column names as information_schema reports them - COLUMN_VALUES is keyed
# the same way, since that map is read straight out of the database.
_NAME_COLUMNS_BY_TABLE = {
    "student_info": ("Student_Name",),
    "employee_info": ("Employee_Name",),
    "subject": ("Subject_Name",),
    "course": ("Course_Name",),
    "department": ("Department_Name",),
    "project": ("Project_Name",),
}


def _match_name_span(tokens, start, tables=None):
    """
    Resolves the run of tokens at `start` to one stored name value, or None.

    A name is routinely more than one word - "CRM Migration", "Budget
    Forecast", "Bengaluru Road" - and reading a single token turns the
    comparison into `project_name = 'Crm'`, which matches no row at all and
    returns nothing. The longest span that is a real stored value wins, so a
    two-word name is never truncated to the one word the user happened to
    start with.

    Returns the stored value verbatim, which is what makes the equality
    correct: 'CRM Migration' as spelled in the database, not as re-capitalised
    from the question.
    """
    if start >= len(tokens):
        return None

    # Longest span first, so a two-word name is preferred over the one-word
    # value it happens to contain. Bounded by what is actually left in the
    # sentence - "greater than CRM Migration" ends there.
    for length in range(min(4, len(tokens) - start), 0, -1):
        span = tokens[start:start + length]
        if any(not w.isalpha() for w in span):
            break
        phrase = " ".join(span)
        for table, columns in COLUMN_VALUES.items():
            if table == "app_users":
                continue
            if tables is not None and table not in tables:
                continue
            for column in _NAME_COLUMNS_BY_TABLE.get(table, ()):
                for value in columns.get(column, ()):
                    if value.lower() == phrase:
                        return value
    return None


# Tokens from the most recent convert_to_sql() call that name a row which
# really exists, but which the rule engine could not filter on because the
# row lives in a different table than the one the question resolved to
# ("show ananya marks" - the name is in student_info, the question is about
# marks, and answering it needs a JOIN the engine's single-table filter here
# cannot build). Recorded rather than acted on, because has_recognizable_
# keywords() reads it to decide the rule engine is not confident and the AI
# layer should take over - which it can do, now that it is given the real
# values. Reset at the start of every conversion so it can never go stale.
UNRESOLVED_ENTITY_TOKENS = set()

# The question UNRESOLVED_ENTITY_TOKENS was computed for, so a confidence
# check that runs without a preceding conversion in this process knows to
# run one first instead of reading another question's leftovers.
_last_converted_question = None

# Bumped by every convert_to_sql() call. Paired with the SQL of that call, it
# lets the confidence gate reuse a conversion only when it really is the one
# for the question in hand - the question name alone is not enough, because a
# direct convert_to_sql() call in the same process overwrites the question
# without the gate's cached SQL ever being refreshed.
_conversion_serial = 0
_LAST_CONVERTED = (None, 0, "")




def _singular(word):
    """Best-effort English singular: students -> student, classes -> class,
    courses -> course, exams -> exam, results -> result."""
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ses"):
        return word[:-2]
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def _schema_fingerprint(schema):
    return tuple(sorted(
        (table, tuple(sorted(columns)))
        for table, columns in schema.items()
    ))


def refresh_schema_maps():
    """
    Re-derives the automatic keyword entries from the live schema and merges
    them into TABLE_MAP / COLUMN_MAP / CATEGORICAL_COLUMNS /
    MULTIWORD_COLUMN_PHRASES / DATE_COLUMNS (each mutated in place so
    existing references stay valid). Hand-curated words always win on a
    conflict.

    When the schema is unreachable (e.g. DB not running), the human-curated
    baseline is left untouched - the rule engine just keeps working with the
    static maps.
    """
    global _schema_maps_fingerprint

    try:
        schema = get_schema()
    except Exception:
        return

    fingerprint = _schema_fingerprint(schema)
    if fingerprint == _schema_maps_fingerprint:
        return
    _schema_maps_fingerprint = fingerprint

    table_words = {}
    column_words = {}
    categorical = []
    multiword = {}
    date_columns = {}

    for table, columns in schema.items():
        if table == "app_users":
            continue  # auth table is never a valid NLP target

        table_words[table] = table
        table_words[_singular(table)] = table

        for column in columns:
            # questions are lowercased before lookup, so every derived
            # keyword has to be lowercased too - the live schema is mixed
            # case (Student_ID, Employee_Name, Max_Marks) and an
            # auto-synced "Max_Marks" key could never match a token
            key = column.lower()
            dtype = (columns[column] or "").lower().split("(")[0].strip()
            is_numeric = dtype.startswith(NUMERIC_TYPE_PREFIXES)
            if key not in date_columns and dtype.startswith(DATE_TYPE_PREFIXES):
                date_columns[table] = key

            column_words[key] = key
            if "_" in key:
                multiword[key.replace("_", " ")] = key
            if key.endswith("_id") and len(key) > 3:
                column_words[key[:-3]] = key
            if not is_numeric and key not in categorical:
                categorical.append(key)

    # Human-curated entries override the auto-derived ones on collision.
    merged_tables = dict(table_words)
    merged_tables.update(TABLE_MAP)
    TABLE_MAP.clear()
    TABLE_MAP.update(merged_tables)

    merged_columns = dict(column_words)
    merged_columns.update(COLUMN_MAP)
    COLUMN_MAP.clear()
    COLUMN_MAP.update(merged_columns)

    known_categorical = set(CATEGORICAL_COLUMNS)
    for col in categorical:
        if col not in known_categorical:
            CATEGORICAL_COLUMNS.append(col)
            known_categorical.add(col)

    known_phrases = set(MULTIWORD_COLUMN_PHRASES)
    for phrase, column in multiword.items():
        if phrase not in known_phrases:
            MULTIWORD_COLUMN_PHRASES[phrase] = column
            known_phrases.add(phrase)

    merged_dates = dict(date_columns)
    merged_dates.update(DATE_COLUMNS)
    DATE_COLUMNS.clear()
    DATE_COLUMNS.update(merged_dates)

# ---------------- DEPARTMENTS ----------------
# The four rows of the `department` table, plus the spelling variants people
# actually type. department_display() maps a matched word back to the exact
# string stored in department.Department_Name - a plain .upper() would turn
# "finance" into 'FINANCE', which matches no row in that column, so the
# resulting query would run cleanly and return nothing.

DEPARTMENT_DISPLAY_VALUES = {
    "hr": "HR",
    "human resources": "HR",
    "human resource": "HR",
    "it": "IT",
    "information technology": "IT",
    "finance": "Finance",
    "financial": "Finance",
    "marketing": "Marketing",
}

# Words that happen to be a stored value but are never one when they appear in
# a sentence. "it" is a department name AND the pronoun, so "the department it
# belongs to" was matching the IT department and quietly restricting the whole
# answer to IT - twice over, once per "it" in the sentence. A literal value
# has to be something the user chose to name, not a word the grammar needed.
NON_LITERAL_WORDS = {
    "it", "its", "it's", "this", "that", "these", "those",
    "he", "she", "they", "them", "their", "theirs", "his", "her",
    "in", "on", "at", "to", "for", "of", "by", "with", "from",
    "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "a", "an", "as", "all", "any", "some", "no", "not",
}

# The subset of the above that is ALSO a value stored in a lookup column.
# "it" is the only one: IT is a department, and "it" is the pronoun.
_AMBIGUOUS_VALUE_WORDS = {"it", "its"}

# ...unless the word is doing a modifier's job. "the IT department" names the
# department; "the department it belongs to" does not. Only one stored value
# collides with a function word, so only that one gets an exception.
_MODIFIER_NOUNS = {
    "department", "departments", "dept", "depts",
    "branch", "branches", "team", "teams", "division", "divisions",
}
_VALUE_PREPOSITIONS = {"in", "from", "of", "at", "within", "inside"}

# A copula introduces a value exactly as a preposition does. "whose department
# IS IT" names the department just as "who work IN IT" does, and without this
# the word reads as the pronoun, the filter is dropped, and "Find employees
# whose department is IT" answers with every employee in the company.
_VALUE_COPULAS = {"is", "are", "was", "were", "be", "been", "equals", "="}

# Separators between items of a spoken list. "HR, IT, or Finance" tokenizes
# with the commas intact, so only the first item sits next to the preposition
# that introduced the list and every later item looks like an ordinary word.
_LIST_SEPARATORS = {",", "or", "and", "nor"}


def _known_value_words():
    """
    Every word that is a stored value in some lookup column, so a list item can
    recognise that it is standing next to its siblings.

    Resolved at call time because the vocabularies below are defined after this
    function.
    """
    words = set(DEPARTMENTS) | set(CITIES) | set(GENDERS)
    words |= set(CATEGORICAL_VALUE_COLUMN)
    return words


def _is_literal_value(word, tokens, index):
    """
    True when `word` at `tokens[index]` is naming a stored value rather than
    filling a grammatical slot.
    """
    if word not in NON_LITERAL_WORDS:
        return True
    if word not in _AMBIGUOUS_VALUE_WORDS:
        return False

    # "the IT department" - the word modifies the noun, so it is a name.
    after = tokens[index + 1] if index + 1 < len(tokens) else None
    if after in _MODIFIER_NOUNS:
        return True

    # "...whose department is IT" / "...whose department is not IT" - a copula
    # introduces the value in the same way, so look back through the negation.
    j = index - 1
    while j >= 0 and tokens[j] in ("not", "n't"):
        j -= 1
    if j >= 0 and tokens[j] in _VALUE_COPULAS:
        # "...whose department is it in" puts the word inside the
        # prepositional phrase that follows, so it is the object of "in"
        # rather than the value the copula introduces.
        return after not in _VALUE_PREPOSITIONS

    # "...in HR, IT, or Finance" - every item after the first is separated
    # from the preposition by a comma, so step back over the separators and
    # look at what the list as a whole was introduced by. A preposition
    # governs the whole list; so does a sibling value, since the list is
    # already known to be a list of names.
    j = index - 1
    while j >= 0 and tokens[j] in _LIST_SEPARATORS:
        j -= 1
    governor = tokens[j] if j >= 0 else None
    if governor in _VALUE_PREPOSITIONS or governor in _known_value_words():
        return True

    # "employees in IT" - a preposition introduces a bare value. The word
    # after it has to not be a verb, otherwise this is the object of one:
    # "the department it belongs to" is "it" followed by "belongs".
    before = tokens[index - 1] if index > 0 else None
    return before in _VALUE_PREPOSITIONS and after not in DATE_TRIGGER_WORDS


DEPARTMENTS = list(DEPARTMENT_DISPLAY_VALUES)

# ---------------- CITIES / ADDRESSES ----------------
# student_info.Address and employee_info.Address hold these city names, so
# "city" is just a synonym for address in this schema. city_display() maps a
# matched word (including the Bangalore/Bengaluru style variants people mix
# up) back to the exact stored spelling.

CITY_DISPLAY_VALUES = {
    "mysore": "Mysore",
    "mysuru": "Mysore",
    "bangalore": "Bangalore",
    "bengaluru": "Bangalore",
    "hubli": "Hubli",
    "hubballi": "Hubli",
    "davangere": "Davangere",
    "davangiri": "Davangere",
    "hassan": "Hassan",
    "mangalore": "Mangalore",
    "mangaluru": "Mangalore",
    "belgaum": "Belgaum",
    "belagavi": "Belgaum",
    "shimoga": "Shimoga",
    "shivamogga": "Shimoga",
    "tumkur": "Tumkur",
    "tumakuru": "Tumkur",
    "chikmagalur": "Chikmagalur",
    "chikmangalur": "Chikmagalur",
}

CITIES = list(CITY_DISPLAY_VALUES)


def department_display(word):
    return DEPARTMENT_DISPLAY_VALUES.get(word, word.capitalize())


def city_display(word):
    return CITY_DISPLAY_VALUES.get(word, word.title())


# ---------------- OTHER CATEGORICAL VALUES (exam / result) ----------------
# exam and result are the last two low-cardinality text columns with fixed
# vocabularies: marks.Exam holds Internal/Final/Midterm, marks.Result holds
# Pass/Fail, performance.Result holds Good/Average/Excellent. People say
# these in plain words ("the final exam", "students who passed", "excellent
# performance") and expect them to filter. As with departments, the spoken
# word has to be mapped back to the EXACT stored spelling - 'PASS' matches
# no row in a column holding 'Pass', so the query would run and return
# nothing. Semester is a number and needs no such map.
CATEGORICAL_VALUE_DISPLAY = {
    # marks.Exam
    "internal": "Internal",
    "final": "Final",
    "finals": "Final",
    "midterm": "Midterm",
    "mid": "Midterm",
    "term": "Midterm",
    # marks.Result
    "pass": "Pass",
    "passed": "Pass",
    "fail": "Fail",
    "failed": "Fail",
    # performance.Result
    "good": "Good",
    "excellent": "Excellent",
    "poor": "Good",
    "outstanding": "Excellent",
}

# Which of those words can filter which column, so "final" (an Exam value)
# can never produce `WHERE result = 'Final'` and "excellent" (a performance
# Result value) can never produce `WHERE exam = 'Excellent'`.
CATEGORICAL_VALUE_COLUMN = {
    "internal": "exam", "final": "exam", "finals": "exam",
    "midterm": "exam", "mid": "exam", "term": "exam",
    "pass": "result", "passed": "result",
    "fail": "result", "failed": "result",
    "good": "result", "excellent": "result",
    "poor": "result", "outstanding": "result",
}

CATEGORICAL_VALUE_WORDS = set(CATEGORICAL_VALUE_DISPLAY)


# ---------------- GENDERS ----------------
# There is no gender/sex column anywhere in this schema, so a "show female
# employees" question cannot be answered from the database. GENDERS stays
# defined (query_refiner imports it) but empty, which keeps the gender rule
# inert instead of it emitting a filter on a column that doesn't exist.

GENDERS = []

# ---------------- LIKE ----------------

LIKE_KEYWORDS = ["like", "contains", "containing"]
STARTS_KEYWORDS = ["starting", "starts", "start"]
ENDS_KEYWORDS = ["ending", "ends", "end"]
LIKE_FILLER_WORDS = {"with", "the", "in", "of"}

# ---------------- ORDER BY ----------------

ORDER_TRIGGER_WORDS = ["order", "ordered", "sort", "sorted", "arrange", "arranged"]

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
    # MySQL has no native FULL OUTER JOIN keyword - "FULL OUTER" is a
    # sentinel handled specially further down, emulated as a
    # LEFT JOIN UNION RIGHT JOIN rather than silently downgraded to a
    # plain LEFT JOIN.
    "outer": "FULL OUTER",
    "full": "FULL OUTER",
    "cross": "CROSS JOIN",
}

# The relational schema is two disconnected stars:
#
#   academic:  marks -> student_info -> course
#              marks -> subject     -> course
#   corporate: employee_info -> department
#              project     -> department
#              performance -> employee_info, project
#
# Every one of those edges is a real foreign key, so JOIN_KEY_MAP below
# carries the actual ON-clause for each pair. SHARED_COLUMN is only the
# last-ditch guess for a pair with no known relationship, and an id-ish
# shared column is preferred over it when the two tables happen to have one.
SHARED_COLUMN = "id"

# words that hint at a *second* join table even though they aren't TABLE_MAP
# keys themselves. These name the table a column/PK/FK word belongs to, so
# "student name along with their marks" can resolve the second table to marks.
# Words owned by more than one table (address, phone_no, course_id,
# student_id, result, department_id) are deliberately absent - resolving them
# would pick an arbitrary owner and produce a bogus join.
JOIN_TABLE_HINTS = {
    "student_name": "student_info",
    "subject_name": "subject",
    "subject_id": "subject",
    "semester": "subject",
    "max_marks": "subject",
    "course_name": "course",
    "marks": "marks",
    "exam": "marks",
    "employee_name": "employee_info",
    "employee_id": "employee_info",
    "department_name": "department",
    "department_id": "department",
    "project_name": "project",
    "project_id": "project",
    "budget": "project",
    "start_year": "project",
    "rating": "performance",
}

# natural-language verbs that semantically describe a row in one table
# belonging to a row in another ("students ... they are TAKING a subject",
# "projects ... the employee RATED it"). These signal a JOIN just like the
# explicit "along with" / "joined" words do, but only when the sentence does
# NOT use a count-style "at least one" construction (which demands an
# EXISTS subquery instead - see the EXISTS section). "at least" is collapsed
# to the AT_LEAST sentinel by merge_comparison_phrases before this runs.
JOIN_RELATION_VERBS = ["taking", "takes", "take", "took", "leading", "leads",
                       "led", "rated", "rates", "assigned", "assigned_to"]

# Preferred ON-columns for the relationships that actually exist between the
# tables, so "project names along with the employees rating them" joins ON
# performance.Employee_ID = employee_info.Employee_ID instead of a
# meaningless shared-column guess. Falls back to a schema-derived shared
# *_id column, then to SHARED_COLUMN, for a pair that isn't in this map.
JOIN_KEY_MAP = {
    ("marks", "student_info"): "marks.Student_ID = student_info.Student_ID",
    ("student_info", "marks"): "marks.Student_ID = student_info.Student_ID",

    ("marks", "subject"): "marks.Subject_ID = subject.Subject_ID",
    ("subject", "marks"): "marks.Subject_ID = subject.Subject_ID",

    ("subject", "course"): "subject.Course_ID = course.Course_ID",
    ("course", "subject"): "subject.Course_ID = course.Course_ID",

    ("student_info", "course"): "student_info.Course_ID = course.Course_ID",
    ("course", "student_info"): "student_info.Course_ID = course.Course_ID",

    ("student_info", "subject"): "student_info.Course_ID = subject.Course_ID",
    ("subject", "student_info"): "student_info.Course_ID = subject.Course_ID",

    ("employee_info", "department"): "employee_info.Department_ID = department.Department_ID",
    ("department", "employee_info"): "employee_info.Department_ID = department.Department_ID",

    ("project", "department"): "project.Department_ID = department.Department_ID",
    ("department", "project"): "project.Department_ID = department.Department_ID",

    ("performance", "employee_info"): "performance.Employee_ID = employee_info.Employee_ID",
    ("employee_info", "performance"): "performance.Employee_ID = employee_info.Employee_ID",

    ("performance", "project"): "performance.Project_ID = project.Project_ID",
    ("project", "performance"): "performance.Project_ID = project.Project_ID",
}


def build_join_on_clause(first, second, explicit_columns=None):
    """
    ON-clause for joining `first` to `second`, preferring the real foreign
    key, then any *_id column the two tables genuinely share, and only then
    SHARED_COLUMN. `explicit_columns` comes from an explicit "same <col>"
    phrase in the question and wins outright.
    """
    if explicit_columns:
        return " AND ".join(f"{first}.{c} = {second}.{c}" for c in explicit_columns)

    known_key = JOIN_KEY_MAP.get((first, second))
    if known_key:
        return known_key

    shared_ids = sorted(
        c for c in (table_columns(first) & table_columns(second))
        if c.endswith("_id")
    )
    if shared_ids:
        return " AND ".join(f"{first}.{c} = {second}.{c}" for c in shared_ids)

    return f"{first}.{SHARED_COLUMN} = {second}.{SHARED_COLUMN}"

# ---------------- NULL ----------------

NULL_TRIGGER_WORDS = ["null", "missing", "blank", "empty", "without"]

# The abstract relationship words, mapped to the local foreign key that can
# actually be NULL. Only usable when the driving table really carries the key:
# student_info has no department_id, so a "students without a department"
# question stays unexpressible rather than inventing the column.
NULLABLE_RELATION_COLUMN = {
    "department": "department_id",
}

# ---------------- HAVING ----------------

HAVING_TRIGGER_WORDS = ["having"]

# ---------------- EXISTS ----------------

EXISTS_TRIGGER_WORDS = ["exists", "exist", "belong", "belongs", "live", "lives", "lived", "leading", "leads", "assigned", "taking"]

# ---------------- ANY / ALL ----------------

# "every"/"each" mean ALL ("more than EVERY employee in HR"); "at least one"
# (the AT_LEAST + 1 sentinel pattern handled further down) means ANY.
ANY_ALL_TRIGGER_WORDS = {"any": "ANY", "all": "ALL", "every": "ALL", "each": "ALL"}

# Ordinal words that name a specific row in a highest/lowest ranking -
# "second-highest-paid employee" -> ORDER BY salary DESC LIMIT 1 OFFSET 1.
# Supports hyphenated forms ("third-highest") as well as plain words.
ORDINAL_MAP = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
}

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
    "million": 1000000,
    "billion": 1000000000,
    "lakh": 100000,
    "crore": 10000000,
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


def _is_number(word):
    """True for plain integers ('35') and decimal values ('4.5')."""
    if word.isdigit():
        return True
    return word.count(".") == 1 and word.replace(".", "", 1).isdigit()


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
        # "not from bangalore or mysore" / "not in bangalore and mysore" -
        # the negation governs the whole list, so this is a NOT IN list.
        # (A per-value negation like "from X but not Y" can't be expressed
        # as a single list and falls back to plain IN - acceptable edge.)
        keyword = "NOT IN" if (not_in or values[0][1]) else "IN"
        return f"{column} {keyword} ({in_list})"

    val, negated = values[-1]
    operator = "!=" if negated else "="
    return f"{column} {operator} '{val}'"


def build_department_id_condition(values, use_in, not_in=False):
    """
    Turns a spoken department name into a filter on a table's Department_ID
    column. employee_info and project store only the numeric Department_ID -
    the readable name lives on department.Department_Name - so the name has
    to be looked up:

        department_id IN (SELECT department_id FROM department
                          WHERE department_name IN ('HR', 'Finance'))
        department_id = (SELECT department_id FROM department
                         WHERE department_name = 'IT')
        department_id NOT IN (...)

    A plain `department_id = 1` would need the id to be hard-coded, which is
    exactly the kind of guess that silently returns the wrong rows.
    """
    if not values:
        return None

    lookup = "SELECT department_id FROM department WHERE department_name"

    if len(values) > 1 and use_in:
        in_list = ", ".join(f"'{v}'" for v, _ in values)
        keyword = "NOT IN" if (not_in or values[0][1]) else "IN"
        return f"department_id {keyword} ({lookup} IN ({in_list}))"

    val, negated = values[-1]
    if negated or not_in:
        return f"department_id NOT IN ({lookup} = '{val}')"
    return f"department_id = ({lookup} = '{val}')"


def parse_or_clause(tokens, default_column=None, table=None):
    """
    Parses one half of an 'X or Y' sentence into a single WHERE condition
    string, e.g. ['below', '40'] -> 'marks < 40', or
    ['in', 'mangalore'] -> "address = 'Mangalore'".

    `table` makes the categorical half schema-aware: a spoken department
    ("IT or HR") can only be compared on department.Department_Name, and a
    spoken city is really the Address column of student_info/employee_info.
    Without a table, those halves simply produce nothing rather than an
    invented "department"/"city" column that no table has.
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
        if word in DEPARTMENTS and table and "department_name" in table_columns(table):
            text_col = "department_name"
            text_val = department_display(word)
        if word in CITIES and table and "address" in table_columns(table):
            text_col = "address"
            text_val = city_display(word)
        if word in CONDITION_MAP and CONDITION_MAP[word] in VALUE_CONDITION_TYPES:
            operator_word = CONDITION_MAP[word]
        if _is_number(word):
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
    result = []
    i = 0
    n = len(tokens)

    while i < n:
        matched = False
        for phrase, sentinel in _ALL_PHRASES:
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


# Multi-word column names that the tokenizer splits apart, mapped to the
# single canonical column key they stand for. Matched over the raw text
# (lowest common denominator) BEFORE word_tokenize so e.g. "project names"
# becomes one token that the column scan can read as project_name.
MULTIWORD_COLUMN_PHRASES = {
    "student name": "student_name",
    "student names": "student_name",
    "students name": "student_name",
    "student id": "student_id",
    "student ids": "student_id",
    "student number": "student_id",
    "roll number": "student_id",
    "employee name": "employee_name",
    "employee names": "employee_name",
    "employees name": "employee_name",
    "employee id": "employee_id",
    "employee ids": "employee_id",
    "department name": "department_name",
    "department names": "department_name",
    "department id": "department_id",
    "project name": "project_name",
    "project names": "project_name",
    "project id": "project_id",
    "project ids": "project_id",
    "subject name": "subject_name",
    "subject names": "subject_name",
    "subject id": "subject_id",
    "course name": "course_name",
    "course names": "course_name",
    "course id": "course_id",
    "max marks": "max_marks",
    "maximum marks": "max_marks",
    "phone no": "phone_no",
    "phone nos": "phone_no",
    "phone number": "phone_no",
    "phone numbers": "phone_no",
    "start year": "start_year",
    "starting year": "start_year",
    "start years": "start_year",
    "performance rating": "rating",
    "project budget": "budget",
    "project department": "department",
    "employee department": "department",
}


def merge_multiword_columns(tokens):
    """
    Collapses known multi-word column phrases into a single token whose
    value IS the canonical column key (so it survives COLUMN_MAP lookups;
    the phrase words themselves aren't keys in COLUMN_MAP).
    """
    result = []
    i = 0
    n = len(tokens)

    # "max marks"/"maximum marks" is both a column name (subject.Max_Marks)
    # and an ordinary English aggregate ("the MAXIMUM marks a student
    # scored"). Folding it into the column token destroys the aggregate word,
    # so "what is the maximum marks" loses its MAX() and degrades to a plain
    # listing. It is only treated as the column when it is being compared
    # against a value ("max marks above 50") or listed as a column ("show
    # subjects and their max marks"); in a superlative question with nothing
    # to compare it against, the words stay separate and read as an aggregate.
    #
    # "maximum"/"max" cannot be evidence of a superlative on their own here,
    # because those are the words that make up the column's own name - asking
    # whether the question is a superlative question and then finding the
    # adjective inside the noun phrase being tested is circular. Counting them
    # made "show the names and maximum marks of all subjects" an aggregate
    # question, which dropped max_marks and joined the marks table to compute
    # MAX() over a column the sentence never mentioned. "what", "which", "how",
    # "highest" and "lowest" are still superlative evidence on their own.
    _asks_superlative = any(
        t in ("what", "which", "how", "highest", "lowest")
        for t in tokens
    )
    _agg_led_phrases = {"max marks", "maximum marks"}

    while i < n:
        matched = False
        # take the longest multi-word phrase first (e.g. "lead employee id"
        # before "lead employee")
        for phrase_len in range(min(3, n - i), 0, -1):
            phrase = " ".join(tokens[i:i + phrase_len])
            if phrase not in MULTIWORD_COLUMN_PHRASES:
                continue
            if phrase in _agg_led_phrases:
                _after = tokens[i + phrase_len:i + phrase_len + 3]
                _has_value = any(
                    t in CONDITION_MAP or _is_number(t) or t == "is"
                    for t in _after
                )
                # A quantified scope right after the phrase ("the maximum
                # marks IN ANY subject") makes the superlative something to
                # resolve rather than a column to list. Folding it into
                # max_marks loses the aggregate word, and the comparison it
                # belongs to then has nothing to build a subquery from - so
                # the filter is dropped and the question is answered with every
                # student. The aggregate machinery has to see it, and it is the
                # piece that knows to escalate when the scope cannot be built.
                # Only "any" counts: "of all subjects" and "of each subject"
                # just name the rows to list, and treating those as scopes
                # would send a plain projection down the aggregate path.
                # Checked regardless of _asks_superlative, because "students
                # with marks equal to the maximum marks in any subject" asks
                # for a superlative without any of the question words.
                _scoped = any(t == "any" for t in _after)
                if _scoped or (_asks_superlative and not _has_value):
                    continue
            result.append(MULTIWORD_COLUMN_PHRASES[phrase])
            i += phrase_len
            matched = True
            break
        if not matched:
            result.append(tokens[i])
            i += 1

    return result


def convert_to_sql(question):
    global _last_converted_question, _conversion_serial
    # Keep TABLE_MAP/COLUMN_MAP/categorical/multi-word in sync with any
    # tables/columns added to the live database since the last query, and
    # pull the real column values so name literals can be grounded.
    refresh_schema_maps()
    refresh_column_values()

    UNSUPPORTED_CONCEPT_TOKENS.clear()
    UNRESOLVED_ENTITY_TOKENS.clear()
    ESCALATION_REASONS.clear()
    _last_converted_question = question
    _conversion_serial += 1

    question = question.lower()

    tokens = word_tokenize(question)
    tokens = merge_multiword_columns(tokens)
    tokens = words_to_numbers(tokens)

    # "projects started in 2024" / "projects that started after 2024" - the
    # year the project started IS its start_year column, so the past tense
    # has to become the bare column keyword the rest of the engine reads.
    tokens = ["start_year" if t == "started" else t for t in tokens]

    # standalone ">"/"<" symbols - collapse to the same words the phrase
    # merger uses ("budget > 60000" => "budget greater 60000") so symbol-typed
    # questions ("budget > Marketing") hit the same comparison rules as
    # word-typed ones ("budget greater than Marketing")
    tokens = ["greater" if t == ">" else ("less" if t == "<" else t) for t in tokens]

    tokens = merge_comparison_phrases(tokens)

    # A question about data this database has no column for ("salary above
    # 60000", "employees older than 30") can't be answered by any rule here:
    # without this the engine would happily filter on some unrelated numeric
    # column and return a confidently wrong answer. Recording the words lets
    # has_recognizable_keywords() hand the question to the agentic engine,
    # which is given the real schema and can say what doesn't exist.
    for word in tokens:
        if word in UNSUPPORTED_CONCEPT_WORDS:
            UNSUPPORTED_CONCEPT_TOKENS.add(word)

    # "at least one <entity>" ("...greater than at least one employee...",
    # "...departments where at least one employee earns...") is an
    # EXISTENTIAL marker, not the "gte" (>= as high as) operator the AT_LEAST
    # sentinel alone stands for. Remember where it sits so the "1" digit
    # isn't misread as a comparison value or a row-count LIMIT, and so the
    # ANY/ALL scanner can turn it back into a proper ANY.
    at_least_one_idx = None
    for i in range(len(tokens) - 1):
        if (tokens[i] == "AT_LEAST"
                and tokens[i + 1] == "1"
                and i + 2 < len(tokens)
                and tokens[i + 2] in TABLE_MAP):
            at_least_one_idx = i
            break
    at_least_one_indices = set()
    if at_least_one_idx is not None:
        at_least_one_indices = {at_least_one_idx, at_least_one_idx + 1}

    table = "student_info"
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
    categorical_values = []   # (column, exact stored value, is_negated)
    name_value = None
    # True when the user named a row by a short form of a longer stored value
    # ("ananya" for "Ananya Singh"), so the filter must be a LIKE rather than
    # an equality - `= 'ananya'` would match nothing at all.
    name_is_partial = False
    # (table, column, value, is_exact) for a person the question names who
    # lives on a table other than the one being queried. The join planner puts
    # that table on the chain and filters on it; the engine's own WHERE can
    # only reach the driving table.
    person_filter = None


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

    # ---------------- TABLE ----------------

    table_word_idx = None

    for i, word in enumerate(tokens):
        # merged multi-word tokens stand in for their column names, but
        # column/PK words also hint at which table is meant
        table_hint = {
            "student_name": "student_info",
            "subject_name": "subject",
            "subject_id": "subject",
            "semester": "subject",
            "max_marks": "subject",
            "course_name": "course",
            "marks": "marks",
            "exam": "marks",
            "employee_name": "employee_info",
            "employee_id": "employee_info",
            "department_name": "department",
            "project_name": "project",
            "project_id": "project",
            "rating": "performance",
        }
        if word in table_hint and table_word_idx is None:
            table = table_hint[word]
            table_word_idx = i
        if word in TABLE_MAP and table_word_idx is None:
            table = TABLE_MAP[word]
            table_word_idx = i

    # Fallback: no explicit table word, but a column that only exists on a
    # specific table implies it. Ordered so the most specific tables win:
    # a bare "result"/"rating" is a performance row, a bare "address" is a
    # student (the default table) and a bare "employee name" is a person.
    if table == "student_info" and table_word_idx is None:
        # A word that is a column of exactly ONE table in the schema is as
        # good as naming the table: "distinct exam names" means the marks
        # table, "show max marks" means subject. This is computed from the
        # live schema rather than a hand-written list, so it keeps working
        # when the admin panel adds a table. Ties are left alone - a column
        # shared by several tables (result, address, course_id) identifies
        # none of them.
        resolved = {COLUMN_MAP[w] for w in tokens if w in COLUMN_MAP}
        inferred = None
        for col in sorted(resolved):
            owners = [
                t for t, cols in STATIC_TABLE_COLUMNS.items() if col in cols
            ]
            if len(owners) == 1:
                inferred = owners[0]
                break

        if inferred:
            table = inferred
        else:
            marks_cols = {"marks", "exam"}
            performance_cols = {"rating"}
            subject_cols = {"subject_name", "semester", "max_marks"}
            course_cols = {"course_name"}
            project_cols = {"project_name", "project_id", "budget", "start_year"}
            department_cols = {"department_name"}
            employee_cols = {"employee_name", "employee_id"}
            students_cols = {"address", "phone_no"}

            if resolved & marks_cols:
                table = "marks"
            elif resolved & performance_cols:
                table = "performance"
            elif resolved & subject_cols:
                table = "subject"
            elif resolved & course_cols:
                table = "course"
            elif resolved & project_cols:
                table = "project"
            elif resolved & department_cols:
                table = "department"
            elif resolved & employee_cols:
                table = "employee_info"
            elif resolved & students_cols:
                table = "student_info"
            elif any(w in DEPARTMENTS for w in tokens):
                table = "department"

    # "show good results" names no table, and "result" is a column of both
    # marks and performance, so the guess landed on marks - where "Good" is not
    # a value at all, and the query returns nothing while looking correct.
    # When the question says no table but says a value that lives in exactly
    # one table, that value is the better evidence of what was meant.
    if not any(
        (w in TABLE_MAP and w not in COLUMN_MAP)
        or (w in JOIN_TABLE_HINTS and w not in COLUMN_MAP)
        for w in tokens if w not in NON_LITERAL_WORDS
    ):
        # Only a word the engine has no other use for may steer the table. The
        # table has a value called "Average" in it, and letting the aggregate
        # word match that sent every "average X" question to the wrong table.
        _explained = set(COLUMN_MAP) | set(AGGREGATE_MAP) | set(CONDITION_MAP)
        _explained |= set(INTENT_MAP) | set(NUMBER_WORDS) | _NAME_STOP_WORDS
        _value_tables = set()
        for _w in tokens:
            if _w in _explained or _w in NON_LITERAL_WORDS:
                continue
            for _t, _cols in COLUMN_VALUES.items():
                # A person's name is a filter, not a statement about which
                # table is being asked about, so it never chooses the table.
                if _t == "app_users" or _t in _PERSON_NAME_TABLES:
                    continue
                for _values in _cols.values():
                    if any(_w == str(_v).lower() for _v in _values):
                        _value_tables.add(_t)
                        break
        if len(_value_tables) == 1:
            _only = _value_tables.pop()
            if _only != table and table_columns(_only):
                table = _only


    # ---------------- SECOND TABLE / JOIN ----------------

    join_type = None
    second_table = None
    join_columns = []
    join_trigger_idx = None
    join_related_indices = set()

    for word in tokens:
        if word in JOIN_TYPE_MAP:
            join_type = JOIN_TYPE_MAP[word]

    any_relation_verb = any(w in tokens for w in JOIN_RELATION_VERBS)
    has_at_least_one = "AT_LEAST" in tokens
    # an explicit JOIN trigger word ("along", "joined", ...), OR a relation
    # verb ("taking", "leading", ...) when NOT phrased as a count-style
    # "at least one" statement - the latter belongs to EXISTS, not JOIN.
    if any(w in tokens for w in JOIN_TRIGGER_WORDS) or (
        any_relation_verb and not has_at_least_one
    ):
        tables_found = []
        for word in tokens:
            table_hint_name = JOIN_TABLE_HINTS.get(word)
            table_map_name = TABLE_MAP.get(word)
            t = table_map_name or table_hint_name
            if t and t not in tables_found:
                tables_found.append(t)

        if len(tables_found) >= 2:
            table = tables_found[0]
            second_table = tables_found[1]
            if join_type is None:
                join_type = "INNER JOIN"   # default when no join type word is used

            # A pair with no direct key between them used to be escalated here
            # ("project and employee_info are only related through
            # performance"). The join planner can now route that itself, so
            # refusing at this point threw away questions it can answer. When
            # the planner really cannot connect the tables it escalates the
            # same way further down.


            # remember which token actually triggered the join (e.g. the
            # word "joined" or the relation verb "taking") so the
            # selected-columns scan further down doesn't also read it as
            # the joining_year column
            join_trigger_idx = next(
                (i for i, w in enumerate(tokens)
                 if w in JOIN_TRIGGER_WORDS or w in JOIN_RELATION_VERBS),
                None
            )
            if join_trigger_idx is not None:
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

    # ---------------- CROSS-TABLE MARKS COMPARISON ----------------
    # "students with marks above 80" / "subjects whose marks are less than
    # 40": the mark VALUES live on the marks table (Student_ID, Subject_ID,
    # Marks), so asking about marks while the subject is students/subjects
    # means the marks table must be JOINed in, not an imagined marks column
    # on the current table. Only fires when a marks-word is compared against
    # a number and no explicit join was already detected (so "student name
    # along with their marks" still uses its own path).
    if (
        second_table is None
        and table in ("student_info", "subject", "course")
        and any(w in tokens for w in ("marks", "mark", "scores", "score", "results", "result"))
        and any(w in STRONG_COMPARISON_WORDS for w in tokens)
        and any(_is_number(w) for w in tokens)
    ):
        second_table = "marks"
        join_type = "INNER JOIN" if join_type is None else join_type
        join_related_indices.update(
            i for i, w in enumerate(tokens) if w in ("marks", "mark", "scores", "score", "results", "result")
        )

    # ---------------- CROSS-TABLE RANKING / AGGREGATION ----------------
    # (placed after the aggregate/limit words are resolved - see below)

    # ---------------- UNION ----------------

    union_second_table = None
    union_all = False

    if any(w in tokens for w in UNION_TRIGGER_WORDS):
        union_all = "all" in tokens
        tables_found_union = []
        for word in tokens:
            if word in TABLE_MAP and TABLE_MAP[word] not in tables_found_union:
                tables_found_union.append(TABLE_MAP[word])

        if len(tables_found_union) >= 2:
            table = tables_found_union[0]
            union_second_table = tables_found_union[1]

    # Implicit union: "employees and students ...", "employee and student
    # ..." with no explicit "union" keyword and no join/relationship word
    # (JOIN_TRIGGER_WORDS) - this is asking for rows from BOTH tables, not
    # a filter and not a join (there's no shared key being matched). Only
    # fires when a table word is directly followed by "and" then another,
    # DIFFERENT table word, and only if union/join weren't already picked
    # up above - keeps this narrow so it doesn't misfire on unrelated
    # sentences that merely mention two table names.
    if union_second_table is None and second_table is None:
        for i, word in enumerate(tokens):
            if word == "and" and 0 < i < len(tokens) - 1:
                left, right = tokens[i - 1], tokens[i + 1]
                if left in TABLE_MAP and right in TABLE_MAP:
                    t1, t2 = TABLE_MAP[left], TABLE_MAP[right]
                    if t1 != t2:
                        table = t1
                        union_second_table = t2
                        break

    # ---------------- INTENT ----------------

    for word in tokens:
        if word in INTENT_MAP:
            intent = INTENT_MAP[word]

    # "how many X" / "how much X" -> COUNT
    if "how" in tokens and "many" in tokens:
        intent = "count"

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

    # "from highest to lowest" / "from lowest to highest" is a sort-direction
    # phrase, not a record condition - "order by salary from highest to
    # lowest" means DESC, not "there's a highest record". Mark those words so
    # the record-condition scan below skips them.
    direction_phrase_indices = set()
    for i in range(len(tokens) - 1):
        if tokens[i] == "from" and i + 3 < len(tokens) and tokens[i + 2] == "to":
            a, b = tokens[i + 1], tokens[i + 3]
            if (a in ("highest", "lowest")) and (b in ("highest", "lowest")):
                if a == "highest":
                    order_by_direction = "DESC"
                else:
                    order_by_direction = "ASC"
                order_requested = True
                direction_phrase_indices.update({i + 1, i + 3})

    # "second-highest-paid employee" / "third lowest marks" - an ordinal
    # naming a specific position in a ranking. This is a rank-record query
    # (ORDER BY ... LIMIT 1 OFFSET N-1), not a bare highest/lowest. Handles
    # both plain words ("second highest") and hyphenated tokens that NLTK
    # keeps whole ("second-highest-paid").
    rank_offset = 0
    for i, word in enumerate(tokens):
        ordinal_word = None
        if word in ORDINAL_MAP:
            ordinal_word = word
        else:
            # hyphenated form: split on "-" and check the leading word
            first = word.split("-")[0]
            if word.count("-") > 0 and first in ORDINAL_MAP:
                ordinal_word = first
        if ordinal_word is None:
            continue
        rank = ORDINAL_MAP[ordinal_word]
        if rank < 2:
            continue  # "first highest" is just plain highest
        if word.count("-") > 0:
            # hyphenated token already carries the ranking word inside it,
            # e.g. "second-highest-paid" -> highest, "third-lowest" -> lowest
            if "highest" in word:
                record_condition = "highest"
                record_condition_idx = i
                rank_offset = rank - 1
                break
            if "lowest" in word:
                record_condition = "lowest"
                record_condition_idx = i
                rank_offset = rank - 1
                break
        # plain-word form: the ranking word must sit nearby (within 3 tokens)
        lo = max(0, i - 3)
        hi = min(len(tokens), i + 3)
        for j in range(lo, hi):
            if tokens[j] in ("highest", "highest-paid", "lowest", "lowest-paid", "paid", "ranked"):
                record_condition = "highest" if tokens[j] in ("highest", "highest-paid") else "lowest"
                record_condition_idx = j
                rank_offset = rank - 1
                break
        if rank_offset:
            break

    for i, word in enumerate(tokens):
        if i in direction_phrase_indices:
            continue
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

    # A superlative over a grouping is a per-group MAX/MIN, not a global
    # top-1: "the highest budget in each department" asks for one number per
    # department, and answering it with the single largest budget in the whole
    # table is a different question. Gating on a real aggregate function
    # missed this, because "highest" is a ranking word rather than an
    # aggregate word, so the grouping was never even looked for.
    _grouping_words = ["by", "per", "each", "based"]
    _groups_with_aggregate = bool(
        aggregate_function
        or intent == "count"
        or (record_condition in RECORD_CONDITION_TYPES
            and any(w in tokens for w in _grouping_words))
    )

    # Which word introduced the grouping decides how much of it is wanted.
    # "per"/"each" asks for every group ("the highest budget in each
    # department"), while a superlative with no such word asks for the single
    # winning group ("the department with the highest average budget") - a
    # question whose answer is one row, not a table of them.
    _group_keyword = None

    if _groups_with_aggregate:
        # "by department", "per subject", "each city", and "based on gender"
        for keyword in _grouping_words:
            if keyword in tokens:
                idx = tokens.index(keyword)
                # "based ON gender" - the preposition between the trigger and
                # the column is just filler
                j = idx + 1
                if keyword == "based" and j < len(tokens) and tokens[j] in ("on", "upon"):
                    j += 1
                if j < len(tokens):
                    next_word = tokens[j]
                    _before_group = group_by_column
                    if next_word in COLUMN_MAP:
                        group_by_column = COLUMN_MAP[next_word]
                    elif next_word in GROUPABLE_CATEGORICAL_COLUMNS:
                        # "per department_name", "by course_id" - a snake_case
                        # column token that survived multiword merging. Only
                        # accepted when it is a real column of a table in play,
                        # so the grouping can never name a phantom column.
                        for _t in (table, second_table):
                            if _t and next_word in table_columns(_t):
                                group_by_column = next_word
                                break
                        else:
                            # "per department name" on a table that only holds
                            # Department_ID: reuse the abstract "department"
                            # grouping, which already knows how to join the
                            # department table in and group on its readable name
                            if (
                                next_word == "department_name"
                                and "department_id" in table_columns(table)
                                and next_word not in table_columns(table)
                            ):
                                group_by_column = "department"

                    if group_by_column != _before_group:
                        _group_keyword = keyword

        # implicit pattern: "cities where average marks..." / "departments
        # where avg budget..." - the categorical column mentioned before the
        # aggregate word is treated as the GROUP BY target when no explicit
        # by/per/each keyword was found
        if not group_by_column and aggregate_idx is not None:
            for word in tokens[:aggregate_idx]:
                if word in COLUMN_MAP and COLUMN_MAP[word] in GROUPABLE_CATEGORICAL_COLUMNS:
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

    # "show subjects HAVING more than one student" counts marks rows per
    # subject - the SUBJECT the student's marks belong to lives on the marks
    # table via Subject_ID. When a having-count grouped by "subject" was
    # detected ("subjects having more than 3 students"), the sentence meant
    # counting marks rows per subject, so the table must be marks and the
    # group-by column subject_id.
    if group_by_column in ("subject_id", "subject_name") and table in ("subject", "course"):
        table = "marks"
        group_by_column = "subject_id"

    # ---------------- COUNT vs AVERAGE OF COUNTS ----------------
    # "departments that have MORE EMPLOYEES than the AVERAGE number of
    # employees per department" compares each group's ROW COUNT against the
    # average row count of all such groups:
    #   SELECT department_id, COUNT(*) FROM employee_info GROUP BY department_id
    #   HAVING COUNT(*) > (SELECT AVG(cnt) FROM (SELECT COUNT(*) AS cnt FROM
    #   employee_info GROUP BY department_id) AS avg_counts)
    # A table word (or "number of ...") must sit between the comparison and
    # the "average" so a plain column comparison ("budget above the average
    # budget") doesn't get misread as a row-count comparison.
    count_avg_cmp = None
    if group_by_column:
        for i, word in enumerate(tokens):
            cmp_op = None
            if word in ("more", "greater", "higher", "above"):
                cmp_op = ">"
            elif word in ("fewer", "less", "lesser", "below", "lower"):
                cmp_op = "<"
            else:
                continue
            than_idx = None
            for j in range(i + 1, min(len(tokens), i + 4)):
                if tokens[j] == "than":
                    than_idx = j
                    break
            if than_idx is None:
                continue
            between = tokens[i + 1:than_idx]
            if not any(t in TABLE_MAP or t in ("number", "count", "amount") for t in between):
                continue
            if any(t == "average" for t in tokens[than_idx + 1:than_idx + 5]):
                count_avg_cmp = cmp_op
                break

    # ---------------- BETWEEN ----------------

    between_negated = False
    between_idx = None

    if "between" in tokens:
        b_idx = tokens.index("between")
        between_idx = b_idx
        nums_after = [w for w in tokens[b_idx:]
                      if _is_number(w)
                      or (w.count("-") == 2 and all(p.isdigit() for p in w.split("-")))]
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

    # "the top 3 marks BY MARKS" is a ranking with a sort column, not a
    # per-group aggregate. Grouping by the very column being ranked gives one
    # row per distinct value instead of the top N rows asked for, and the
    # projection then loses the ranked column to `SELECT *`. Only a target
    # that is NOT the ranked column makes a superlative a per-group MAX/MIN,
    # which is what "the highest budget in each department" is asking for. Only
    # checked when no real aggregate was named, since "the average marks per
    # subject" really does group.
    if (
        aggregate_function is None
        and intent != "count"
        and group_by_column
        and group_by_column == numeric_column
    ):
        group_by_column = None

    # condition_column: date words (before/after/since/till/until) always
    # mean a year/date column - project.Start_Year is the only one in this
    # schema, but the map auto-syncs with any DATE/DATETIME/TIMESTAMP column
    # added later - regardless of any other column mentioned.
    if value_condition_word in DATE_TRIGGER_WORDS:
        condition_column = DATE_COLUMNS.get(table)
    else:
        value_anchor_idx = value_condition_idx if value_condition_idx is not None else between_idx
        condition_column = nearest_column(value_anchor_idx)

    # "started in 2026" / "began before 2024" - "started"/"began"/"launched"
    # already became start_year during tokenization, but the year is often
    # the only number in the sentence and "in" hides it from the value scan
    # on a bare "which projects started in 2026" phrasing. Pin the column
    # whenever the sentence is explicitly about a start year.
    if "start_year" in tokens or "launched" in tokens:
        if condition_column is None or condition_column in ("project_id", "budget"):
            condition_column = "start_year"

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

    # ---------------- IMPLICIT LIMIT ("3 employees") ----------------
    # A bare number directly before a table name is a row-count limit
    # ("show 3 employees with lowest salary"), not a comparison value -
    # without this, "3" above would become a `salary = 3` filter instead.
    # BUT when "having" appears ("department HAVING more than 3 employees"),
    # that number is the HAVING comparison value, NOT a row limit - the
    # having-count path needs it as the value. The same goes for a number that
    # a comparison word introduces directly: in "more than 60 marks" the "60"
    # is followed by the table name, but it is the value being compared
    # against, not a row count - treating it as a LIMIT silently drops the
    # filter and returns every student.
    if limit_value is None and "having" not in tokens:
        for i, word in enumerate(tokens):
            if i in at_least_one_indices:
                continue
            if any(tokens[j] in _COMPARISON_LEAD_WORDS for j in range(max(0, i - 2), i)):
                continue
            # a number glued to the front of a categorical value is part of the
            # value, not a row count ("Internal 1 exam", "semester 3")
            if i > 0 and tokens[i - 1] in CATEGORICAL_VALUE_DISPLAY:
                continue
            if word.isdigit() and i + 1 < len(tokens) and tokens[i + 1] in TABLE_MAP:
                limit_value = word
                limit_value_idx = i
                break

    # ---------------- CROSS-TABLE COUNT ("departments with more than 2 employees") ----------------
    # A count of one table grouped by a column of ANOTHER table needs a
    # derived table ("SELECT department_id, COUNT(*) FROM employee_info GROUP
    # BY department_id") - the rule engine only builds single-table COUNTs and
    # would otherwise read the "2" as a row LIMIT and answer a completely
    # different question ("show 2 departments"). Recognise the shape and hand
    # it to the agentic layer instead of guessing.
    if second_table is None and not union_second_table:
        for i, word in enumerate(tokens):
            # "... more than 2 employees" (a bare number) and "... the number
            # of subjects" (a spelled-out count) are the same request
            if word.isdigit() and i + 1 < len(tokens) and tokens[i + 1] in TABLE_MAP:
                counted_table = TABLE_MAP[tokens[i + 1]]
                _is_digit_form = True
            elif (
                word in ("number", "count")
                and i + 1 < len(tokens) and tokens[i + 1] == "of"
                and i + 2 < len(tokens) and tokens[i + 2] in TABLE_MAP
            ):
                counted_table = TABLE_MAP[tokens[i + 2]]
                _is_digit_form = False
            else:
                continue

            # the entity being counted must be a different table from the one
            # the question is grouped/filtered by
            grouped_tables = {
                TABLE_MAP[w] for w in tokens
                if w in TABLE_MAP and TABLE_MAP[w] != counted_table
            }
            if not grouped_tables or counted_table == table:
                continue

            for grouped_table in grouped_tables:
                if not any(
                    (grouped_table, _o) in JOIN_KEY_MAP or (_o, grouped_table) in JOIN_KEY_MAP
                    for _o in STATIC_TABLE_COLUMNS
                    if _o != grouped_table
                ):
                    continue
                if _is_digit_form:
                    _ctx = " ".join(tokens[max(0, i - 4):i])
                    if not any(
                        w in _ctx for w in ("more", "fewer", "less", "greater", "at", "than")
                    ):
                        continue
                    limit_value = None
                    limit_value_idx = i
                    between_nums.discard(word)
                ESCALATION_REASONS.add(
                    f"count of {counted_table} grouped by {grouped_table}"
                )
                break
            if ESCALATION_REASONS:
                break


    # ---------------- NUMBER (generic comparison value) ----------------

    for i, word in enumerate(tokens):
        if i in at_least_one_indices:
            continue
        if _is_number(word) and word not in between_nums and i != limit_value_idx:
            value = word
        # ISO dates ("2026-05-01") come through as a single token - used as
        # a comparison value for date columns (e.g. projects.deadline)
        elif word.count("-") == 2 and all(part.isdigit() for part in word.split("-")):
            if word not in between_nums and i != limit_value_idx:
                value = word

    # a numeric comparison alongside a GROUP BY + aggregate/count belongs in
    # HAVING (applied after grouping), not WHERE (applied before) - this
    # covers both "... having more than 2 ..." and "... average marks are
    # greater than 80" phrasings
    condition_is_having = bool(
        group_by_column and (aggregate_function or intent == "count")
        and value_condition in ("above", "below", "gte", "lte") and value
    )

    # ---------------- CROSS-TABLE RANKING / AGGREGATION ----------------
    # "top 3 students by marks", "highest rated employees", "average budget
    # of projects" - the column being ranked or averaged is not on the table
    # the question is about, but it is one hop away through a real foreign
    # key, so the right answer is a JOIN rather than either an invented
    # column or a silently unfiltered SELECT *. This is the same idea as the
    # marks comparison above, minus the need for an explicit number.
    if second_table is None and not union_second_table:
        # order_requested is only set by the detailed ORDER BY scan further
        # down, so the trigger words are re-checked here: "sort students by
        # marks descending" ranks a column one hop away just as much as "top 3
        # by marks" does, and without the join the ORDER BY names a column the
        # table does not have and MySQL rejects the query outright.
        _order_asked = order_requested or any(
            w in ORDER_TRIGGER_WORDS for w in tokens
        )
        _aggregate_requested = bool(
            intent == "count"
            or aggregate_function in ("AVG", "SUM", "MIN", "MAX")
            or record_condition in ("highest", "lowest")
            or limit_value
            or _order_asked
        )
        if _aggregate_requested:
            for _word, _cand in COLUMN_MAP.items():
                if _word not in tokens:
                    continue
                if _cand == "name" or _cand in table_columns(table):
                    continue
                for _other, _cols in STATIC_TABLE_COLUMNS.items():
                    if _cand not in _cols or _other == table:
                        continue
                    if (table, _other) not in JOIN_KEY_MAP:
                        continue
                    second_table = _other
                    join_type = "INNER JOIN" if join_type is None else join_type
                    break
                if second_table:
                    break

    # ---------------- DEPARTMENT ----------------
    # The literal is the exact spelling stored in department.Department_Name
    # ('HR', 'IT', 'Finance', 'Marketing'), never a blanket .upper().



    # ---------------- DEPARTMENT ----------------
    # The literal is the exact spelling stored in department.Department_Name
    # ('HR', 'IT', 'Finance', 'Marketing'), never a blanket .upper().

    for i, word in enumerate(tokens):
        if word in DEPARTMENTS and _is_literal_value(word, tokens, i):
            _entry = (department_display(word), is_negated(tokens, i))
            if _entry not in department_values:
                department_values.append(_entry)

    # ---------------- CITY / ADDRESS ----------------

    for i, word in enumerate(tokens):
        if word in CITIES and _is_literal_value(word, tokens, i):
            _entry = (city_display(word), is_negated(tokens, i))
            if _entry not in city_values:
                city_values.append(_entry)


    # ---------------- GENDER ----------------

    for i, word in enumerate(tokens):
        if word in GENDERS:
            gender_values.append((word.capitalize(), is_negated(tokens, i)))

    # ---------------- EXAM / RESULT ----------------
    # "the final exam", "students who passed", "excellent performance" - the
    # spoken word is mapped to the exact string stored in exam/result, and only
    # used when the table being queried actually has that column.

    for i, word in enumerate(tokens):
        if word in CATEGORICAL_VALUE_COLUMN:
            categorical_values.append(
                (CATEGORICAL_VALUE_COLUMN[word],
                 CATEGORICAL_VALUE_DISPLAY[word],
                 is_negated(tokens, i))
            )

    # A spoken exam/result value whose column lives only on ANOTHER table is a
    # two-table question in disguise: "students who failed the midterm",
    # "employees with excellent performance". Without the join the filter has
    # nowhere to go and the question silently returns every row; with it, the
    # filter applies to the joined table and the columns are unambiguous.
    if second_table is None and not union_second_table:
        for _col, _v, _n in categorical_values:
            if _col in table_columns(table):
                continue
            for _other, _cols in STATIC_TABLE_COLUMNS.items():
                if _col not in _cols or _other == table:
                    continue
                if (table, _other) not in JOIN_KEY_MAP:
                    continue
                second_table = _other
                join_type = "INNER JOIN" if join_type is None else join_type
                break
            if second_table:
                break

    # A comparison whose column lives only on ANOTHER table is the same
    # two-table question in disguise, and it fails the same way: "students
    # whose marks are between 70 and 90" resolves to student_info, which has no
    # marks column, so the schema guard below discards the BETWEEN and the
    # question silently degrades to a listing of every student. Promoting the
    # owning table puts marks on the join, the column becomes real, and the
    # range survives.
    if second_table is None and not union_second_table and condition_column:
        if condition_column not in table_columns(table):
            for _other, _cols in STATIC_TABLE_COLUMNS.items():
                if condition_column not in _cols or _other == table:
                    continue
                if (table, _other) not in JOIN_KEY_MAP:
                    continue
                second_table = _other
                join_type = "INNER JOIN" if join_type is None else join_type
                break

    # ---------------- UNFILTERABLE QUALIFIER ----------------
    # "show student names in HR" - students have no department at all
    # (student_info has no Department_ID; that relationship only exists for
    # employee_info and project). Silently dropping the filter would answer
    # "all 15 students", confidently and wrongly, so escalate to the agentic
    # layer instead of pretending the question was understood.
    if (
        not ESCALATION_REASONS
        and department_values
        and "department_name" not in table_columns(table)
        and "department_id" not in table_columns(table)
        and not (second_table and (
            "department_name" in table_columns(second_table)
            or "department_id" in table_columns(second_table)
        ))
    ):
        ESCALATION_REASONS.add(f"department filter cannot apply to {table}")

    # ---------------- NAME ----------------

    if "named" in tokens:

        idx = tokens.index("named")

        if idx + 1 < len(tokens):
            # Only take the word after "named" as a row name if this table
            # actually has a name column to filter. "show marks of the student
            # named Ananya" is about marks, and marks has no name column -
            # resolve_column() answers with a default from a different schema
            # group, so the filter silently became `employee_name = 'Ananya'`.
            # Leaving it unset lets the person lookup below run instead, which
            # can find Ananya on student_info and join to them.
            if resolve_column("name", table) in table_columns(table):
                name_value = tokens[idx + 1].capitalize()


    # A bare name with no "named" in front of it - "show ananya marks",
    # "ananya singh" - used to be invisible to the rule engine, which would
    # emit an unfiltered SELECT * and quietly return every row instead. The
    # token is only accepted when it matches a value that actually exists in
    # a column of the table being queried, so a stray unknown word can never
    # turn into a filter on the wrong column.
    if name_value is None:
        # Everything after the LAST comparison word is that comparison's
        # target, not a filter on this query. "salary greater than the salary
        # of Amit" already resolves through the named-person subquery path
        # below, so the bare-name filter must not also fire on "Amit" and add
        # a redundant `name = 'Amit'` next to the subquery. Filler words sit
        # between the comparison and the name here, so this keys off position
        # rather than the single token that follows the comparison word.
        last_comparison = -1
        for i, tok in enumerate(tokens):
            if tok in _COMPARISON_LEAD_WORDS:
                last_comparison = i
        # -1 means the question has no comparison at all, so nothing is a
        # comparison target - note tokens[0:] would wrongly select every
        # token, hence the explicit empty case.
        comparison_region = set(tokens[last_comparison + 1:]) if last_comparison >= 0 else set()

        # 1) Can the table this question resolved to filter the name itself?
        for word in tokens:
            if word in comparison_region:
                continue
            match = _find_entity_match(word, tables=(table,))
            if not match:
                continue
            name_value = match[2]
            name_is_partial = not match[3]
            break

        # 2) If not, does the question still name a person who really exists,
        #    just one this table can't reach on its own? "show ananya marks"
        #    asks a question about marks, but the only person in it is a row of
        #    student_info, so answering needs a join. The join planner can
        #    build that now, so the person is recorded and the planner adds
        #    their table to the chain; if it cannot be connected from here, the
        #    agentic layer takes over as before.
        if name_value is None:
            for word in tokens:
                if word in comparison_region:
                    continue
                person = _find_entity_match(word, tables=_PERSON_NAME_TABLES)
                if person:
                    person_filter = person
                    break


    # ---------------- NULL CONDITION ----------------

    null_column = None
    null_negated = False

    for i, word in enumerate(tokens):
        if word in NULL_TRIGGER_WORDS:
            null_negated = is_negated(tokens, i, window=3)

            # the column can appear either before ("salary not null") or
            # after ("missing department") the trigger word. Search ALL
            # preceding tokens (not just a narrow 3-word window) so a
            # column a few words back - "show salary of employees which is
            # not null" - is still found; the last column mentioned wins.
            backward_window = tokens[:i]
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

    # "do not have a manager" / "doesn't have an email" / "without a guardian"
    # pattern: detect "not have" + optional "a"/"an" + column word
    if null_column is None:
        for i, word in enumerate(tokens):
            if word == "not" and i + 1 < len(tokens) and tokens[i + 1] == "have":
                j = i + 2
                if j < len(tokens) and tokens[j] in ("a", "an"):
                    j += 1
                if j < len(tokens) and tokens[j] in COLUMN_MAP:
                    null_column = COLUMN_MAP[tokens[j]]
                    null_negated = False
                    break

    # "do not belong to any department" / "not in any city" - the "any" +
    # column pattern means the value is absent entirely -> IS NULL.
    if null_column is None and "belong" in tokens and "any" in tokens:
        b_idx = tokens.index("belong")
        for j in range(b_idx, len(tokens)):
            if tokens[j] == "any" and j + 1 < len(tokens) and tokens[j + 1] in COLUMN_MAP:
                null_column = COLUMN_MAP[tokens[j + 1]]
                null_negated = False
                break

    # "show employees who HAVE a manager" / "students who HAVE a guardian" -
    # the positive counterpart: HAVE a <column> means IS NOT NULL. This is
    # skipped when a relation/EXISTS trigger is present ("who have a subject
    # ASSIGNED to them" is an EXISTS query, not a null check).
    if null_column is None and not any(w in tokens for w in EXISTS_TRIGGER_WORDS):
        for i, word in enumerate(tokens):
            if word == "have" and i + 1 < len(tokens):
                j = i + 1
                if tokens[j] in ("a", "an"):
                    j += 1
                if j < len(tokens) and tokens[j] in COLUMN_MAP:
                    null_column = COLUMN_MAP[tokens[j]]
                    null_negated = True
                    break

    # A missing relationship is a missing FOREIGN KEY. "department" is not a
    # column on employee_info or project - they hold a numeric Department_ID,
    # and the readable name lives in the department table - so the schema guard
    # below would drop the IS NULL test entirely. Worse, the question has by
    # then pulled the department table into an INNER JOIN, and an inner join
    # discards exactly the rows whose key is NULL. "employees who do not have
    # a department" therefore returns the employees that do have one: the
    # opposite answer, with no error and no empty result to hint at it. Point
    # the test at the local key and make the join outer.
    if null_column and null_column not in table_columns(table):
        # An abstract relationship word names a foreign key, not a column.
        _fk = NULLABLE_RELATION_COLUMN.get(null_column)
        if _fk and _fk in table_columns(table):
            null_column = _fk
            # Unconditional, and not conditioned on second_table: the
            # relationship table has not been chosen yet at this point in the
            # parse, and whichever join the question ends up needing for this
            # relationship has to be the outer one. An inner join would make
            # the IS NULL test unsatisfiable by construction.
            join_type = "LEFT JOIN"
        # Otherwise the column may be real but owned by another table - "no
        # marks" is student_info.marks, not student_info. anything. Bring the
        # owning table in, the same way a comparison column is promoted.
        elif second_table is None and not union_second_table:
            for _owner, _cols in STATIC_TABLE_COLUMNS.items():
                if null_column not in _cols or _owner == table:
                    continue
                if (table, _owner) not in JOIN_KEY_MAP:
                    continue
                second_table = _owner
                join_type = "LEFT JOIN"
                break

     # ---------------- EXISTS ----------------

    exists_second_table = None
    exists_column = SHARED_COLUMN

    if any(w in tokens for w in EXISTS_TRIGGER_WORDS):
        tables_found_exists = []
        for word in tokens:
            t = TABLE_MAP.get(word) or JOIN_TABLE_HINTS.get(word)
            if t and t not in tables_found_exists:
                tables_found_exists.append(t)

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

        # An abstract keyword can't be a join key, and neither can a column
        # the second table doesn't have ("students who live in a department"
        # has no department column to match on at all).
        if exists_column == "name" or exists_column not in table_columns(exists_second_table):
            shared_ids = sorted(
                c for c in (table_columns(table) & table_columns(exists_second_table))
                if c.endswith("_id")
            )
            exists_column = shared_ids[0] if shared_ids else SHARED_COLUMN

    # ---------------- ANY / ALL ----------------

    any_all_keyword = None
    any_all_sub_table = None
    any_all_sub_column = None

    aggregate_subquery_function = None

    for i, word in enumerate(tokens):
        # "all employees who have a salary greater than 60000" is NOT an
        # ALL-subquery - "all" here is just describing the whole table and
        # the comparison comes AFTER it. A genuine ANY/ALL comparison puts
        # the comparison word first: "salary greater than ALL employees in
        # HR", "cgpa greater than ANY student from Mysore". Only treat
        # any/all as a subquery qualifier when a value-comparison word
        # (above/below/equal/since/...) appeared before it.
        if word in ANY_ALL_TRIGGER_WORDS:
            preceding_comp = any(
                tokens[j] in STRONG_COMPARISON_WORDS
                and CONDITION_MAP.get(tokens[j]) in VALUE_CONDITION_TYPES
                for j in range(i)
            )
            if not preceding_comp:
                continue

            # "... greater than the AVERAGE salary of all employees" isn't
            # ANY/ALL at all - the aggregate word ("average"/"sum") sitting
            # between the operator and any/all means the comparison target
            # is a single summary value, e.g. salary > (SELECT AVG(salary)
            # FROM employees). All-rows scope is implied, so trade the
            # any/all qualifier for an aggregate subquery instead.
            agg_in_between = [
                (j, AGGREGATE_MAP[tokens[j]])
                for j in range(i)
                if tokens[j] in AGGREGATE_MAP
                and AGGREGATE_MAP[tokens[j]] != "DISTINCT"
            ]
            if agg_in_between:
                aggregate_subquery_function = agg_in_between[-1][1]
                continue

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

        elif word == "AT_LEAST" and at_least_one_idx == i:
            # "...salary is greater than AT_LEAST 1 employee in IT" - the
            # "at least one <entity>" phrase means ANY, i.e. "greater than
            # at least one employee" == "> ANY (employee salaries)". Same
            # guard as above: only when a comparison word governs it.
            preceding_comp = any(
                tokens[j] in STRONG_COMPARISON_WORDS
                and CONDITION_MAP.get(tokens[j]) in VALUE_CONDITION_TYPES
                for j in range(i)
            )
            if preceding_comp:
                any_all_keyword = "ANY"
                for t in tokens[i:]:
                    if t in TABLE_MAP:
                        any_all_sub_table = TABLE_MAP[t]
                        break
                for t in tokens[i:]:
                    if t in COLUMN_MAP and COLUMN_MAP[t] not in CATEGORICAL_COLUMNS:
                        any_all_sub_column = COLUMN_MAP[t]
                        break
                # "greater than at least one <entity>" is strict ">", not
                # the >= that the AT_LEAST sentinel alone would produce
                value_condition = "above"

    # the aggregate ("average salary of all employees") belongs INSIDE the
    # subquery filter, so the outer query must not collapse to a
    # SELECT AVG(salary) - it stays a plain row-level SELECT with a
    # WHERE salary > (SELECT AVG(salary) FROM employees) filter
    if aggregate_subquery_function:
        aggregate_function = None
        aggregate_idx = None

    # "salary MORE THAN the AVERAGE salary" / "marks BELOW the SUM of marks"
    # - no "any"/"all" word is required. As long as a comparison operator
    # precedes an aggregate word that names the comparison target
    # ("average salary"), it's a subquery summary to compare against, not a
    # top-level aggregate. Only counts when the comparison has no literal
    # number ("above 2") - otherwise it's a plain WHERE filter.
    if (
        not aggregate_subquery_function
        and aggregate_idx is not None
        and value_condition_idx is not None
        and aggregate_idx > value_condition_idx
        and value is None
        and value_condition_word in STRONG_COMPARISON_WORDS
    ):
        agg_fn = AGGREGATE_MAP[tokens[aggregate_idx]]
        if agg_fn != "DISTINCT":
            aggregate_subquery_function = agg_fn
            aggregate_function = None
            aggregate_idx = None

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
            # "employees whose name contains ..." with no column word - every
            # table names its rows through a <thing>_name column, and the
            # abstract "name" has to land on whichever one this is.
            like_column = "name"

        # an abstract/foreign column can't be filtered on - fall back to the
        # table's own name column so the LIKE still has somewhere to go
        if like_column not in table_columns(table):
            like_column = resolve_column("name", table)

        # Name columns are stored title-cased ("Ananya", "Cloud Technology"),
        # so a pattern drawn from the question should match that casing.
        name_like_columns = set(NAME_COLUMN_BY_TABLE.values())

        # "contains the word company" - the word "word" (and "letter") are
        # just empty fillers announcing the real pattern (company), so they
        # don't become the LIKE pattern themselves.
        pattern_list = tokens[like_trigger_idx + 1:]
        for k, word in enumerate(pattern_list):
            if word.isalpha() and word not in LIKE_FILLER_WORDS:
                if word in ("word", "letter", "words", "letters") and k + 1 < len(pattern_list):
                    continue
                like_pattern = word.capitalize() if like_column in name_like_columns else word
                break
        if like_pattern is None and pattern_list:
            for word in pattern_list:
                if word.isalpha() and word not in LIKE_FILLER_WORDS:
                    like_pattern = word.capitalize() if like_column in name_like_columns else word
                    break

    # ---------------- ORDER BY ----------------

    for i, word in enumerate(tokens):
        if word in ORDER_TRIGGER_WORDS:
            order_requested = True
            window_start = max(0, i - 3)
            window = tokens[window_start:i] + tokens[i:i + 6]
            for wi, w in enumerate(window):
                # A categorical column is normally not a sensible sort target -
                # except when the user spelled it out right after the ORDER BY
                # trigger, which is exactly the "order students by student
                # name" case that used to silently fall back to the id column.
                _explicit_sort = wi > 0 and window[wi - 1] in ("by", "on")
                if w in COLUMN_MAP and (
                    COLUMN_MAP[w] not in CATEGORICAL_COLUMNS
                    or COLUMN_MAP[w] == "name"
                    or _explicit_sort
                ):
                    order_by_column = COLUMN_MAP[w]
                if w in SORT_DIRECTION_MAP:
                    order_by_direction = SORT_DIRECTION_MAP[w]
            break

    # "sorted by name" is the abstract name keyword, not a literal column -
    # land it on the *_name column of the table in play, or MySQL is handed
    # an `ORDER BY name` that no table in this schema has.
    if order_by_column == "name":
        _resolved_name = resolve_column("name", table)
        if _resolved_name:
            order_by_column = _resolved_name
        else:
            order_by_column = None

    # ---------------- SELECTED COLUMNS ("show name and marks of students") ----------------

    STOP_WORDS_FOR_COLUMNS = {
        "where", "whose", "with", "having",
        "between",
        "above", "below", "over", "under", "greater", "less", "more",
        "order", "ordered", "sort", "sorted", "arrange",
        "limit",
        "like", "contains", "containing", "starting", "starts", "ending", "ends",
    }
    selected_columns = []
    # where in the question each selected column word sat, so later rules can
    # tell "show subjects and their max marks" (max_marks describes the table)
    # from "show student names and their marks" (student_name was requested)
    selected_column_indices = []
    # columns the question explicitly asked to display that the resolved table
    # does not have, mapped to the single other table that DOES have them. This
    # is what turns "show employee name and department name" into a join
    # instead of silently dropping half the request.
    foreign_requested = {}
    # column words that just echoed the resolved table's own name. A single
    # one is the table being named ("show courses" wants every course), but
    # several of them are the user listing real columns of that table
    # ("show exam, marks and result" on marks) - so they are only folded back
    # into the projection when nothing else was selected.
    echoed_table_columns = []


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
        # "bangalore CITY", "hr DEPARTMENT" - is the value being described,
        # not that column being requested. Without this, "get name of
        # employees from bangalore city" would incorrectly select both name
        # AND address, when only name was actually asked for.
        DESCRIPTOR_VALUE_LISTS = {"address": CITIES, "department": DEPARTMENTS}

        for i, word in enumerate(tokens[intent_word_idx + 1:end_idx], start=intent_word_idx + 1):
            if i in join_related_indices:
                continue
            if word in COLUMN_MAP:
                col = COLUMN_MAP[word]
                # a column that is being tested for NULL/not-NULL is a
                # filter, not something the user asked to display - "whose
                # address is null" means show the people, not the column
                if null_column is not None and col == null_column:
                    continue
                # a word that merely echoes the table's own name isn't a
                # requested column - "show subjects" wants the whole
                # subjects table, not the subject column (project_name IS
                # a real column on project, so it's NOT filtered). This
                # also covers the *_id auto-synonym (course/exam/rating
                # -> their *_id column): "show courses" means the whole
                # table, not just course_id. The echo is only dropped when
                # nothing else was asked for - "show exam, marks and result"
                # names three real marks columns, and "exam" echoing the
                # table must not swallow the whole projection.
                if word in TABLE_MAP and TABLE_MAP[word] == table:
                    echoed_table_columns.append(col)
                    continue
                # a word that just echoes the subject table isn't a requested
                # column - "show subjects" wants the whole subjects table
                if table == "subject" and col == "subject_id":
                    continue
                # A bare group/scope word narrows the rows, it doesn't say
                # what to display: "show subjects of semester 3" wants the
                # subjects, not a single column called semester - and
                # "show students of course 1" wants the students. The tell is
                # the word introducing it ("of", "in", "for", "from") with
                # its value on the far side.
                if col in FILTER_ONLY_COLUMNS:
                    _ctx = tokens[max(0, i - 2):i]
                    if any(w in ("of", "in", "for", "from", "with") for w in _ctx):
                        continue
                # "name" is an abstract keyword, not a real column: land it
                # on the *_name column of the table this question is about
                # ("show the names of all subjects" -> subject_name).
                if col == "name":
                    col = resolve_column("name", table)
                # a column the queried table doesn't actually have can't be
                # selected - "show the phone number of every department"
                # must not turn into a reference to a missing column. But if
                # exactly one other table reachable by a real join key owns
                # it, the honest reading is a two-table question, so remember
                # it and join that table in below rather than dropping the
                # column the user explicitly asked for.
                if col not in table_columns(table):
                    _owners = [
                        _o for _o, _cols in STATIC_TABLE_COLUMNS.items()
                        if col in _cols and _o != table
                        and (table, _o) in JOIN_KEY_MAP
                    ]
                    if len(_owners) == 1:
                        foreign_requested[col] = _owners[0]
                    continue
                prev_word = tokens[i - 1] if i > 0 else None
                next_word = tokens[i + 1] if i + 1 < len(tokens) else None
                value_list = DESCRIPTOR_VALUE_LISTS.get(col)
                # the category value can sit on either side of its column
                # name - "bangalore city" AND "city bangalore", "hr
                # department" / "department hr" - in both cases the column
                # word is describing a filter value, not a column to display
                if value_list is not None and (prev_word in value_list or next_word in value_list):
                    continue
                if col not in selected_columns:
                    selected_columns.append(col)
                    selected_column_indices.append(i)

    # "show subjects and their max marks" / "show all projects and their
    # budgets" ask for every column of the whole table - "their <column>" just
    # describes the table, not a projection. Only columns that appear AFTER the
    # "their" are dropped, so "show student names and their marks" keeps the
    # explicitly requested name while "show subjects and their max marks"
    # becomes SELECT *.
    if selected_columns and "their" in tokens:
        _their_idx = tokens.index("their")
        if all(i > _their_idx for i in selected_column_indices):
            selected_columns = []

    # "show exam, marks and result" - every word echoed the marks table, but
    # three of them is the user naming three columns, not just the table. Only
    # a lone echo stays folded into "show the whole table".
    if not selected_columns and len(echoed_table_columns) > 1:
        for _col in echoed_table_columns:
            if _col in table_columns(table) and _col not in selected_columns:
                selected_columns.append(_col)

    # ---------------- ALIASES (AS) ----------------
    # e.g. "show salary as pay" -> SELECT salary AS pay

    column_aliases = {}

    for i, word in enumerate(tokens):
        if word == "as" and i > 0 and i + 1 < len(tokens):
            prev_word = tokens[i - 1]
            if prev_word in COLUMN_MAP:
                column_aliases[COLUMN_MAP[prev_word]] = tokens[i + 1]

    # A table word immediately followed by a number is naming which one, not
    # asking to see that table: "show students in course 1" wants students.
    # The column it selects is also the column it filters, so
    # `SELECT course_id ... WHERE course_id = 1` answers with the filter value
    # repeated. Drop the selection and let the row itself be the answer.
    _filter_only_tables = set()
    for _i, _word in enumerate(tokens[:-1]):
        _hint = TABLE_MAP.get(_word) or JOIN_TABLE_HINTS.get(_word)
        if _hint and _hint != table and tokens[_i + 1].isdigit():
            _filter_only_tables.add(_hint)
    if _filter_only_tables and selected_columns:
        _filter_only_columns = set()
        for _t in _filter_only_tables:
            _filter_only_columns |= {_t} | table_columns(_t)
        selected_columns = [
            c for c in selected_columns if c not in _filter_only_columns
        ]

    # "show projects started in 2024" projects ONE column, and that column is
    # also the one being filtered - `SELECT start_year ... WHERE start_year =
    # 2024` answers a question nobody asked. When the question named a table
    # and every column it "selected" is just a filter/group target, the real
    # intent was rows of that table, so drop the narrowing.
    if selected_columns:
        _filter_targets = {
            condition_column, null_column, group_by_column, like_column,
            ifnull_column, case_column,
        }
        _filter_targets.update(col for col, _v, _n in categorical_values)
        _filter_targets.discard(None)
        if (
            any(w in TABLE_MAP and TABLE_MAP[w] == table
                for w in tokens[intent_word_idx:end_idx]) if intent_word_idx is not None else False
        ) and all(c in _filter_targets for c in selected_columns):
            selected_columns = []

    if selected_columns:
        select_parts = []
        for col in selected_columns:
            if col in column_aliases:
                select_parts.append(f"{col} AS {column_aliases[col]}")
            else:
                select_parts.append(col)
        select_columns_sql = ", ".join(select_parts)
    else:
        select_columns_sql = "*"

    # ---------------- COLUMN-SPAN JOIN ----------------
    # "show employee name and department name" names two columns that live on
    # two different tables. Nothing else in the sentence hints at a join ("and"
    # is not a join trigger), so the second column used to be dropped and the
    # user silently got half of what they asked for. When every requested
    # foreign column is owned by ONE reachable table, join it in and project
    # those columns - that is the only reading of the sentence that returns
    # what was asked for.
    if foreign_requested and second_table is None and not union_second_table:
        _owners = set(foreign_requested.values())
        if len(_owners) == 1:
            _owner = _owners.pop()
            second_table = _owner
            join_type = "INNER JOIN" if join_type is None else join_type
            if selected_columns:
                # the question named concrete columns on BOTH sides
                for _col in foreign_requested:
                    if _col not in selected_columns:
                        selected_columns.append(_col)
                _reparts = []
                for _col in selected_columns:
                    _reparts.append(
                        f"{_col} AS {column_aliases[_col]}" if _col in column_aliases
                        else _col
                    )
                select_columns_sql = ", ".join(_reparts)
            else:
                # "show employees and their department names" projects the
                # employees, annotated with the department name - so show the
                # whole employee row, not just the borrowed column
                select_columns_sql = "*"

    # ---------------- DEFAULT NUMERIC COLUMN ----------------
    # The column a bare "highest"/"top 3"/"average of" falls back to when the
    # question names no numeric column of its own. One per table in the live
    # schema; every table has at least one usable numeric column, so a sort
    # or aggregate never has to invent one.

    if not numeric_column:
        numeric_column = DEFAULT_NUMERIC_COLUMN.get(table)

    # A numeric target that the resolved table spells differently is still the
    # column being asked about: subject stores the ceiling as `max_marks`, so
    # "the maximum marks of subjects" means MAX(max_marks), not a bare
    # SELECT *. Only a column whose name actually contains the requested word
    # qualifies, and only when there is exactly one such column - so this can
    # never invent a target or guess between two candidates.
    if numeric_column and numeric_column not in table_columns(table):
        _part = numeric_column
        _cands = [
            c for c in table_columns(table)
            if c != numeric_column and _part in c.split("_")
        ]
        if len(_cands) == 1:
            numeric_column = _cands[0]

    if order_requested and not order_by_column:
        order_by_column = numeric_column

    # "show projects in department 2" filters on the department the project
    # belongs to, but the bare number had no column of its own and fell back
    # to the table's default numeric one, so the query became
    # `project_id = 2` - a different question that happens to run. A table
    # word sitting right in front of a number names the key to compare.
    _table_key_columns = set()
    for _i, _word in enumerate(tokens[:-1]):
        if not tokens[_i + 1].isdigit():
            continue
        _hint = TABLE_MAP.get(_word) or JOIN_TABLE_HINTS.get(_word)
        if not _hint or _hint == table:
            continue
        for _key in (f"{_hint}_id", f"{_hint.rstrip('s')}_id"):
            if _key in table_columns(table):
                _table_key_columns.add(_key)
    if len(_table_key_columns) == 1:
        numeric_column = _table_key_columns.pop()
        if condition_column in (None, DEFAULT_NUMERIC_COLUMN.get(table)):
            condition_column = numeric_column

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
                cond = parse_or_clause(part_tokens, default_column=numeric_column, table=table)
                if cond:
                    parsed_or_conditions.append(cond)

            if len(parsed_or_conditions) >= 2:
                # an OR branch naming a column the table lacks would fail the
                # whole query, so drop those branches before using the clause
                _real_cols = table_columns(table)
                parsed_or_conditions = [
                    c for c in parsed_or_conditions
                    if c.split(" ")[0] in _real_cols
                ]

            if len(parsed_or_conditions) >= 2:
                cols_in_or = {c.split(" ")[0] for c in parsed_or_conditions}
                all_equality = all(" = " in c for c in parsed_or_conditions)
                same_column_list = (len(cols_in_or) == 1 and all_equality)

                if not same_column_list:
                    or_where_clause = " OR ".join(parsed_or_conditions)

    # ---------------- BUILD CONDITIONS ----------------

    # Departments are rows of the `department` table, not a text column: the
    # tables that belong to one (employee_info, project) hold only a
    # Department_ID. So a name like "IT" has to be resolved through that
    # table rather than compared directly.
    if department_values:
        if "department_name" in table_columns(table):
            # the question is already about the department table itself
            dept_condition = build_categorical_condition(
                "department_name", department_values,
                use_in or len(department_values) > 1,
                not_in=has_not_in,
            )
        elif "department_id" in table_columns(table):
            dept_condition = build_department_id_condition(
                department_values, use_in or len(department_values) > 1,
                not_in=has_not_in,
            )
        else:
            # this table has no relationship to a department at all
            # (student_info, marks, course, ...) - the words are a false
            # positive, e.g. the "IT" in a course name
            dept_condition = None
        if dept_condition:
            conditions.append(dept_condition)

    # "city" is just another word for Address in this schema
    if "address" in table_columns(table):
        city_condition = build_categorical_condition(
            "address", city_values, use_in or len(city_values) > 1, not_in=has_not_in
        )
        if city_condition:
            conditions.append(city_condition)

    # exam / result values, grouped per column so "internal or final" becomes
    # one IN (...) and negation ("who did not pass") still works. The column
    # may live on the joined table rather than the main one, which is exactly
    # what made "students who failed the midterm" a two-table question.
    if categorical_values:
        _visible_cols = set(table_columns(table))
        if second_table:
            _visible_cols |= set(table_columns(second_table))

        _cat_by_column = {}
        for _col, _val, _neg in categorical_values:
            if _col in _visible_cols:
                _cat_by_column.setdefault(_col, []).append((_val, _neg))

        for _col, _pairs in _cat_by_column.items():
            _negative = _pairs[0][1]
            if len(_pairs) == 1:
                _op = f"= '{_pairs[0][0]}'" if not _negative else f"!= '{_pairs[0][0]}'"
            else:
                _kw = "NOT IN" if _negative else "IN"
                _op = f"{_kw} ({', '.join(chr(39) + v + chr(39) for v, _ in _pairs)})"
            conditions.append(f"{_col} {_op}")


    if name_value:
        name_column = resolve_column("name", table)
        if name_is_partial:
            # The user named a row by a short form of the stored value
            # ("ananya" for "Ananya Singh"). An equality test against the
            # full stored value would only work if the value happened to be
            # an exact match, so match on containment instead.
            conditions.append(
                f"{name_column} LIKE '%{name_value}%'"
            )
        else:
            conditions.append(
                f"{name_column} = '{name_value}'"
            )

    # ---------------- SCHEMA GUARD ON WHERE TARGETS ----------------
    # Every WHERE target has to be a real column that is actually in scope. A
    # JOIN puts the joined table's columns in scope too, so "students with
    # marks above 80" (which joins marks) is legal SQL rather than an invented
    # column - the column is only accepted from a joined table when the main
    # table has no column of that name, so the reference stays unambiguous and
    # MySQL never sees a duplicate identifier. What is still rejected is a
    # keyword that maps to no reachable column at all, or an abstract
    # pseudo-column ("department" - the names live in the department table).
    # Rather than emit SQL that cannot run, drop the condition: the question
    # then degrades to a plain listing, and the caller can escalate.
    _real_cols = set(table_columns(table))
    _joined_cols = set()
    for _jt in (second_table, union_second_table):
        if _jt and _jt != table:
            _joined_cols |= set(table_columns(_jt))
    _real_cols |= _joined_cols - _real_cols

    if null_column not in _real_cols:
        null_column = None
    if like_column not in _real_cols:
        like_column = None
    if condition_column not in _real_cols:
        between_values = None
        value_condition = None
        value = None
        condition_is_having = False

    # ---------------- UNEXPRESSIBLE COMPARISON CHECK ----------------
    # A comparison the question asked for but this engine cannot build must
    # NOT degrade into a plain listing: "students whose marks are greater than
    # ALL students taking Mathematics" needs marks compared against a scoped
    # subset, and silently dropping the comparison returns every student - a
    # confidently wrong answer. Recording the reason makes
    # has_recognizable_keywords() report the question as unrecognised, so the
    # hybrid router runs it on the agentic engine instead. Checked here, right
    # after the schema guard, because that is the last point where both the
    # comparison target and the tables in scope are known.
    if any_all_keyword:
        _any_all_sub_table = any_all_sub_table or table
        _any_all_sub_col = any_all_sub_column or condition_column
        # "budget greater than any PROJECT" names an entity, not a measure, so
        # the scan for a column after ANY/ALL lands on the table's key. A key
        # can never be the thing on the right of a quantified comparison -
        # comparing a budget to a project_id is not a question anyone asked - so
        # the key is dropped in favour of the outer measure, which is what
        # "any project" means: any project's budget. When that measure is not
        # in the sub-table either ("marks greater than any STUDENT from
        # Mysore"), the scope genuinely cannot be built and the checks below
        # decline it, which is the point of them.
        if any_all_sub_column and _any_all_sub_col.endswith("_id") \
                and _any_all_sub_col[:-3].rstrip("s") in _any_all_sub_table:
            _any_all_sub_col = condition_column
        if (
            value_condition not in ("above", "below", "gte", "lte")
            or condition_column not in _real_cols
            or not _any_all_sub_col
            or _any_all_sub_col not in table_columns(_any_all_sub_table)
        ):
            ESCALATION_REASONS.add(
                f"{value_condition or 'ANY/ALL'} {any_all_keyword} comparison on "
                f"{_any_all_sub_col} that the rule engine cannot scope"
            )
            any_all_keyword = None

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
    # ISO-date values ("2026-05-01") must be quoted in SQL; bare numbers stay bare.
    def sql_value(v):
        if v is None:
            return None
        is_date = str(v).count("-") == 2 and all(p.isdigit() for p in str(v).split("-"))
        return f"'{v}'" if is_date else str(v)

    if between_values:
        between_keyword = "NOT BETWEEN" if between_negated else "BETWEEN"
        conditions.append(
            f"{condition_column} {between_keyword} {sql_value(between_values[0])} AND {sql_value(between_values[1])}"
        )

    elif value_condition == "above" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} > {sql_value(value)}"
        )

    elif value_condition == "below" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} < {sql_value(value)}"
        )

    elif value_condition == "on_or_after" and value:
        conditions.append(
            f"{condition_column} >= {sql_value(value)}"
        )

    elif value_condition == "on_or_before" and value:
        conditions.append(
            f"{condition_column} <= {sql_value(value)}"
        )

    elif value_condition == "equal" and value:
        conditions.append(
            f"{condition_column} = {sql_value(value)}"
        )

    elif value_condition == "gte" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} >= {sql_value(value)}"
        )

    elif value_condition == "lte" and value and not condition_is_having:
        conditions.append(
            f"{condition_column} <= {sql_value(value)}"
        )

    # ---------------- NAMED-PERSON COMPARISON ----------------
    # "employees earning more than RAVI" / "students with marks less than
    # PRIYA" - the comparison target is a person's name, not a number. The
    # name resolves to that person's own value in the same column, looked up
    # in a subquery: premise staff, "salary > (SELECT salary FROM employees
    # WHERE name = 'Ravi')". Only fires when no numeric value was given, no
    # BETWEEN pair was found, and the word after the operator isn't a known
    # keyword. Without the BETWEEN guard the word "between" is itself read as
    # the name being compared against, so "semester between 3 and 4" also emits
    # `AND semester = (SELECT semester FROM subject WHERE subject_name =
    # 'Between')` - a second condition that matches no subject ever.
    if (
        value is None
        and between_values is None
        and condition_column
        and value_condition in ("above", "below", "equal")
    ):
        name_comp_idx = None
        if value_condition_idx is not None:
            j = value_condition_idx + 1
            # jump filler words AND any re-mention of the column being
            # compared ("greater than the SALARY OF Amit") so the scan lands
            # on the actual person's name
            while j < len(tokens) and (
                tokens[j] in ("than", "to", "as", "the", "of", "for", "with", "in")
                or tokens[j] in COLUMN_MAP
            ):
                j += 1
            if j < len(tokens):
                name_comp_idx = j

        if name_comp_idx is not None:
            cand = tokens[name_comp_idx]
            known_words = set(TABLE_MAP) | set(COLUMN_MAP) | set(DEPARTMENTS) \
                | set(CITIES) | set(GENDERS) | set(CONDITION_MAP) \
                | set(INTENT_MAP) | set(AGGREGATE_MAP)
            STOP_WORDS = {
                "the", "than", "to", "as", "a", "an", "of", "and", "or",
                "all", "any", "each", "every", "average", "most", "their",
                "who", "whose", "with", "for", "from", "in",
                "overall", "total", "everyone", "everybody", "anyone", "anybody",
                "both", "others", "other", "each",
            }
            if (
                cand not in known_words
                and cand not in STOP_WORDS
                and cand not in _NAME_STOP_WORDS
                and not cand.isdigit()
                # A function word is never the name being compared against.
                # "employees whose department is not null" used to compare
                # employee_name = 'Not' - a value no row has, so the subquery
                # returned NULL and the whole filter vanished, leaving the
                # question answered as if nothing had been asked. _is_literal_value
                # is the single place that decides whether a word is filling a
                # grammatical slot, so ask it rather than growing a second list
                # that is guaranteed to miss one.
                and _is_literal_value(cand, tokens, name_comp_idx)
            ):
                op_map = {"above": ">", "below": "<", "equal": "="}
                # The name is often several words. Taking one token and
                # capitalising it gives `project_name = 'Crm'` for "CRM
                # Migration" - a value no row has, so the subquery returns
                # NULL and the query answers with nothing at all. Resolve the
                # whole run to the spelling the database actually stores.
                target = _match_name_span(tokens, name_comp_idx, tables=(table,)) \
                    or cand.capitalize()
                # the row is named through whichever *_name column the table
                # has; comparing against a column the table lacks would error
                if condition_column in table_columns(table):
                    name_col = resolve_column("name", table)
                    conditions.append(
                        f"{condition_column} {op_map[value_condition]} "
                        f"(SELECT {condition_column} FROM {table} "
                        f"WHERE {name_col} = '{target}')"
                    )

    # ---------------- AGGREGATE-SUBQUERY COMPARISON ----------------
    # "budget greater than the AVERAGE budget of all projects" means
    # budget > (SELECT AVG(budget) FROM project) - the aggregate word inside
    # the comparison becomes a subquery summary, not a top-level aggregate.
    # The outer SELECT keeps the user's requested columns.
    if (
        aggregate_subquery_function
        and condition_column
        and value_condition in ("above", "below", "equal", "gte", "lte")
    ):
        op_map = {"above": ">", "below": "<", "equal": "=", "gte": ">=", "lte": "<="}
        sub_col = any_all_sub_column if any_all_sub_column else condition_column

        # The subquery has to average the SAME column the outer WHERE filters
        # on, so it must read from whichever table actually owns that column.
        # "students whose marks are higher than the average marks" filters on
        # marks.Marks via a join, but the main table is student_info - reading
        # AVG(marks) FROM student_info is a query about the wrong table.
        sub_table = table
        if sub_col and sub_col not in table_columns(sub_table):
            for _jt in (second_table, union_second_table):
                if _jt and sub_col in table_columns(_jt):
                    sub_table = _jt
                    break
            else:
                # the column being compared lives on a table that is two hops
                # away (marks needs student AND subject together) - the rule
                # engine can only build single JOINs, so rather than emit an
                # aggregate over a column no table in the FROM clause has,
                # hand the question to the agentic engine
                if sub_col:
                    ESCALATION_REASONS.add(
                        f"aggregate over {sub_col}, which is not reachable "
                        f"from {table} in a single join"
                    )

        # "greater than the MAXIMUM budget in the IT department" - the
        # subquery should be scoped to IT too, otherwise the outer filter
        # compares against the whole-table max. Scope by whatever qualifier
        # (department/address) was mentioned.
        sub_scope = ""
        if department_values:
            if "department_id" in table_columns(sub_table):
                sub_scope = (
                    f" WHERE {build_department_id_condition(department_values[-1:], False)}"
                )
            else:
                sub_scope = f" WHERE department_name = '{department_values[-1][0]}'"
        elif city_values and "address" in table_columns(sub_table):
            sub_scope = f" WHERE address = '{city_values[-1][0]}'"

        # "projects whose budget is higher than the average budget of projects
        # FROM THEIR department" - "their" makes it a CORRELATED per-group
        # comparison: each row compares against the average of the group it
        # belongs to, not a whole-table average. The grouping category is
        # the word that follows "their".
        correlated_by = None
        if "their" in tokens:
            t_idx = tokens.index("their")
            if t_idx + 1 < len(tokens):
                cat_word = tokens[t_idx + 1]
                if cat_word in COLUMN_MAP:
                    candidate = COLUMN_MAP[cat_word]
                    # an abstract keyword can't be correlated on, and the
                    # column has to exist on BOTH sides of the subquery
                    if candidate != "department" and candidate in table_columns(table):
                        correlated_by = candidate

        if correlated_by:
            conditions.append(
                f"{condition_column} {op_map[value_condition]} "
                f"(SELECT {aggregate_subquery_function}({sub_col}) FROM {sub_table} t2 "
                f"WHERE t2.{correlated_by} = {sub_table}.{correlated_by})"
            )
        else:
            conditions.append(
                f"{condition_column} {op_map[value_condition]} "
                f"(SELECT {aggregate_subquery_function}({sub_col}) FROM {sub_table}{sub_scope})"
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
    # "count employees in each department" has to group on a readable name,
    # but employee_info/project only hold a numeric Department_ID. When the
    # grouping column is the abstract "department", the department table is
    # joined in and aliased `d` so the query can show and group on
    # d.department_name. LEFT JOIN, not INNER: a row with a NULL/unmatched
    # Department_ID must still appear in its group rather than vanish.
    def _planned_chain_tables():
        """Every table the join planner will attach, not just second_table.

        The chain can be longer than two tables - performance reaches
        department only through employee_info - and a decision made here
        against only the first hop is wrong for every question that needs the
        third. At this point second_table is still None, because the extra
        tables are resolved from the whole question further down; asking the
        planner for the same set keeps this decision and the FROM clause that
        eventually gets rendered in step.

        Imported inside the function because join_planner reads this module's
        own maps, and the module-level import of it is deliberately deferred
        until after they exist.
        """
        from services.join_planner import (
            find_bridges,
            plan_join_chain,
            resolve_question_tables,
        )

        _extras = [t for t in resolve_question_tables(
            tokens, table, selected_columns
        ) if t != table]
        if not _extras:
            return set()
        _extras = _extras + [b for b in find_bridges(table, _extras)
                             if b not in _extras]
        _steps, _miss = plan_join_chain(table, _extras, "INNER JOIN")
        if _miss:
            return set()
        return {t for t, _ in _steps}

    from_sql = f"FROM {table}"
    department_alias = None
    group_by_clause = ""
    # the expression actually projected/ordered by, which differs from the raw
    # group_by_column keyword when the department table had to be joined in
    # ("count employees in each department" -> GROUP BY d.department_name, so
    # the SELECT must say d.department_name too, not the bare word
    # "department" that no table has a column for)
    group_select_col = group_by_column

    if group_by_column:
        if group_by_column == "department":
            if "department_name" in table_columns(table):
                # already the department table - the name is right here
                group_by_clause = " GROUP BY department_name"
                group_select_col = "department_name"
            elif "department_id" in table_columns(table):
                department_alias = "d"
                from_sql = (
                    f"FROM {table} LEFT JOIN department d "
                    f"ON {table}.department_id = d.department_id"
                )
                group_by_clause = " GROUP BY d.department_name"
                group_select_col = "d.department_name"
            elif second_table == "department":
                # the department table is already joined in under its own
                # name, so group on the qualified column rather than adding a
                # second join of the same table under an alias
                group_by_clause = " GROUP BY department.department_name"
                group_select_col = "department.department_name"
            elif "department" in _planned_chain_tables():
                # ...or it is one hop further out than second_table. "the
                # average rating for each department" starts from performance,
                # so the chain is performance -> employee_info -> department and
                # department is neither the driving table nor the first join.
                # Checking only those two made the GROUP BY disappear and left
                # a single global AVG(rating) answering a per-group question -
                # one number where the question asked for one per department.
                group_by_clause = " GROUP BY department.department_name"
                group_select_col = "department.department_name"
            else:
                # the table has nothing to do with departments
                group_by_column = None
        elif group_by_column == "department_name" and (
                second_table == "department"
                or "department" in _planned_chain_tables()):
            # "the number of employees per department NAME" - the readable
            # column only exists on the joined department table
            group_by_clause = " GROUP BY department.department_name"
            group_select_col = "department.department_name"
        if group_by_column and not group_by_clause:
            # every other grouping target is a real column of the table
            if group_by_column == "name" or group_by_column not in table_columns(table):
                group_by_column = None
            else:
                group_by_clause = f" GROUP BY {group_by_column}"
                group_select_col = group_by_column
        if not group_by_column:
            group_select_col = None

    # Now that the grouping is settled, a superlative over it is a per-group
    # MAX/MIN. Left as a ranking it becomes a global ORDER BY ... LIMIT 1, and
    # "the highest budget in each department" then returns one department's
    # single largest project as though it were the answer for all of them. The
    # projection is built from aggregate_function, so that is what has to be
    # set here. Only when the sentence named no aggregate of its own, and only
    # over a different column than the grouping, so "the highest marks of each
    # student" still groups rather than aggregating the key it groups on.
    if (
        aggregate_function is None
        and group_by_column
        and record_condition in RECORD_CONDITION_TYPES
        and numeric_column
        and numeric_column not in group_by_column
        and numeric_column != "name"
    ):
        aggregate_function = "MAX" if record_condition == "highest" else "MIN"

    # ---------------- HAVING ----------------

    having_clause = ""
    op_symbol_map = {"above": ">", "below": "<", "gte": ">=", "lte": "<="}

    if condition_is_having and value_condition in op_symbol_map and value is not None:
        having_agg = "COUNT(*)" if intent == "count" else f"{aggregate_function}({numeric_column})"
        having_clause = f" HAVING {having_agg} {op_symbol_map[value_condition]} {value}"

    # ---------------- ORDER BY / LIMIT (for the default / non-aggregate paths) ----------------

    # "top 3 students by marks" ranks a column that lives on the joined table,
    # so the ORDER BY has to be qualified - `ORDER BY marks` is ambiguous once
    # two tables are in scope, while `ORDER BY marks.marks` is not.
    if second_table and numeric_column in table_columns(second_table) \
            and numeric_column not in table_columns(table):
        rank_column = f"{second_table}.{numeric_column}"
    elif numeric_column:
        rank_column = numeric_column
    else:
        rank_column = None

    order_by_clause = ""
    limit_clause = ""

    if record_condition is None:

        if order_requested and order_by_column:
            # "order by department" can't sort on a readable name - the tables
            # that belong to one store only a numeric Department_ID
            if order_by_column == "department":
                order_by_column = (
                    "department_id" if "department_id" in table_columns(table) else None
                )
            if order_by_column:
                order_by_clause = f" ORDER BY {order_by_column} {order_by_direction}"

        if limit_value:
            limit_clause = f" LIMIT {limit_value}"

    # ---------------- MULTI-TABLE JOIN PLANNING ----------------
    # The two-table join below can only hold two tables, which left several
    # real questions unanswerable by the rules:
    #   * a question naming three tables ("project names along with the
    #     employees rating them"),
    #   * one where the projection reaches a table nothing joined ("show
    #     students along with their course and their marks" lost the marks),
    #   * one whose join is implied only by a possessive ("show employees
    #     with their department names" - no trigger word, so no join at all),
    #   * and one where the two-table path invented a relationship that does
    #     not exist ("show student names along with employee names" emitted
    #     ON student_info.id = employee_info.id, on a column neither table
    #     has).
    #
    # The planner takes over whenever the question joins at all. It derives
    # the real foreign keys from the live schema, connects every table the
    # question names into one tree (bridging through intermediate tables when
    # a pair is two hops apart), and projects each requested column from
    # whichever table owns it. When it cannot connect something, that is
    # recorded as an escalation reason and the bogus two-table fallback is
    # suppressed, so the agentic layer answers rather than the rules
    # fabricating a relationship.
    _multi_sql = None

    # EXISTS no longer blocks this. "the project name, the department it
    # belongs to and the employees working on it" fires the EXISTS rule on
    # "the department it belongs to" and used to stop there, answering about
    # projects and departments while dropping the employees the question
    # actually asked for. A planned chain that already contains the EXISTS
    # pair makes the subquery redundant, so the planner is free to take over.
    if (
        not union_second_table
        and not any_all_keyword
        and not case_column
    ):

        from services.join_planner import (  # lazy: join_planner needs the maps above
            chain_columns as _chain_columns,
            column_owners,

            connect_reason,
            fanout_risk,
            find_bridges,
            has_join_intent,
            plan_join_chain,
            qualify,
            qualify_clause,
            retarget_comparison,

            render_from_chain,
            render_tail,
            resolve_question_tables,
        )

        _requested = [c for c in selected_columns if c and c != "*"]
        _candidate_tables = resolve_question_tables(tokens, table, _requested)
        _extra = [t for t in _candidate_tables if t != table]

        # "show students in course 1" names course only to say which one, and
        # the driving table already holds course_id - so the filter never needs
        # the course table at all. Left alone, the planner joined it and then
        # projected ITS column, answering with a list of course names and not
        # the students that were asked for. A table word followed immediately
        # by a number is a filter, never a request to show that table.
        if _filter_only_tables:
            _extra = [t for t in _extra if t not in _filter_only_tables]

        # A person named in the question whose row lives elsewhere: "show
        # ananya marks" is a question about marks, filtered to one student. The
        # table holding that student has to be on the chain or the WHERE cannot
        # reach it.
        _person_table = person_filter[0] if person_filter else None
        if _person_table and _person_table != table and _person_table not in _extra:
            _extra.append(_person_table)

        # "students with marks equal to the maximum marks in any subject" asks
        # for a comparison against an aggregate, which only a correlated
        # subquery can express. The aggregate-subquery rules above are what
        # build it; if they did not fire, planning a join chain would only
        # swap one wrong answer for another - a bare MAX(marks) over the whole
        # table. Decline and let the agentic layer have it.
        _aggregate_comparison = (
            aggregate_subquery_function is None
            and aggregate_function in ("AVG", "SUM", "MIN", "MAX")
            and numeric_column is not None
            and numeric_column not in table_columns(table)
            and any(
                CONDITION_MAP.get(t) in VALUE_CONDITION_TYPES
                or t in STRONG_COMPARISON_WORDS
                for t in tokens
            )
        )
        if _aggregate_comparison:
            ESCALATION_REASONS.add(
                f"comparing {numeric_column} against an aggregate needs a "
                f"correlated subquery, which the rule engine cannot build"
            )
            _extra = []

        # The engine's own `second_table` is a guess made from a single token,
        # and it is sometimes a table the question never named - "employee
        # names, project names and ratings" drags in department that way. The
        # tables resolved from the question itself win; the guess is only
        # consulted when the question named nothing else to join.
        if not _extra and second_table:
            _extra = [second_table]

        # Worth planning whenever the question reaches a table at all.
        # `resolve_question_tables` only ever returns tables that share a real
        # key with the driving one, so a non-empty result already means the
        # question is about more than one table - "list the course name,
        # subject name and marks of every student" names four of them and
        # joins on nothing but the list.
        if _extra:

            # A pair with no direct key is often still answerable through an
            # intermediate table - employee_info and project are both related
            # to performance, which is where their real relationship lives.
            _bridged = find_bridges(table, _extra)
            if _bridged:
                _extra = _extra + _bridged

            _steps, _missing = plan_join_chain(table, _extra, join_type or "INNER JOIN")

            for _m in _missing:
                ESCALATION_REASONS.add(connect_reason(table, _m) or f"cannot connect {_m}")

            if _missing:
                # The question names something no key path reaches. The
                # two-table path would answer it with a made-up ON clause, so
                # that path is switched off and the planner below declines;
                # the escalation above routes it to the agentic layer.
                second_table = None
                join_type = None
            elif _steps:
                _chain = [table] + [t for t, _ in _steps]
                _kind = join_type or "INNER JOIN"

                # Now that the chain is known, a comparison that was aimed at
                # a key column can be moved onto the measure the sentence names
                # ("scored above 80" is about marks, not student_id).
                where_clause = retarget_comparison(
                    where_clause, _chain, table, tokens
                )

                # The named person is now a real WHERE on the joined table.
                # Until this existed the engine dropped the name and answered
                # with every mark row, which is a wrong answer presented as a
                # right one.
                if person_filter:
                    _pt, _pc, _pv, _p_exact = person_filter
                    if _pt in _chain:
                        _op = f"= '{_pv}'" if _p_exact else f"LIKE '%{_pv}%'"
                        _cond = f"{_pt}.{_pc} {_op}"
                        where_clause = (
                            f"{where_clause} AND {_cond}"
                            if where_clause
                            else f" WHERE {_cond}"
                        )
                    else:
                        ESCALATION_REASONS.add(
                            f"cannot filter by the named person because "
                            f"{_pt} is not reachable from {table}"
                        )


                # The column scan runs before the tables are known, so it
                # silently drops a column whose owning table it could not see
                # yet: "employee names, project names and ratings" lost
                # project_name because project was only reachable through
                # performance. The merged tokens still spell it out, so any
                # token that is a real column of a table in the chain is put
                # back.
                _mentioned = [t for t in tokens if t in _chain_columns(_chain)]
                for _c in _mentioned:
                    if _c not in _requested and _c not in ("*",):
                        _requested.append(_c)

                _owners = column_owners(_requested, _chain)

                # "show every subject and its course" resolves to course_id,
                # because that is the column a bare "course" maps to. The
                # sentence wants the course, not its key - unless it actually
                # asked for the id, number or code.
                _wants_ids = any(
                    t in ("id", "ids", "identifier", "number", "code", "key")
                    for t in tokens
                )
                if not _wants_ids:
                    for _i, _c in enumerate(_requested):
                        if not _c.endswith("_id"):
                            continue
                        _base = _c[:-3]
                        for _t in _chain:
                            if _base not in _t and _t not in _base:
                                continue
                            _named = resolve_column("name", _t)
                            if _named and (_base in tokens or _t in tokens):
                                _requested[_i] = _named
                            break

                _owners = column_owners(_requested, _chain)

                # Any requested column that NO table in the chain owns cannot
                # be projected. Dropping it keeps the rest of the answer
                # usable instead of failing the whole statement.
                _projectable = [c for c in _requested if _owners.get(c)]
                _lost = [c for c in _requested if not _owners.get(c)]
                for _c in _lost:
                    UNSUPPORTED_CONCEPT_TOKENS.add(_c)


                def _qualified(col, projection=False):
                    """One column, table-prefixed where the join makes the
                    bare name ambiguous."""
                    return qualify([col], column_owners([col], _chain), table, _chain,
                                   projection=projection)[0]

                # "the number of employees per department" groups by a TABLE,
                # not a column. Left bare, MySQL is handed `GROUP BY
                # department` and rejects it. The readable grouping is that
                # table's name column - the one the question named, not just
                # the first table in the chain, which for this question is
                # employee_info and would group by student... employee_name.
                _group_by = group_by_column
                if _group_by and not any(
                    _group_by.lower() in table_columns(t) for t in _chain
                ):
                    _group_table = (
                        TABLE_MAP.get(_group_by) or JOIN_TABLE_HINTS.get(_group_by)
                    )
                    _group_by = None
                    for _t in ([_group_table] if _group_table in _chain else []) + _chain:
                        _named = resolve_column("name", _t)
                        if _named:
                            _group_by = _named
                            break
                    if _group_by is None:
                        _group_by = group_by_column

                # "the number of students per course" groups by course_id and
                # reports 1, 2, 3 - a count labelled by a key nobody recognises.
                # The course table is already on the chain, so the readable
                # grouping is its name, and it groups identically. Same for
                # "the average marks per subject". Only skipped when the
                # sentence asked for the id itself.
                if _group_by and _group_by.endswith("_id"):
                    _base = _group_by[:-3]
                    _named_owner = next(
                        (
                            _t for _t in _chain
                            if _t in (f"{_base}s", _base)
                            and f"{_base}_name" in table_columns(_t)
                        ),
                        None,
                    )
                    if _named_owner and f"{_base} id" not in question:
                        _group_by = f"{_named_owner}.{_base}_name"

                # The engine's own GROUP BY is rendered with a table alias
                # ("GROUP BY d.department_name") that does not exist in a
                # planned chain, so the grouping is rebuilt from the column
                # resolved above instead of reusing that clause.
                _group_clause = f" GROUP BY {_qualified(_group_by)}" if _group_by else None

                _select_parts = []

                for _c in _projectable:
                    _alias = column_aliases.get(_c)
                    _rendered = _qualified(_c, projection=True)

                    _select_parts.append(f"{_rendered} AS {_alias}" if _alias else _rendered)

                if _select_parts and not any(
                    _owners.get(c) == [table] for c in _projectable
                ) and table in _chain and not person_filter:
                    # The question asked for an entity the projection dropped:
                    # "show every subject and its course" resolves to
                    # course_name, and a list of course names does not tell you
                    # which subject is which. Whatever the sentence opened with
                    # is an entity it wants rows of, so give it its row back.
                    _select_parts.insert(0, f"{table}.*")

                # Same loss, one hop further along: "show project names along
                # with the employees rating them" joins employee_info and then
                # projects nothing from it, so the answer is a list of projects
                # with numbers and no indication of who rated them. A table the
                # sentence named as an entity has to put its name in the output
                # if nothing else of it is already there.
                if _select_parts and not person_filter and not _group_by:
                    _shown = {
                        _o[0] for _o in (_owners.get(c) for c in _projectable) if _o
                    }
                    if _select_parts and _select_parts[0] != f"{table}.*":
                        _shown.add(table)
                    for _t in _chain:
                        if _t in _shown or _t == table or _t in _filter_only_tables:
                            continue
                        if (TABLE_MAP.get(_t) or JOIN_TABLE_HINTS.get(_t)) != _t:
                            continue
                        _name_col = resolve_column("name", _t)
                        if not _name_col or _name_col not in table_columns(_t):
                            continue
                        _select_parts.append(
                            _qualified(_name_col, projection=True)
                        )
                        _shown.add(_t)

                if not _select_parts:
                    if person_filter:
                        # The joined table is only there to filter - the
                        # question asked for the driving table's rows, so
                        # projecting its columns too would just be noise.
                        _select_parts = [f"{table}.*"]
                    else:
                        # The question named no specific column ("show
                        # subjects along with course names") so every table it
                        # asked about contributes its row rather than the
                        # driving table alone.
                        _select_parts = [f"{_t}.*" for _t in _chain]


                # A count over a join has to count DISTINCT driving rows, or
                # "how many students have marks" reports one row per mark.
                if intent == "count" or aggregate_function == "COUNT":
                    _pk = get_primary_keys().get(table, "id").lower()
                    if _pk in table_columns(table):
                        _count_expr = f"COUNT(DISTINCT {table}.{_pk})"
                        if _group_by:
                            _select_parts = [_qualified(_group_by, projection=True), _count_expr]

                        else:
                            _select_parts = [_count_expr]
                    else:
                        # No primary key to count distinctly (marks and
                        # performance have none). Counting rows is then the
                        # honest answer, but a fan-out join would inflate it,
                        # so this is escalated rather than guessed.
                        if fanout_risk(table, _chain):
                            ESCALATION_REASONS.add(
                                f"counting {table} rows across a one-to-many join "
                                f"needs DISTINCT on a key that does not exist"
                            )
                        _select_parts = ["COUNT(*)"]
                elif aggregate_function and aggregate_function != "COUNT" and numeric_column:
                    if column_owners([numeric_column], _chain).get(numeric_column):
                        _agg = f"{aggregate_function}({_qualified(numeric_column)})"
                        if _group_by:
                            _select_parts = [_qualified(_group_by, projection=True), _agg]
                            # "the department with the highest average project
                            # budget" groups and then wants one row. Grouping
                            # alone answers with every department, which is a
                            # different question from the one asked - the
                            # superlative is choosing between the groups, not
                            # summarising each of them. "per"/"each" is the
                            # opposite intent and keeps the full table.
                            if (
                                record_condition in RECORD_CONDITION_TYPES
                                and _group_keyword not in ("per", "each")
                                and not limit_value
                            ):
                                _dir = (
                                    "DESC" if record_condition == "highest"
                                    else "ASC"
                                )
                                order_by_clause = f" ORDER BY {_agg} {_dir}"
                                limit_clause = " LIMIT 1"

                        else:
                            _select_parts = [_agg]
                # "the top 3 students by marks along with their course name"
                # sorts on a column of a joined table, so it needs qualifying,
                # and the LIMIT the ranking rules asked for has to survive.
                # Gated on an actual superlative - a bare numeric column is
                # not a reason to invent an ORDER BY. The rank column arrives
                # already table-qualified ("marks.marks"), so it is matched by
                # its bare name.
                _rank_bare = rank_column.split(".")[-1] if rank_column else None
                if record_condition in ("highest", "lowest") and _rank_bare \
                        and not _group_by \
                        and column_owners([_rank_bare], _chain).get(_rank_bare):
                    _dir = "DESC" if record_condition == "highest" else "ASC"
                    _from_chain = render_from_chain(table, _steps, _kind)
                    _multi_sql = (
                        f"SELECT {', '.join(_select_parts)}\n{_from_chain}"
                        f"{render_tail(where_clause, _group_clause, having_clause, None, f' LIMIT {limit_value}' if limit_value else None, _chain, rank_column=_qualified(_rank_bare), direction=_dir)}"
                    )
                    return _multi_sql.strip()


                _from_chain = render_from_chain(table, _steps, _kind)
                _multi_sql = (
                    f"SELECT {', '.join(_select_parts)}\n{_from_chain}"
                    f"{render_tail(where_clause, _group_clause, having_clause, order_by_clause, limit_clause, _chain)}"
                )

    if _multi_sql:
        return _multi_sql.strip()

    # ---------------- JOIN QUERY ----------------

    if second_table:

        on_clause = build_join_on_clause(table, second_table, explicit_columns=join_columns or None)
        join_select_cols = f"{table}.*, {second_table}.*" if select_columns_sql == "*" else select_columns_sql

        if join_type == "CROSS JOIN":
            join_clause = f" CROSS JOIN {second_table}"   # no ON - true Cartesian product
            return f"""
            SELECT {join_select_cols}
            {from_sql}
            {join_clause}
            {where_clause}
            """.strip()

        if join_type == "FULL OUTER":
            # MySQL has no native FULL OUTER JOIN - emulate it as the
            # UNION of a LEFT JOIN (every row from `table`, matched or
            # not) and a RIGHT JOIN (every row from `second_table`,
            # matched or not). UNION (not UNION ALL) drops the rows that
            # matched on both sides so they aren't duplicated - matching
            # what a real FULL OUTER JOIN returns.
            left_sql = (
                f"SELECT {join_select_cols} {from_sql} "
                f"LEFT JOIN {second_table} ON {on_clause}{where_clause}"
            )
            right_sql = (
                f"SELECT {join_select_cols} {from_sql} "
                f"RIGHT JOIN {second_table} ON {on_clause}{where_clause}"
            )
            return f"{left_sql}\nUNION\n{right_sql}"

        join_clause = f" {join_type} {second_table} ON {on_clause}"

        # A COUNT that arrived WITH the join ("the number of employees per
        # department name") still has to COUNT and GROUP - the plain join
        # return below would project whole rows and answer a different
        # question than the one that was asked.
        if intent == "count":
            _count_select = (
                f"{group_select_col}, COUNT(*)" if group_select_col else "COUNT(*)"
            )
            return f"""
            SELECT {_count_select}
            {from_sql}
            {join_clause}
            {where_clause}{group_by_clause}{having_clause}
            """.strip()

        # A ranking or aggregate that arrived WITH the join ("top 3 students
        # by marks", "which department has the highest average budget") has
        # to keep its ORDER BY / LIMIT here, because the plain join return
        # below would otherwise drop it and return every matching row.
        join_tail = ""
        if rank_column and (record_condition in ("highest", "lowest") or order_requested):
            _dir = "DESC" if record_condition == "highest" else (
                "ASC" if record_condition == "lowest" else order_by_direction
            )
            join_tail = f" ORDER BY {rank_column} {_dir}"
            if record_condition in ("highest", "lowest") and limit_value:
                join_tail += f" LIMIT {limit_value}"
        elif limit_value and not group_by_column:
            join_tail = f" LIMIT {limit_value}"

        if aggregate_function in ("AVG", "SUM", "MIN", "MAX") and rank_column:
            # an aggregate may only wrap a column one of the tables actually
            # in the FROM clause has. "students with marks equal to the maximum
            # marks in any subject" needs marks AND subject AND student
            # together; with only a student/subject join in scope, `MAX(marks)`
            # is not a slow query, it is a query MySQL refuses to parse.
            _rank_bare = rank_column.split(".")[-1]
            if (
                _rank_bare not in table_columns(table)
                and _rank_bare not in table_columns(second_table)
            ):
                ESCALATION_REASONS.add(
                    f"{aggregate_function}({_rank_bare}) needs a join chain "
                    f"the rule engine cannot build from {table}"
                )
                return f"""
                SELECT {join_select_cols}
                {from_sql}
                {join_clause}
                {where_clause}
                """.strip()
            _agg_dir = ""
            if record_condition in ("highest", "lowest"):
                _agg_dir = " ORDER BY " + aggregate_function + f"({rank_column}) " + (
                    "DESC" if record_condition == "highest" else "ASC"
                )
                if not limit_value:
                    _agg_dir += " LIMIT 1"
            # keep the grouping column visible next to the aggregate
            _agg_select = (
                f"{group_select_col}, {aggregate_function}({rank_column})"
                if group_select_col else f"{aggregate_function}({rank_column})"
            )
            return f"""
            SELECT {_agg_select}
            {from_sql}
            {join_clause}
            {where_clause}{group_by_clause}{having_clause}{_agg_dir}
            """.strip()

        return f"""
        SELECT {join_select_cols}
        {from_sql}
        {join_clause}
        {where_clause}{join_tail}
        """.strip()

    # ---------------- UNION QUERY ----------------

    if union_second_table:

        # Columns (and WHERE conditions, further below) that actually exist on
        # BOTH sides of the UNION, read straight from the live schema - a
        # UNION of differently-shaped tables can only render columns common to
        # both (student_info+employee_info share only address/phone_no;
        # marks+subject share Student_ID/Subject_ID, etc.). If the schema is
        # unreachable, fall back to nothing/ID as a safe guess.
        try:
            schema = get_schema()
            _cols_a = {c.lower() for c in schema.get(table, {})}
            _cols_b = {c.lower() for c in schema.get(union_second_table, {})}
            _preferred = (
                "id", "name", "student_id", "subject_id", "course_id",
                "employee_id", "department_id", "project_id",
                "address", "phone_no",
            )
            UNION_SHARED_COLUMNS = [c for c in _preferred if c in _cols_a and c in _cols_b]
            if not UNION_SHARED_COLUMNS:
                UNION_SHARED_COLUMNS = sorted(_cols_a & _cols_b)
        except Exception:
            UNION_SHARED_COLUMNS = ["id"]

        # SELECT * across two differently-shaped tables would break a UNION
        # (mismatched column counts). If specific columns were genuinely
        # requested, keep only the ones valid on both sides (e.g. "marks"
        # or "budget" only exist on one table and would error out on the
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

        # Only reuse WHERE conditions built on columns common to both tables -
        # department, marks, budget, semester, etc. are table-specific and
        # would error out on whichever side of the UNION lacks that column.
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

        # a label can only bucket on a column the table actually has; when it
        # doesn't, the CASE is dropped and this degrades to a plain SELECT
        if case_column not in table_columns(table):
            case_column = None
            case_label_true = None
            case_label_false = None
        else:
            case_sql = (
                f"CASE WHEN {case_column} {op_symbol} {case_value} "
                f"THEN '{case_label_true}' ELSE '{case_label_false}' END AS category"
            )

            return f"""
            SELECT *, {case_sql}
            {from_sql}
            {where_clause}
            """.strip()

    # ---------------- IFNULL / COALESCE QUERY ----------------

    if ifnull_column and ifnull_default:

        if ifnull_column not in table_columns(table):
            ifnull_column = None

    if ifnull_column and ifnull_default:

        default_sql = ifnull_default if ifnull_default.isdigit() else f"'{ifnull_default}'"

        return f"""
        SELECT IFNULL({ifnull_column}, {default_sql}) AS {ifnull_column}
        {from_sql}
        """.strip()

    # ---------------- EXISTS QUERY ----------------

    if exists_second_table:

        # prefer the real foreign-key relationship over the guessed
        # join column - "students who have marks" must check
        # marks.Student_ID = student_info.Student_ID, not a random shared
        # column found in the sentence
        known_key = JOIN_KEY_MAP.get((table, exists_second_table))
        if known_key:
            exists_match = known_key
        elif exists_column in table_columns(table) and exists_column in table_columns(exists_second_table):
            exists_match = f"{exists_second_table}.{exists_column} = {table}.{exists_column}"
        else:
            exists_match = None

        if exists_match:
            exists_where = (
                f" WHERE EXISTS (SELECT 1 FROM {exists_second_table} "
                f"WHERE {exists_match})"
            )

            return f"""
            SELECT {select_columns_sql}
            {from_sql}
            {exists_where}
            """.strip()

        # No usable relationship between the two tables (the rule engine
        # only builds single-hop EXISTS, and this pair needs a bridge table
        # such as `performance`). Clear it so this question falls through to
        # the normal select instead of emitting SQL that cannot run.
        exists_second_table = None

    # ---------------- CATEGORY IN-SUBQUERY ("belong to departments where ...") ----------------
    # "employees who BELONG TO DEPARTMENTS WHERE at least one project has a
    # budget more than 100000" - a category (department/address) filters rows
    # by whether that category CONTAINS any row satisfying a numeric
    # condition, expressed as IN (SELECT DISTINCT category ...).
    if (
        not exists_second_table
        and any(w in tokens for w in ("belong", "belongs"))
        and value is not None
        and value_condition in ("above", "below", "equal", "gte", "lte")
    ):
        cat_col = None
        for w in tokens:
            if w in ("department", "departments", "dept") and "department_id" in table_columns(table):
                cat_col = "department_id"
            elif w in ("city", "cities", "address") and "address" in table_columns(table):
                cat_col = "address"
        if cat_col:
            op_map = {"above": ">", "below": "<", "equal": "=", "gte": ">=", "lte": "<="}
            op = op_map[value_condition]
            # "find EMPLOYEES who belong..." returns the rows, not the
            # category column - only keep narrowed columns when something
            # genuinely narrower was asked for (e.g. "names of employees")
            cat_select = select_columns_sql
            if selected_columns == [cat_col]:
                cat_select = "*"
            return f"""
            SELECT {cat_select}
            {from_sql}
            WHERE {cat_col} IN (SELECT DISTINCT {cat_col} FROM {table}
                                 WHERE {condition_column} {op} {sql_value(value)})
            """.strip()

    # ---------------- ANY / ALL QUERY ----------------

    if any_all_keyword and value_condition in ("above", "below", "gte", "lte") and condition_column:

        op_symbol_map = {"above": ">", "below": "<", "gte": ">=", "lte": "<="}
        sub_table = any_all_sub_table if any_all_sub_table else table
        sub_column = any_all_sub_column if any_all_sub_column else condition_column

        # the comparison column has to exist on a table that is actually in
        # scope - the main table OR the one joined in for it ("students whose
        # marks are greater than ALL ..." compares marks.Marks, which arrives
        # through the marks join, not as a student_info column)
        _outer_ok = (
            condition_column in table_columns(table)
            or (second_table and condition_column in table_columns(second_table))
        )
        if not _outer_ok or sub_column not in table_columns(sub_table):
            any_all_keyword = None

    if any_all_keyword and value_condition in ("above", "below", "gte", "lte") and condition_column:

        op_symbol_map = {"above": ">", "below": "<", "gte": ">=", "lte": "<="}
        sub_table = any_all_sub_table if any_all_sub_table else table
        sub_column = any_all_sub_column if any_all_sub_column else condition_column

        # scope the subquery to whichever qualifier was mentioned -
        # department, address, or a specific semester number - falling back
        # to no filter (compare against every row of sub_table) if none.
        # Scoping is only possible when sub_table is the main table: with a
        # different sub_table the qualifier has to be a column of THAT table.
        scope_column = None
        scope_value = None

        if department_values:
            # department is a *name* (department.Department_Name) or a stored
            # Department_ID - never a "department" column on the row itself
            if sub_table == "department" and "department_name" in table_columns(sub_table):
                scope_column, scope_value = "department_name", f"'{department_values[-1][0]}'"
            elif "department_id" in table_columns(sub_table):
                scope_column = "department_id"
                scope_value = (
                    f"(SELECT department_id FROM department "
                    f"WHERE department_name = '{department_values[-1][0]}')"
                )
        elif city_values and "address" in table_columns(sub_table):
            scope_column, scope_value = "address", f"'{city_values[-1][0]}'"
        elif "semester" in tokens and "semester" in table_columns(sub_table):
            sem_idx = tokens.index("semester")
            for t in tokens[sem_idx:sem_idx + 3]:
                if t.isdigit():
                    scope_column, scope_value = "semester", t
                    break

        sub_where = f" WHERE {scope_column} = {scope_value}" if scope_column else ""

        any_all_where = (
            f" WHERE {condition_column} {op_symbol_map[value_condition]} {any_all_keyword} "
            f"(SELECT {sub_column} FROM {sub_table}{sub_where})"
        )

        return f"""
        SELECT {select_columns_sql}
        {from_sql}
        {any_all_where}
        """.strip()

    # ---------------- COUNT vs AVERAGE OF COUNTS ----------------

    if count_avg_cmp and group_by_column:

        # The inner query counts rows of the table that actually HOLDS the
        # grouping key - "more employees than the average per department"
        # counts employee_info rows, it does not count rows of the department
        # table (which has one row per department by construction, so every
        # group would come out as 1). It also has to group on a real column of
        # that table: the abstract keyword "department" has to become the
        # department_id foreign key, otherwise the inner query groups by an
        # identifier no table has and MySQL rejects the whole statement.
        counted_table = table
        if group_by_column == "department" and department_alias:
            counted_table = table
            inner_group_col = (
                "department_id" if "department_id" in table_columns(counted_table)
                else "department_name"
            )
        else:
            inner_group_col = group_by_column
            for _cand in (second_table, table):
                if _cand and group_by_column in table_columns(_cand):
                    counted_table = _cand
                    break

        inner_from = (
            f"{counted_table} LEFT JOIN department d "
            f"ON {counted_table}.department_id = d.department_id"
            if inner_group_col == "department_name"
            else counted_table
        )
        inner = f"SELECT COUNT(*) AS cnt FROM {inner_from} GROUP BY {inner_group_col}"

        return f"""
        SELECT {group_select_col}, COUNT(*)
        {from_sql}
        {group_by_clause}
        HAVING COUNT(*) {count_avg_cmp} (SELECT AVG(cnt) FROM ({inner}) AS avg_counts)
        """.strip()

    # ---------------- DISTINCT ----------------

    if aggregate_function == "DISTINCT":

        distinct_column = None
        _cols = table_columns(table)

        # Scan for the last column word that actually resolves on this table.
        # "show distinct exam names" ends in the abstract keyword "name", and
        # a blanket last-wins scan would land on it - the marks table has no
        # name column, so the real answer ("DISTINCT exam") got lost.
        for word in tokens:

            if word not in COLUMN_MAP:
                continue
            candidate = COLUMN_MAP[word]
            if candidate == "name":
                candidate = resolve_column("name", table)
            if candidate in _cols:
                distinct_column = candidate

        if distinct_column:

            return f"""
            SELECT DISTINCT {distinct_column}
            {from_sql}
            {where_clause}
            """.strip()

        # no real column to de-duplicate on - DISTINCT * is the honest answer
        return f"""
        SELECT DISTINCT *
        {from_sql}
        {where_clause}
        """.strip()

    # ---------------- AVG / SUM / MIN / MAX ----------------

    # "the highest marks obtained BY a student" asks for the aggregated VALUE
    # itself (MAX(marks)), not the top-ranked record - unlike "students who
    # OBTAINED the highest marks" (ORDER BY ... LIMIT 1). The tell is a
    # "by <a/an/the> <table-row>" phrase: the value is being reported per
    # row, so it should be collapsed with MAX/MIN.
    if record_condition in ("highest", "lowest") and aggregate_function is None \
       and not group_by_column and not limit_value:
        for i, word in enumerate(tokens):
            if word != "by":
                continue
            if i > 0 and tokens[i - 1] in ("ordered", "sorted", "arranged", "grouped", "group"):
                break
            j = i + 1
            while j < len(tokens) and tokens[j] in ("a", "an", "the", "each", "every", "any"):
                j += 1
            if j < len(tokens) and tokens[j] in TABLE_MAP:
                agg_fn = "MAX" if record_condition == "highest" else "MIN"
                agg_col = (
                    numeric_column
                    if numeric_column in table_columns(table)
                    else DEFAULT_NUMERIC_COLUMN.get(table, "student_id")
                )
                return f"""SELECT {agg_fn}({agg_col}) FROM {table}""".strip()

    if aggregate_function in ("AVG", "SUM", "MIN", "MAX"):

        # an aggregate can only wrap a real numeric column of this table
        if numeric_column not in table_columns(table):
            return f"""
            SELECT {select_columns_sql}
            {from_sql}
            {where_clause}{order_by_clause}{limit_clause}
            """.strip()

        select_cols = f"{aggregate_function}({numeric_column})"

        if group_by_column:
            select_cols = f"{group_select_col}, {select_cols}"

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

        # "the department with the highest average budget", "departments
        # ordered by average marks from highest to lowest" - when the
        # aggregate is grouped, ordering happens on the aggregate value
        # itself, not on the raw column. MySQL won't run "ORDER BY budget"
        # on a GROUP BY query, so sort by AVG(budget)/SUM(...)/etc instead.
        aggregate_order_clause = ""
        if group_by_column:
            if record_condition in ("highest", "lowest"):
                agg_sort_dir = "DESC" if record_condition == "highest" else "ASC"
                aggregate_order_clause = (
                    f" ORDER BY {aggregate_function}({numeric_column}) {agg_sort_dir}"
                )
                if not limit_value:
                    aggregate_order_clause += " LIMIT 1"
            elif order_requested and order_by_direction:
                aggregate_order_clause = (
                    f" ORDER BY {aggregate_function}({numeric_column}) {order_by_direction}"
                )

        return f"""
        SELECT {select_cols}
        {from_sql}
        {where_clause}{group_by_clause}{having_clause}{aggregate_order_clause}
        """.strip()

    # ---------------- COUNT ----------------

    if intent == "count":

        select_cols = "COUNT(*)"

        if group_by_column:
            select_cols = f"{group_select_col}, COUNT(*)"

        return f"""
        SELECT {select_cols}
        {from_sql}
        {where_clause}{group_by_clause}{having_clause}
        """.strip()

    # ---------------- HIGHEST ----------------

    if record_condition == "highest":

        # ranking needs a real numeric column; without one the request
        # degrades to a plain ordered listing instead of ORDER BY NULL
        if numeric_column not in table_columns(table):
            return f"""
            SELECT {select_columns_sql}
            {from_sql}
            {where_clause}{order_by_clause}{limit_clause}
            """.strip()

        limit_n = limit_value if limit_value else "1"
        offset_clause = f" OFFSET {rank_offset}" if rank_offset else ""

        return f"""
        SELECT {select_columns_sql}
        {from_sql}
        {where_clause}
        ORDER BY {numeric_column} DESC
        LIMIT {limit_n}{offset_clause}
        """.strip()

    # ---------------- LOWEST ----------------

    if record_condition == "lowest":

        if numeric_column not in table_columns(table):
            return f"""
            SELECT {select_columns_sql}
            {from_sql}
            {where_clause}{order_by_clause}{limit_clause}
            """.strip()

        limit_n = limit_value if limit_value else "1"
        offset_clause = f" OFFSET {rank_offset}" if rank_offset else ""

        return f"""
        SELECT {select_columns_sql}
        {from_sql}
        {where_clause}
        ORDER BY {numeric_column} ASC
        LIMIT {limit_n}{offset_clause}
        """.strip()

    # ---------------- DEFAULT SELECT ----------------

    return f"""
    SELECT {select_columns_sql}
    {from_sql}
    {where_clause}{order_by_clause}{limit_clause}
    """.strip()
#------------------------------(AI)--------------------------
def has_recognizable_keywords(question, tokens=None):
    """
    Lightweight confidence check, used by the /query route to decide
    whether to trust convert_to_sql()'s output or fall back to the AI
    layer instead.

    convert_to_sql() ALWAYS returns some SQL string (it falls through to
    a default SELECT * even when nothing meaningful was understood), so
    it can't signal low confidence on its own without changing its return
    contract. This function does the check separately, without touching
    convert_to_sql() or anything that depends on its existing behaviour.

    Returns True if the question contains at least one word this system
    actually knows how to interpret (a table, column, aggregate,
    condition, intent word, or a recognised category value like a
    department/city/gender). Returns False if NOTHING in the sentence
    was recognised - i.e. the rule-based engine likely produced a
    meaningless default query.

    If tokens are pre-computed and passed in, word_tokenize is skipped.
    """
    # Anything the engine had no rule for is left in the question and silently
    # discarded. The SQL it produced is kept so the gate below can tell a fully
    # understood question from one that only matched a stray keyword.
    global _last_converted_question, _LAST_CONVERTED
    if tokens is None:
        tokens = word_tokenize(question.lower())


    # Same live-schema sync as convert_to_sql() - a newly added table/column
    # must count as a recognisable keyword, otherwise its questions would be
    # routed to the AI fallback instead of the rule engine.
    refresh_schema_maps()
    refresh_column_values()

    # UNRESOLVED_ENTITY_TOKENS is filled in by convert_to_sql(). If this
    # question hasn't been through the converter in this process, run it
    # rather than reading another question's leftovers. convert_to_sql()
    # resets the set on entry, so this is always the right answer for
    # `question`.
    #
    # The SQL of that same conversion is captured here, because a question can
    # look recognised on its keywords while the query it produced quietly
    # ignored most of the sentence. The serial is what makes the pairing safe:
    # a caller that ran convert_to_sql() itself after the gate last cached a
    # result has to invalidate it.
    if (_LAST_CONVERTED[0] != question
            or _LAST_CONVERTED[1] != _conversion_serial):
        _LAST_CONVERTED = (question, _conversion_serial, convert_to_sql(question))
    _LAST_CONVERTED_SQL = _LAST_CONVERTED[2]


    # The question names a row that really exists ("ananya" -> 'Ananya
    # Singh' in student_info) but the row is not in the table the question
    # resolved to, so the engine's name filter could not apply it and would
    # otherwise emit a bare SELECT * and return everything. That is the
    # documented meaning of "unrecognised" - the output is a meaningless
    # default - so hand it to the AI layer, which can build the JOIN and now
    # has the real values to filter on.
    if UNRESOLVED_ENTITY_TOKENS:
        return False

    # The question is understood but needs an aggregate across tables this
    # engine builds one at a time. Answering it here would mean guessing.
    if ESCALATION_REASONS:
        return False

    # The question explicitly asks about a concept this schema does not
    # have ("top 5 salaries", "average age", "active employees"). The rule
    # engine cannot answer it, and anything it emits would be a confident,
    # silently wrong SELECT - so let the AI layer build the query instead
    # (it sees the same live schema and can decline gracefully).
    if any(word in UNSUPPORTED_CONCEPT_TOKENS for word in tokens):
        return False

    # Copulas / vague function words that appear in CONDITION_MAP ("is"
    # maps to "equal") but aren't enough on their own to say the rule-based
    # engine understood anything - "what is the weather like today" would
    # otherwise count as recognised just because it contains "is". A
    # question made up of ONLY such words must not pass this gate.
    WEAK_KEYWORDS = {"is", "equals", "equal", "were", "was"}

    # A recognised keyword is not the same as an understood question. When the
    # engine built a query with no filter at all and left a name-shaped word
    # unconsumed, it read part of the sentence and threw the rest away:
    # "show watson marks" matched on "marks" and answered with every mark row
    # in the table. A missing filter is a wrong answer delivered confidently,
    # so decline instead of letting the keyword below vouch for it.
    if _unexplained_name_tokens(tokens, _LAST_CONVERTED_SQL, question):
        return False

    keyword_sources = (
        TABLE_MAP, COLUMN_MAP, AGGREGATE_MAP, CONDITION_MAP, INTENT_MAP
    )


    for word in tokens:
        if word in WEAK_KEYWORDS:
            continue
        if any(word in source for source in keyword_sources):
            return True
        if word in DEPARTMENTS or word in CITIES or word in GENDERS:
            return True
        if word in SELECT_INTENT_WORDS or word in SORT_DIRECTION_MAP:
            return True

    return False


# Every word the engine's own vocabulary already accounts for. A token absent
# from here AND absent from the SQL it produced is a word nothing consumed.

# Requests that ask for a whole table without naming a row. They are ordinary
# questions, not sentences where a filter went missing.
_GENERIC_REQUEST_WORDS = {
    "everything", "everybody", "everyone", "anything", "anybody", "details",
    "detail", "info", "information", "data", "record", "records", "rows",
    "row", "table", "list", "summary", "overview", "please", "need", "want",
    "give", "tell", "let", "us", "whats", "whatss",
}


def _explained_vocabulary():
    # Vague requests name no row and filter nothing on purpose ("show me
    # everything"), so they are not the engine having dropped a name.
    words = set(NON_LITERAL_WORDS) | _GENERIC_REQUEST_WORDS
    words |= _NAME_STOP_WORDS | _MODIFIER_NOUNS | _VALUE_PREPOSITIONS
    for source in (
        TABLE_MAP, COLUMN_MAP, AGGREGATE_MAP, CONDITION_MAP, INTENT_MAP,
        SORT_DIRECTION_MAP, JOIN_TYPE_MAP, JOIN_TABLE_HINTS, JOIN_KEY_MAP,
        NUMBER_WORDS, SCALE_WORDS, ORDER_TRIGGER_WORDS,
        GROUPABLE_CATEGORICAL_COLUMNS,
        ORDINAL_MAP, ANY_ALL_TRIGGER_WORDS, DATE_TRIGGER_WORDS,
        STRONG_COMPARISON_WORDS, LIKE_FILLER_WORDS, SELECT_INTENT_WORDS,
    ):
        words |= {str(k) for k in source}
    # These maps are keyed by the words a person types ("emp", "dept"), so
    # the canonical values count as understood too.
    for source in (TABLE_MAP, COLUMN_MAP, CONDITION_MAP, INTENT_MAP,
                   JOIN_TABLE_HINTS):
        words |= {str(v).lower() for v in source.values()}
    words |= {str(v).lower() for v in list(DEPARTMENTS) + list(CITIES) + list(GENDERS)}
    return words


def _unexplained_name_tokens(tokens, sql, question=""):
    """
    The words that look like a row name and that nothing in the engine
    consumed. Only meaningful when the question produced a query with no
    filter at all: a WHERE means the engine clearly acted on what it read,
    and any leftover word is just chaff ("show the top 3 sales figures").

    Two tests have to pass together. The word must be absent from the engine's
    whole vocabulary, and it must have been written as a proper noun - a name
    mid-sentence is capitalised, while the connecting words that make up the
    rest of any sentence ("per", "with", "along") never are. The capitalisation
    test is what keeps this from flagging ordinary grammar, and the first word
    of a question is exempt because that position is capitalised regardless.

    A token counts as consumed if it, or a plural/possessive of it, appears
    anywhere in the generated SQL - which covers resolved values, multiword
    column phrases and anything rendered as a literal.
    """
    if not tokens or not sql or " WHERE " in f" {sql} ".upper():
        return []

    explained = _explained_vocabulary()
    haystack = f" {sql} ".lower()

    proper_nouns = set()
    for index, word in enumerate(re.findall(r"[A-Za-z]+", question)):
        if index == 0:
            # First word of the question: capitalised by convention, so it
            # proves nothing about being a name.
            continue
        if word[0].isupper():
            proper_nouns.add(word.lower())

    leftovers = []
    for word in tokens:
        if len(word) < 3 or not word.isalpha() or word in explained:
            continue
        if word not in proper_nouns:
            continue
        if any(form and form in haystack for form in (
            word, f"{word}s", f"{word}es", _strip_possessive(word),
        )):
            continue
        leftovers.append(word)

    leftovers.extend(_dropped_value_spans(tokens, haystack, explained))
    return leftovers


def _dropped_value_spans(tokens, haystack, explained):
    """
    Real stored values the question named that the generated SQL never used.

    The proper-noun test in _unexplained_name_tokens only fires on
    capitalised words, so a value typed in lower case slips straight past it.
    "students who took data structures" is written in lower case, the engine
    resolves nothing, and it answers with every student in the table - a
    confident, silently wrong result. Capitalisation is the wrong signal
    anyway: value grounding is case-insensitive, so the engine could have
    matched that value perfectly well, it just never checked whether it did.

    Being a real database value is the strong signal. 'Data Structures' is a
    row in subject.Subject_Name, so the user naming it is a constraint the
    query dropped - not a sentence-final noun and not grammar. Only reached
    when the query has no WHERE at all, so this can only ever fire on an
    unfiltered answer, which is precisely the case worth escalating.

    Values that are themselves part of the known vocabulary (a city, a
    department, a word like "hr" or "average") are left to the proper-noun
    test: substring-matching those against a SQL string is hopeless ("it" is
    inside most of them) and they are already covered.
    """
    dropped = []
    index = 0
    while index < len(tokens):
        value = _match_name_span(tokens, index)
        if value is None:
            index += 1
            continue

        # _match_name_span only returns on an exact word-for-word match, so
        # the span it consumed is exactly as long as the value.
        index += len(value.split())

        if value.lower() in explained or value.lower() in haystack:
            continue
        dropped.append(value)
    return dropped
