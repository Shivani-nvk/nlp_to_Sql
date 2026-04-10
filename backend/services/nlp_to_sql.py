#Shivani's part 
#precedence
import nltk
from nltk.tokenize import word_tokenize

# Run once:
# import nltk
# nltk.download('punkt')

# Intent mapping (action words)
INTENT_MAP = {
    "show": "select",
    "display": "select",
    "list": "select",
    "count": "count",
    "total": "count",

}

# Condition mapping
CONDITION_MAP = {
    "above": "above",
    "greater": "above",
    "below": "below",
    "less": "below",
    "highest": "highest",
    "top": "highest",
    "lowest": "lowest",
    "least": "lowest"
}

# Table mapping
TABLE_MAP = {
    "student": "students",
    "students": "students",
    "stu": "students",
    "employee": "employees",
    "emp": "employees",
    "employees": "employees",
    "staff": "employees"
}

# Column mapping
COLUMN_MAP = {
    "marks": "marks",
    "mark": "marks",
    "salary": "salary",
    "department": "department",
    "dept": "department",
    "name": "name"
}

# department values
DEPARTMENTS = ["it", "hr", "finance", "sales", "marketing"]


def convert_to_sql(question):
    question = question.lower()

    # Tokenization
    tokens = word_tokenize(question)

    table = "students"
    intent = "select"
    condition = None
    value = None
    column = None
    text_value = None
    name_value = None

    # NEW variables for insert
    student_id = None
    marks_value = None
    salary_value = None

# example :  "Show me employees with salary above 65000 in IT department"

    # Detect table
    for word in tokens:
        if word in TABLE_MAP:
            table = TABLE_MAP[word]

    # Detect intent
    for word in tokens:
        if word in INTENT_MAP:
            intent = INTENT_MAP[word]

    # Detect condition
    for word in tokens:
        if word in CONDITION_MAP:
            condition = CONDITION_MAP[word]

    # Detect column
    for word in tokens:
        if word in COLUMN_MAP:
            column = COLUMN_MAP[word]

    # Extract numeric value (for select queries)
    for word in tokens:
        if word.isdigit():
            value = word

    # Detect department text value
    for word in tokens:
        if word in DEPARTMENTS:
            text_value = word.upper()
            column = "department"

    # Default column
    if table == "students" and not column:
        column = "marks"

    if table == "employees" and not column:
        column = "salary"

    # ---------------- BUILD SQL ----------------

    # COUNT with conditions
    if intent == "count":

        if column and text_value:
            return f"SELECT COUNT(*) FROM {table} WHERE {column} = '{text_value}'"

        if condition == "above" and value:
            return f"SELECT COUNT(*) FROM {table} WHERE {column} > {value}"

        if condition == "below" and value:
            return f"SELECT COUNT(*) FROM {table} WHERE {column} < {value}"

        return f"SELECT COUNT(*) FROM {table}"

    # Highest
    if condition == "highest":
        return f"SELECT * FROM {table} ORDER BY {column} DESC LIMIT 1"

    # Lowest
    if condition == "lowest":
        return f"SELECT * FROM {table} ORDER BY {column} ASC LIMIT 1"

    # Text condition
    if column and text_value:
        return f"SELECT * FROM {table} WHERE {column} = '{text_value}'"

    # Above
    if condition == "above" and value:
        return f"SELECT * FROM {table} WHERE {column} > {value}"

    # Below
    if condition == "below" and value:
        return f"SELECT * FROM {table} WHERE {column} < {value}"

    # Default
    return f"SELECT * FROM {table}" 