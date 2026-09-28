"""
Hybrid NLP-to-SQL system tests, written against the LIVE schema of nlp_db.

    student_info(Student_ID, Student_Name, Course_ID, Address, Phone_No)
    course(Course_ID, Course_Name)
    department(Department_ID, Department_Name)
    employee_info(Employee_ID, Employee_Name, Department_ID, Address, Phone_No)
    project(Project_ID, Project_Name, Department_ID, Start_Year, Budget)
    performance(Employee_ID, Project_ID, Rating, Result)
    subject(Subject_ID, Subject_Name, Course_ID, Semester, Max_Marks)
    marks(Student_ID, Subject_ID, Exam, Marks, Result)

The rule-based engine is the PRIMARY path and is exercised end-to-end against
the real database through the hybrid router. The agentic/LLM tests are
"integration-shaped": they check that routing and the validation layer behave,
and report a graceful failure when no LLM key is configured rather than
crashing the suite.

Run: python test_hybrid.py
"""

import sys
import os

sys.path.insert(0, ".")

from services.nlp_to_sql import convert_to_sql, has_recognizable_keywords
from services.sql_validator import validate_sql
from services.hybrid_router import run_hybrid_query

PASS = 0
FAIL = 0
SKIP = 0
failures = []


def report(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        failures.append(name)
        print(f"[FAIL] {name} {detail}")


def check_rule(name, question, expected_patterns):
    """The rule engine must recognise the question and produce SQL containing
    the expected fragments."""
    try:
        sql = convert_to_sql(question)
        rec = has_recognizable_keywords(question)
        normalized = " ".join(sql.lower().split())
        missing = [p for p in expected_patterns if p.lower() not in normalized]
        report(name, rec and not missing, f"| sql: {sql} | missing: {missing}")
    except Exception as e:
        report(name, False, f"| crash: {e}")


def check_escalates(name, question):
    """A question the rule engine cannot answer honestly must be reported as
    unrecognised, so the router hands it to the agentic engine as PRIMARY
    rather than the rule engine inventing a column that does not exist."""
    try:
        rec = has_recognizable_keywords(question)
    except Exception as e:
        report(name, False, f"| crash: {e}")
        return
    report(f"{name} -> escalated", not rec, "" if not rec else f"| claimed support")


def check_valid(sql, should_pass, label):
    ok, reason = validate_sql(sql)
    report(f"validate {label}", ok == should_pass, f"| reason: {reason}")


# =========================================================================
# A. RULE-BASED ENGINE (PRIMARY)
# =========================================================================
print("\n=== A. RULE-BASED ENGINE ===")

# 1. Basic selects
check_rule("show all students", "Show all students", ["from student_info"])
check_rule("show all employees", "Show all employees", ["from employee_info"])
check_rule("show all projects", "List all projects", ["from project"])
check_rule("show all subjects", "Show all subjects", ["from subject"])
check_rule("show all courses", "Display all courses", ["from course"])
check_rule("show all departments", "Show all departments", ["from department"])

# 2. WHERE
check_rule("employees from IT", "Show employees from the IT department", ["it"])
check_rule("project budget > 1M", "Show projects with budget above 1000000", ["budget", ">", "1000000"])
check_rule("students marks > 80", "Show students with marks above 80", ["marks", ">", "80"])
check_rule("rating above 4", "Show performance records with rating above 4", ["rating", ">", "4"])
check_rule("start_year after 2020", "Show projects started after 2020", ["start_year", ">", "2020"])

# 3. Aggregates
check_rule("count students", "How many students are there", ["count(*)", "from student_info"])
check_rule("avg marks", "What is the average marks", ["avg(marks)"])
check_rule("sum budget", "What is the total budget of all projects", ["sum(budget)"])
check_rule("max rating", "What is the maximum rating", ["max(rating)"])

# 4. GROUP BY / HAVING
check_rule("count per course", "Count the number of students per course", ["group by", "course_id"])
check_rule("count per dept", "Count the number of employees in each department", ["group by", "department_name"])
check_rule("avg budget per dept", "Find the average budget for each department", ["avg(", "group by", "department"])
check_rule("avg marks per subject", "Show the average marks per subject", ["avg(marks)", "group by"])

# 5. ORDER BY / LIMIT
check_rule("order marks desc", "Show students ordered by marks from highest to lowest", ["order by", "marks", "desc"])
check_rule("top 5 marks", "Show the top 5 students by marks", ["order by", "desc", "limit 5"])
check_rule("lowest budgets", "Show the 3 projects with the lowest budget", ["order by", "asc", "3"])
check_rule("sort by name", "Show employees sorted by name", ["order by", "employee_name"])

# 6. NULL
check_rule("no address", "Find students who do not have an address", ["address", "is null"])
check_rule("has address", "Show students who have an address", ["address", "is not null"])
check_rule("no phone", "Show employees with a null phone number", ["phone_no", "is null"])

# 7. JOIN
check_rule("student + course", "Show student name and course name", ["from student_info", "join", "course"])
check_rule("subject + course", "Show course name and subject name", ["join", "subject"])
check_rule("student + marks", "Show student name along with their marks", ["from student_info", "join", "marks"])
check_rule("subject + marks", "Show subject name along with their marks", ["from subject", "join", "marks"])
check_rule("employee + department", "Show employee name and department name", ["join", "department"])
check_rule("project + department", "Show project name and department name", ["join", "department"])

# 8. Categorical values (exact strings stored in the DB)
check_rule("internal exam", "Show marks for the Internal exam", ["exam = 'internal'"])
check_rule("midterm exam", "Show marks for the Midterm exam", ["exam = 'midterm'"])
check_rule("pass result", "Show students with a pass result", ["pass"])
check_rule("excellent performance", "Show performance records with an excellent result", ["excellent"])
check_rule("bangalore address", "Show students from Bangalore", ["bangalore"])

# 9. Subqueries
check_rule("marks > avg", "Find students whose marks are higher than the average marks", ["(select avg(marks)"])
check_rule("budget < avg", "Show projects with budget less than the average budget", ["(select avg(budget)"])

# 10. Word numbers
check_rule("marks above eighty", "Show students with marks above eighty", ["80"])
check_rule("budget above one million", "Show projects with budget above one million", ["1000000"])

# 11. UNION
check_rule("union students subjects", "Show students and subjects together", ["union"])

# =========================================================================
# B. ESCALATION - the rule engine must REFUSE these, not invent SQL
# =========================================================================
print("\n=== B. ESCALATION (no such column / needs a join chain) ===")

check_escalates("salary", "Show employees with salary above 50000")
check_escalates("age", "Show employees older than 30")
check_escalates("gender", "Show female employees")
check_escalates("email", "Show employee email addresses")
check_escalates("experience", "Show employees with more than 5 years of experience")
check_escalates("manager", "Show employees and their managers")
check_escalates("deadline", "Show projects with deadline after 2026-01-01")
check_escalates("cgpa", "Show students with CGPA above 8")
check_escalates("active status", "Show active employees")
check_escalates("dept count vs avg count", "Find departments that have more employees than the average number of employees per department")
check_escalates("marks max in any subject", "Show students with marks equal to the maximum marks in any subject")
check_escalates("any/all scoped", "Find students whose marks are greater than all students taking Mathematics")

# =========================================================================
# C. HYBRID ROUTER - rule-based queries through the real pipeline
# =========================================================================
print("\n=== C. HYBRID ROUTER (rule-based path) ===")


def check_router(name, question, expected_sources=None):
    try:
        result = run_hybrid_query(question, role="user")
    except Exception as e:
        report(name, False, f"| crash: {e}")
        return None

    valid_sources = {"rule_based", "agentic", "agentic_self_healed", "failed"}
    ok = result["source"] in valid_sources
    report(f"{name} [source={result['source']}]", ok, f"| result keys: {sorted(result)}")

    if expected_sources:
        ok2 = result["source"] in expected_sources
        report(f"{name} source in {expected_sources}", ok2, f"| got {result['source']}")

    if result["source"] != "failed":
        report(f"{name} has sql", bool(result.get("sql")), "")
    else:
        report(f"{name} failed-clean-error", bool(result.get("error")), "")
    return result


check_router("router show all students", "Show all students", ["rule_based"])
check_router("router count employees", "How many employees are there", ["rule_based"])
check_router("router avg budget per dept", "Find the average budget for each department", ["rule_based"])
check_router("router join", "Show student name and course name", ["rule_based"])
check_router("router categorical", "Show students from Bangalore", ["rule_based"])

# =========================================================================
# D. AGENTIC PATH (integration-shaped: routing + graceful failure)
# =========================================================================
print("\n=== D. AGENTIC PATH ===")

# A question the rule engine cannot recognise must not be answered by the rule
# engine's default; the router should route to the agentic layer (which either
# succeeds or fails gracefully depending on whether an LLM key is configured).
result = run_hybrid_query("what is the weather like today", role="user")
ok_shape = (
    result["source"] in ("agentic", "agentic_self_healed", "failed")
    and "trace" in result
)
report(
    "router routes unknown question away from rule-based",
    ok_shape,
    f"| got source={result['source']}",
)

# A question with no such column should reach the agentic path too.
result = run_hybrid_query("Show employees with salary above 50000", role="user")
ok_shape = result["source"] in ("agentic", "agentic_self_healed", "failed")
report(
    "router routes unsupported concept to agentic",
    ok_shape,
    f"| got source={result['source']}",
)

# =========================================================================
# E. VALIDATION LAYER (unit tests - no DB needed)
# =========================================================================
print("\n=== E. SQL VALIDATION ===")

check_valid("SELECT * FROM student_info", True, "read-only select")
check_valid("SELECT student_name, phone_no FROM student_info WHERE address = 'Bangalore'", True, "select with where")
check_valid("SELECT AVG(marks) FROM marks", True, "aggregate select")
check_valid("SELECT * FROM marks ORDER BY marks DESC LIMIT 5", True, "full select")

check_valid("DROP TABLE student_info", False, "DROP blocked")
check_valid("DELETE FROM student_info", False, "DELETE blocked")
check_valid("INSERT INTO student_info VALUES (1)", False, "INSERT blocked")
check_valid("UPDATE student_info SET student_name='x'", False, "UPDATE blocked")
check_valid("ALTER TABLE student_info ADD COLUMN x INT", False, "ALTER blocked")
check_valid("SELECT * FROM app_users", False, "app_users blocked")
check_valid("SELECT * FROM student_info; DROP TABLE student_info", False, "statement separator blocked")
check_valid("SELECT * FROM student_info /* comment */", False, "comment blocked")
check_valid("", False, "empty rejected")
check_valid("SELECT * FROM information_schema.tables", False, "only SELECT prefix enforced")

# =========================================================================
# SUMMARY
# =========================================================================
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped")
if failures:
    print("\nFailed tests:")
    for f in failures:
        print(f"  - {f}")
print("=" * 60)

sys.exit(1 if FAIL else 0)
