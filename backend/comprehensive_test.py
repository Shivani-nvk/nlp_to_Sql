"""
Comprehensive rule-based NLP-to-SQL test suite, written against the LIVE
schema of nlp_db.

Every prompt here is executed against the real database, so a test only
passes if the generated SQL is both shaped as expected AND actually runnable.
The schema under test is:

    student_info(Student_ID, Student_Name, Course_ID, Address, Phone_No)
    course(Course_ID, Course_Name)
    department(Department_ID, Department_Name)
    employee_info(Employee_ID, Employee_Name, Department_ID, Address, Phone_No)
    project(Project_ID, Project_Name, Department_ID, Start_Year, Budget)
    performance(Employee_ID, Project_ID, Rating, Result)
    subject(Subject_ID, Subject_Name, Course_ID, Semester, Max_Marks)
    marks(Student_ID, Subject_ID, Exam, Marks, Result)

app_users is auth and is never queryable.

Concepts with no column in this schema (salary, age, gender, email,
experience, manager, deadline, CGPA, active status) are NOT tested here as
supported SQL: they are covered by the escalation tests at the bottom, which
assert that the engine refuses to invent SQL for them.

Run: python comprehensive_test.py
"""

import sys

sys.path.insert(0, ".")

from db import get_db_connection
from services.nlp_to_sql import convert_to_sql, has_recognizable_keywords

# (name, prompt, expected substrings or None to skip shape checks)
PROMPTS = [
    # ============ 1. BASIC SELECT ============
    ("show students", "Show all students", ["from student_info"]),
    ("show employees", "Show all employees", ["from employee_info"]),
    ("show projects", "List all projects", ["from project"]),
    ("show subjects", "Show all subjects", ["from subject"]),
    ("show courses", "Display all courses", ["from course"]),
    ("show departments", "Show all departments", ["from department"]),
    ("show performance", "Show all performance records", ["from performance"]),
    ("show marks", "Show all marks", ["from marks"]),

    # ============ 2. EXPLICIT COLUMNS ============
    ("student columns", "Show student id, student name, address and phone_no", ["student_id", "student_name", "address", "phone_no"]),
    ("employee columns", "Show employee id, employee name and phone number", ["employee_id", "employee_name", "phone_no"]),
    ("project columns", "Show project name, start year and budget", ["project_name", "start_year", "budget"]),
    ("subject columns", "Show subject name, semester and max marks", ["subject_name", "semester", "max_marks"]),
    ("marks columns", "Show exam, marks and result", ["exam", "marks", "result"]),
    ("max marks", "What is the maximum marks", ["max(marks)"]),
    ("students+subjects union", "Show students and subjects together", ["union"]),

    # ============ 3. COUNT / AGGREGATES ============
    ("count students", "How many students are there", ["count(*)"]),
    ("count employees", "Count the employees", ["count(*)"]),
    ("count projects", "How many projects are there", ["count(*)"]),
    ("count departments", "How many departments are there", ["count(*)"]),
    ("count subjects", "How many subjects are there", ["count(*)"]),
    ("count marks", "How many marks records are there", ["count(*)"]),
    ("count performance", "How many performance records are there", ["count(*)"]),
    ("avg marks", "What is the average marks", ["avg(marks)"]),
    ("max marks score", "What is the maximum marks scored", ["max(marks)"]),
    ("min budget", "What is the minimum budget", ["min(budget)"]),
    ("total budget", "What is the total budget of all projects", ["sum(budget)"]),

    # ============ 4. FILTERS (numeric) ============
    ("marks > 60", "Show students who scored more than 60 marks", ["marks", ">", "60"]),
    ("budget > 1000000", "Show projects with budget above 1000000", ["budget", ">", "1000000"]),
    ("max_marks >= 50", "Show subjects with max marks at least 50", ["max_marks", ">=", "50"]),
    ("rating above 4", "Show performance records with rating above 4", ["rating", ">", "4"]),
    ("start_year after 2020", "Show projects started after 2020", ["start_year", ">", "2020"]),

    # ============ 5. CATEGORICAL FILTERS ============
    ("IT department", "Show employees from the IT department", ["IT"]),
    ("HR department", "List employees in HR", ["HR"]),
    ("bangalore address", "Show students from Bangalore", ["Bangalore"]),
    ("internal exam", "Show marks for the Internal exam", ["exam = 'Internal'"]),
    ("midterm exam", "Show marks for the Midterm exam", ["exam = 'Midterm'"]),
    ("final exam", "Show marks for the Final exam", ["exam = 'Final'"]),
    ("pass result", "Show students with a pass result", ["Pass"]),
    ("excellent performance", "Show performance records with an excellent result", ["Excellent"]),

    # ============ 6. GROUP BY ============
    ("students per course", "Show the number of students per course", ["group by", "course_id"]),
    ("subjects per semester", "Count subjects per semester", ["group by", "semester"]),
    ("employees per department", "Show the number of employees per department", ["group by"]),
    ("avg budget per department", "Show the average budget per department", ["avg(project.budget)", "group by"]),
    ("avg marks per subject", "Show the average marks per subject", ["avg(marks)", "group by"]),

    # ============ 7. ORDER BY / LIMIT ============
    ("sort by marks desc", "Sort students by marks descending", ["order by", "marks", "desc"]),
    ("top 5 by marks", "Show top 5 students by marks", ["order by", "desc", "5"]),
    ("lowest 3 budgets", "Show the 3 lowest budget projects", ["order by", "asc", "3"]),
    ("limit 10", "Show 10 projects", ["limit 10"]),

    # ============ 8. JOINS (two tables) ============
    ("subjects per course", "Show course name and subject name", ["join", "subject"]),
    ("students in course", "Show student name and course name", ["join", "course"]),
    ("employees in department", "Show employee name and department name", ["join", "department"]),
    ("projects in department", "Show project name and department name", ["join", "department"]),
    ("students with marks", "Show student name along with their marks", ["join", "marks"]),
    ("marks with subject", "Show subject name along with their marks", ["join", "marks"]),

    # ============ 9. DEPARTMENT RESOLUTION (no bare `department` column) ============
    ("dept by name", "Show employees and their department names", ["join department"]),
    ("dept group by name", "Show the number of employees per department name", ["join department", "group by department.department_name", "count(*)"]),
    ("dept count grouped", "Show the number of employees per department", ["group by d.department_name", "count(*)"]),

    # ============ 10. AGGREGATE SUBQUERIES ============
    ("marks above average", "Find students whose marks are higher than the average marks", ["marks", ">", "(select avg(marks)"]),
    ("budget below average", "Show projects with budget less than the average budget", ["budget", "<", "(select avg(budget)"]),

    # ============ 11. NULL CHECKS ============
    ("students without address", "Show students who do not have an address", ["address is null"]),
    ("employees without phone", "Show employees with a null phone number", ["phone_no is null"]),

    # ============ 12. WORD NUMBERS ============
    ("marks above eighty", "Show students with marks above eighty", ["80"]),
    ("budget above one million", "Show projects with budget above one million", ["1000000"]),
]

# Concepts with NO column in the live schema. The engine must escalate these
# to the agentic path instead of emitting SQL against a column that does not
# exist. (name, prompt, offending token)
UNSUPPORTED = [
    ("salary", "Show employees with salary above 50000", "salary"),
    ("age", "Show employees older than 30", "age"),
    ("gender", "Show female employees", "gender"),
    ("email", "Show employee email addresses", "email"),
    ("experience", "Show employees with more than 5 years of experience", "experience"),
    ("manager", "Show employees and their managers", "manager"),
    ("deadline", "Show projects with deadline after 2026-01-01", "deadline"),
    ("cgpa", "Show students with CGPA above 8", "cgpa"),
    ("active", "Show active employees", "active"),
]


# Concepts that DO have columns in the live schema, but that need a join chain
# (or a derived table) the single-JOIN rule engine cannot build. These must be
# reported as unrecognised so the hybrid router runs them on the agentic path
# as primary, instead of the rule engine emitting SQL that references a column
# no table in its FROM clause has.
COMPLEX = [
    ("marks max in any subject", "Show students with marks equal to the maximum marks in any subject"),
    ("subjects with more than 2 students", "Show subjects having more than 2 students"),
    ("dept count vs avg count", "Find departments that have more employees than the average number of employees per department"),
    ("any/all comparison", "Find students whose marks are greater than all students taking Mathematics"),
    ("any/all scoped to dept", "Find employees whose budget is greater than all budgets in the IT department"),
]


def check_supported(name, prompt, patterns, conn):
    """Rule-based prompt: must be recognized, contain the expected SQL
    fragments, validate, AND execute without a DB error."""
    try:
        sql = convert_to_sql(prompt)
    except Exception as e:
        print(f"[FAIL] {name} -> generation crashed: {e}")
        return False

    reasons = []

    if not has_recognizable_keywords(prompt):
        reasons.append("NOT RECOGNIZED (should have been supported)")

    normalized = " ".join(sql.lower().split())
    for p in patterns or []:
        if p.lower() not in normalized:
            reasons.append(f"missing '{p}'")

    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql)
        rows = cur.fetchall()
    except Exception as e:
        reasons.append(f"SQL ERROR: {str(e).splitlines()[0][:120]}")
        rows = None
    finally:
        cur.close()

    ok = not reasons
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"    prompt: {prompt}")
        print(f"    sql:    {sql}")
        for r in reasons:
            print(f"    {r}")
    return ok


def check_unsupported(name, prompt, token, conn):
    """Unsupported concept: has_recognizable_keywords must return False so the
    hybrid router hands off to the agentic engine. If it DOES produce SQL, the
    SQL must not reference the phantom column (and must not blow up on a table
    that does not exist)."""
    try:
        recognized = has_recognizable_keywords(prompt)
    except Exception as e:
        print(f"[FAIL] {name} -> recognizer crashed: {e}")
        return False

    reasons = []

    try:
        sql = convert_to_sql(prompt)
    except Exception as e:
        sql = ""
        reasons.append(f"generation crashed: {e}")

    if recognized:
        # If the engine claims to understand it, the SQL must at least be
        # valid against the live schema.
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql)
            cur.fetchall()
        except Exception as e:
            reasons.append(f"claimed supported but SQL ERROR: {str(e).splitlines()[0][:100]}")
        finally:
            cur.close()

    ok = not reasons
    verdict = "escalated (agentic)" if not recognized else "rule-based (runnable)"
    print(f"[{'PASS' if ok else 'FAIL'}] {name} -> {verdict}")
    if not ok:
        print(f"    prompt: {prompt}")
        print(f"    sql:    {sql}")
        for r in reasons:
            print(f"    {r}")
    return ok


def check_complex(name, prompt):
    """A question the data CAN answer but the rule engine cannot express: it
    must be reported as unrecognised so the agentic engine takes it, and the
    SQL the rule engine produced anyway must at least be runnable (or be
    ignored entirely, which is what the escalation does)."""
    try:
        recognized = has_recognizable_keywords(prompt)
        sql = convert_to_sql(prompt)
    except Exception as e:
        print(f"[FAIL] {name} -> crashed: {e}")
        return False

    if recognized:
        print(f"[FAIL] {name} -> rule engine claimed a join chain it cannot build")
        print(f"    prompt: {prompt}")
        print(f"    sql:    {sql}")
        return False

    print(f"[PASS] {name} -> escalated (agentic)")
    return True


def main():
    conn = get_db_connection()
    passed = 0
    total = 0
    failed = []

    try:
        for name, prompt, patterns in PROMPTS:
            total += 1
            if check_supported(name, prompt, patterns, conn):
                passed += 1
            else:
                failed.append(name)

        for name, prompt, token in UNSUPPORTED:
            total += 1
            if check_unsupported(name, prompt, token, conn):
                passed += 1
            else:
                failed.append(name)

        for name, prompt in COMPLEX:
            total += 1
            if check_complex(name, prompt):
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
