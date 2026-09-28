"""
Multi-table join planning tests, written against the LIVE schema of nlp_db.

This covers the part of the engine that had to grow a real join planner.
nlp_to_sql.py used to build at most one JOIN, which is why these questions
either lost a column or were handed to the LLM:

  * "show employees with their department names" has no join trigger word at
    all - a possessive alone means a join - and department_name was dropped.
  * "show project names along with the employees rating them" names three
    tables and the bridge between the two ends is a fourth concept
    (performance) that no pair of the mentioned tables shares a key with.
  * "show students along with their course and their marks" joined two tables
    and then projected only the driving table's columns.
  * "show student names along with employee names" invented
    ON student_info.id = employee_info.id, on a column neither table has.

Every prompt here is executed against the real database, so a test passes only
if the SQL is shaped as expected AND runnable. Questions that the rules
genuinely cannot express must be ESCALATED rather than answered with a guess -
the last group asserts exactly that.

Run: python test_join_planner.py
"""

import sys
import re

sys.path.insert(0, ".")

from db import get_db_connection
from services.nlp_to_sql import convert_to_sql, has_recognizable_keywords

# A subquery that projects a column from a table other than the one it selects
# FROM is a correlated reference to the enclosing query. When the engine
# qualifies the subquery against the outer join chain it produces
#   employee_info.department_id = (SELECT employee_info.department_id FROM department ...)
# which compares each row's own department_id with itself: true for every row,
# so "employees in the finance department" reports all ten employees. The SQL
# is well formed and executes, so a pattern test cannot see it - the filter has
# to be checked for the correlation itself.
CORRELATED_SUBQUERY_RE = re.compile(
    r"\(\s*select\s+([a-z_]\w*)\.([a-z_]\w*)\s+from\s+([a-z_]\w*)"
)


def correlated_reason(sql):
    """A reason string if `sql` filters through a self-satisfying subquery."""
    flat = " ".join(str(sql).lower().split())
    for outer, column, inner in CORRELATED_SUBQUERY_RE.findall(flat):
        if outer != inner:
            return (
                f"correlated subquery: selects {outer}.{column} "
                f"while FROM {inner} (filter is always true)"
            )
    return None

# (name, prompt, expected substrings in the SQL)
SUPPORTED = [
    # ============ 1. POSSESSIVE ALONE IS A JOIN ============
    ("dept via possessive", "Show employees with their department names",
     ["join department", "department_name"]),
    ("marks via possessive", "Show students along with their marks",
     ["join marks", "student_id = student_info.Student_ID"]),
    ("subjects via possessive", "Show subjects along with course names",
     ["join course"]),

    # ============ 2. THREE TABLES IN ONE QUESTION ============
    # project and employee_info share NO key. The relationship lives on
    # performance, so the only honest route is through it.
    ("project via performance", "Show project names along with the employees rating them",
     ["join performance", "join employee_info"]),
    ("employee side of bridge", "Show employee names, project names and ratings",
     ["join performance", "join project"]),
    # "employees and their projects" is the same bridge asked for without the
    # word "performance" anywhere in the sentence.
    ("implicit bridge", "List employees and their projects",
     ["join performance"]),

    # ============ 3. PROJECTION MUST REACH EVERY TABLE ============
    ("projection across chain", "Show students along with their course and their marks",
     ["join course", "join marks"]),
    ("four table chain",
     "List the course name, subject name and marks of every student",
     ["join subject", "join marks", "join student_info", "course_name", "subject_name"]),

    # ============ 4. EXPLICIT JOIN TYPES ============
    ("left join preserved", "Show all students with a left join to their marks",
     ["left join marks"]),
    ("cross join preserved", "Cross join students and subjects",
     ["cross join", "student_info", "subject"]),

    # ============ 5. AGGREGATES MUST NOT INFLATE ============
    # One student has many mark rows, so COUNT(*) over that join counts rows,
    # not students.
    ("count distinct through fanout", "How many students have marks",
     ["count(distinct student_info.student_id)", "join marks"]),
    ("grouped count", "Show the number of students per course",
     ["count(distinct student_info.student_id)", "group by"]),

    # ============ 6. FILTERS MUST LAND ON THE RIGHT COLUMN ============
    # "scored above 80" is about marks. The nearest numeric column to the
    # comparison word is student_id, which is nonsense as a filter.
    ("measure not key", "Show students who scored above 80 along with their subject names",
     ["marks.marks > 80"]),
    ("literal threshold kept", "Show projects with budget above 1000000 along with their department names",
     ["project.budget > 1000000"]),
    # "the department it belongs to" - "it" is a pronoun, not the department
    # named IT. Reading it as a value silently restricted the whole answer to
    # the IT department.
    ("pronoun is not a value",
     "Show the project name, the department it belongs to and the employees working on it",
     ["join department", "join employee_info"]),
    # ...but when IT is really the name of the department, it is a value.
    ("modifier is a value", "Show employees from the IT department",
     ["'IT'"]),
    # The subquery is rendered as "= (SELECT ...)" - one whitespace token
    # "(SELECT" - so a qualifier that looks for a bare "(" never sees the
    # opening bracket, rewrites the subquery against the outer join chain and
    # turns this filter into a tautology that matches every employee.
    ("subquery keeps its own columns",
     "show names of employees who are from the finance department",
     ["'Finance'", "department_id = (select department_id from department"]),

    # ============ 7. ORDERING AND LIMITS SURVIVE THE JOIN ============
    ("order by joined column", "Show students along with their marks ordered by marks descending",
     ["order by", "marks.marks desc"]),
    ("limit preserved", "Show projects along with their department names sorted by budget descending limit 5",
     ["order by", "budget desc", "limit 5"]),
    ("top n through join", "Show the top 3 students by marks along with their course name",
     ["order by", "desc", "limit 3"]),

    # ============ 8. A BARE TABLE NAME RESOLVES TO ITS NAME COLUMN ============
    # "its course" means the course, not course_id.
    ("table word means name column", "Show every subject and its course",
     ["course.course_name"]),

    # ============ 5. A NAME IS A FILTER, NOT A WORD TO THROW AWAY ============
    # "show ananyas marks" used to answer with every mark row in the table.
    # The possessive was not stripped, so the word matched no stored value;
    # it was then dropped as unknown, and "marks" alone was confident enough
    # to suppress the fallback. Ananya's marks are one row, not eighteen.
    ("possessive name filter", "Show Ananya's marks",
     ["join student_info", "student_name = 'ananya'"]),
    ("possessive without apostrophe", "Show Ananyas marks",
     ["join student_info", "student_name = 'ananya'"]),
    # A name on another table still has to reach it, and both column names in
    # the projection have to be qualified now that two tables are in play.
    ("name filter projection", "Show marks of the student named Ananya",
     ["join student_info", "student_name = 'ananya'", "marks.marks"]),
    ("name filter with a second column", "Show Ananya's marks and exam",
     ["join student_info", "student_name = 'ananya'", "exam"]),
    ("name filter with a comparison", "Show Ananya's marks above 80",
     ["join student_info", "student_name = 'ananya'", "marks > 80"]),
    # The same sentence on the corporate side resolves the same way, which
    # shows the name is looked up in the schema rather than hardcoded.
    ("employee name filter", "Show Amit's ratings",
     ["join employee_info", "employee_name = 'amit'"]),
]

# The schema has no key between the academic half and the corporate half, so a
# question spanning both cannot be answered by a join at all. Fabricating one
# (ON a.id = b.id on columns that do not exist) produces a query that fails at
# runtime, and a query that "works" by sharing a category answers a different
# question. These must be escalated.
UNSUPPORTED = [
    ("students and employees", "Show student names along with employee names"),
    ("marks and projects", "Show marks along with project names"),
    # "Watson" is a plausible name but not a row in this database, and the
    # sentence contains no other word to filter on. Answering with every mark
    # row would be complete, runnable and not the question that was asked.
    ("unknown name", "Show Watson's marks"),
    # A person who does exist, in the half of the schema that cannot be joined
    # to marks. No honest query exists, so it has to go to the AI layer.
    ("employee name on marks", "Show marks of Amit"),
]


def check_supported(name, prompt, patterns, conn):
    try:
        sql = convert_to_sql(prompt)
    except Exception as e:
        print(f"[FAIL] {name} -> generation crashed: {e}")
        return False

    reasons = []

    if not has_recognizable_keywords(prompt):
        reasons.append("NOT RECOGNIZED (should have been supported)")

    normalized = " ".join(sql.lower().split())
    for pattern in patterns or []:
        if pattern.lower() not in normalized:
            reasons.append(f"missing '{pattern}'")

    correlated = correlated_reason(sql)
    if correlated:
        reasons.append(correlated)

    if "id = id" in normalized or "app_users" in normalized:
        reasons.append("invented a relationship")

    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql)
        cur.fetchall()
    except Exception as e:
        reasons.append(f"SQL ERROR: {str(e).splitlines()[0][:120]}")
    finally:
        cur.close()

    if reasons:
        print(f"[FAIL] {name}: {'; '.join(reasons)}")
        print(f"    prompt: {prompt}")
        print(f"    sql:    {' '.join(sql.split())}")
        return False

    print(f"[PASS] {name}")
    return True


def check_escalated(name, prompt):
    try:
        recognized = has_recognizable_keywords(prompt)
        sql = convert_to_sql(prompt)
    except Exception as e:
        print(f"[FAIL] {name} -> crashed: {e}")
        return False

    if recognized:
        print(f"[FAIL] {name} -> claimed a join that does not exist")
        print(f"    prompt: {prompt}")
        print(f"    sql:    {' '.join(sql.split())}")
        return False

    normalized = " ".join(sql.lower().split())
    if "id = id" in normalized:
        print(f"[FAIL] {name} -> invented ON a.id = b.id")
        return False

    correlated = correlated_reason(sql)
    if correlated:
        print(f"[FAIL] {name} -> {correlated}")
        return False

    print(f"[PASS] {name} -> escalated (agentic)")
    return True


def main():
    conn = get_db_connection()
    passed = 0
    total = 0
    failed = []

    try:
        for name, prompt, patterns in SUPPORTED:
            total += 1
            if check_supported(name, prompt, patterns, conn):
                passed += 1
            else:
                failed.append(name)

        for name, prompt in UNSUPPORTED:
            total += 1
            if check_escalated(name, prompt):
                passed += 1
            else:
                failed.append(name)
    finally:
        conn.close()

    print("=" * 60)
    print(f"RESULTS: {passed}/{total}")
    if failed:
        print("FAILED:")
        for f in failed:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
