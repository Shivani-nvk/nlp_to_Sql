"""
Query refiner tests: takes the SQL the rule-based engine produced, applies a
follow-up refinement through the same path routes/refine.py uses
(parse_query -> apply_feedback -> rebuild_sql), then re-validates the result
against the live schema and actually runs it.

Run: python test_refiner.py
"""

import sys

sys.path.insert(0, ".")

from db import get_db_connection
from services.nlp_to_sql import convert_to_sql
from services.query_refiner import (
    RefinementError,
    apply_feedback,
    build_department_id_condition,
    parse_query,
    rebuild_sql,
    resolve_column,
    table_columns,
)
from services.sql_validator import validate_sql, execute_sql_safe
from routes.refine import _is_safe_select

PASS = 0
FAIL = 0
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


conn = get_db_connection()


def check_refine(name, question, feedback, expected_patterns, expect_dept_subquery=False):
    """question -> SQL -> refine -> assert fragments, safety, and DB run."""
    try:
        base_sql = convert_to_sql(question)
        ctx = parse_query(base_sql)
        ctx, changes = apply_feedback(ctx, feedback)
        refined = rebuild_sql(ctx)
    except RefinementError as e:
        report(name, False, f"| RefinementError: {e}")
        return
    except Exception as e:
        report(name, False, f"| crash: {type(e).__name__}: {e}")
        return

    normalized = " ".join(refined.lower().split())
    missing = [p for p in expected_patterns if p.lower() not in normalized]

    ok_valid, reason = validate_sql(refined)
    result, err = execute_sql_safe(conn, refined)
    runs = err is None

    detail = f"| refined: {refined} | missing: {missing}"
    if not ok_valid:
        detail += f" | validator rejected: {reason}"
    if not runs:
        detail += f" | db error: {str(err).splitlines()[0][:100]}"
    if expect_dept_subquery and "department_id = (select" not in normalized:
        detail += " | expected department subquery"

    report(name, not missing and ok_valid and runs, detail)


def check_refuse(name, question, feedback, must_mention=()):
    """The refiner must decline rather than answer a different question."""
    try:
        ctx = parse_query(convert_to_sql(question))
        ctx, _ = apply_feedback(ctx, feedback)
        refined = rebuild_sql(ctx)
    except RefinementError:
        report(f"{name} -> declined", True, "")
        return
    except Exception as e:
        report(f"{name} -> declined", False, f"| crash {type(e).__name__}: {e}")
        return
    normalized = " ".join(refined.lower().split())
    ok_valid, _ = validate_sql(refined)
    _, err = execute_sql_safe(conn, refined)
    report(
        f"{name} -> declined",
        False,
        f"| silently produced: {refined} | valid={ok_valid} | db_error={str(err).splitlines()[0][:80] if err else None}",
    )


print("\n=== A. COLUMN RESTRICTION ===")
check_refine("only employee name", "Show all employees", "only show employee name", ["employee_name"])
check_refine("only student name and address", "Show all students", "only show name and address", ["student_name", "address"])
check_refine("only project and year", "Show all projects", "only show project name and start year", ["project_name", "start_year"])
check_refine("only marks and exam", "Show all marks", "only show exam and marks", ["exam", "marks"])
check_refine("only subject name and max marks", "Show all subjects", "only show subject name and max marks", ["subject_name", "max_marks"])

print("\n=== B. REMOVE / SWAP ===")
check_refine("remove budget", "Show all projects", "remove budget", ["project_name"])
check_refine("remove phone", "Show all employees", "remove phone number", ["employee_name"])
check_refine("swap department for address", "Show all employees", "swap department for address", ["address"])

print("\n=== C. CATEGORICAL FILTERS (schema-grounded values) ===")
check_refine("filter to IT", "Show all employees", "only show IT", ["it"])
check_refine("filter to HR", "Show all employees", "only show HR", ["hr"])
check_refine("filter bangalore", "Show all students", "only show Bangalore", ["bangalore"])
check_refine("filter mysore", "Show all students", "only show Mysore", ["mysore"])
check_refine("filter internal exam", "Show all marks", "only show Internal exam", ["internal"])
check_refine("filter pass result", "Show all marks", "only show Pass", ["pass"])
check_refine("filter excellent", "Show all performance", "only show Excellent", ["excellent"])

print("\n=== D. DEPARTMENT SUBQUERY (department_name lives on `department`) ===")
check_refine("dept filter becomes subquery", "Show all employees", "only show IT", ["department_id = (select"], expect_dept_subquery=True)
check_refine("dept filter on projects", "Show all projects", "only show Finance", ["department_id = (select"], expect_dept_subquery=True)
check_refine("multiple departments", "Show all employees", "only show IT and HR", ["department_id in (select", "it", "hr"])

print("\n=== E. SORT ===")
check_refine("dept name sort declined", "Show all employees", "sort by phone number ascending", ["order by", "phone_no", "asc"])
check_refine("sort asc", "Show all employees", "sort by employee name ascending", ["order by", "asc"])
check_refine("sort desc", "Show all projects", "sort by budget descending", ["order by", "budget", "desc"])
check_refine("abstract name sort on students", "Show all students", "sort by name", ["order by", "student_name"])
check_refine("abstract name sort on subjects", "Show all subjects", "sort by name", ["order by", "subject_name"])
check_refine("swap phone for address", "Show all employees", "swap phone number for address", ["address"])

# these name an attribute the table cannot sort by without a JOIN, so the
# refiner has to decline rather than quietly order by some other column
check_refuse("sort by department name declined", "Show all employees", "sort by department name")
check_refuse("sort students by marks declined", "Show all students", "sort by marks descending")
check_refuse("sort marks by subject declined", "Show all marks", "sort by subject name")

print("\n=== F. LIMIT / NUMBERS ===")
check_refine("top 5", "Show all projects", "show top 5", ["limit 5"])
check_refine("limit ten", "Show all students", "limit ten", ["limit 10"])

print("\n=== G. UNIT CHECKS ===")

# resolve_column: only "name" is abstract, everything else passes through, and
# a column belonging to a different table is not silently borrowed
report("resolve_column marks/marks", resolve_column("marks", "marks") == "marks", f"| got {resolve_column('marks','marks')}")
report("resolve_column name/student_info", resolve_column("name", "student_info") == "student_name", f"| got {resolve_column('name','student_info')}")
report("resolve_column name/employee_info", resolve_column("name", "employee_info") == "employee_name", f"| got {resolve_column('name','employee_info')}")
report("resolve_column name/subject", resolve_column("name", "subject") == "subject_name", f"| got {resolve_column('name','subject')}")
report("resolve_column name/course", resolve_column("name", "course") == "course_name", f"| got {resolve_column('name','course')}")
report("resolve_column name/department", resolve_column("name", "department") == "department_name", f"| got {resolve_column('name','department')}")

# live columns for the tables the chatbot is allowed to touch
for table, expected in {
    "employee_info": {"employee_id", "employee_name", "department_id", "address", "phone_no"},
    "student_info": {"student_id", "student_name", "course_id", "address", "phone_no"},
    "project": {"project_id", "project_name", "department_id", "start_year", "budget"},
    "subject": {"subject_id", "subject_name", "course_id", "semester", "max_marks"},
    "marks": {"student_id", "subject_id", "exam", "marks", "result"},
    "performance": {"employee_id", "project_id", "rating", "result"},
}.items():
    cols = table_columns(table)
    report(f"table_columns {table}", expected <= cols, f"| missing {sorted(expected - cols)}")

report("table_columns bogus table empty", table_columns("no_such_table") == set(), f"| got {table_columns('no_such_table')}")

# department subquery builder: names are looked up, ids never hard-coded
c = " ".join(build_department_id_condition([("IT", False)], False).lower().split())
report("dept condition single", c == "department_id = (select department_id from department where department_name = 'it')", f"| got {c}")

c = " ".join(build_department_id_condition([("IT", False), ("HR", False)], True).lower().split())
report("dept condition IN list", c.startswith("department_id in (select department_id from department") and "'it'" in c and "'hr'" in c, f"| got {c}")

c = " ".join(build_department_id_condition([("IT", True)], False).lower().split())
report("dept condition negated", c.startswith("department_id not in (select"), f"| got {c}")
report("dept condition empty input", build_department_id_condition([], False) is None, "")

# a refinement naming a column the table doesn't have must not invent it
try:
    ctx = parse_query(convert_to_sql("Show all employees"))
    ctx, _ = apply_feedback(ctx, "only show salary")
    refined = rebuild_sql(ctx)
    report("unknown column not invented", "salary" not in refined.lower(), f"| got {refined}")
except RefinementError:
    report("unknown column not invented", True, "")
except Exception as e:
    report("unknown column not invented", False, f"| crash {type(e).__name__}: {e}")

# cross-table column in a refinement must not leak into a single-table query
try:
    ctx = parse_query(convert_to_sql("Show all students"))
    ctx, _ = apply_feedback(ctx, "only show budget")
    refined = rebuild_sql(ctx)
    report("cross-table column not borrowed", "budget" not in refined.lower(), f"| got {refined}")
except RefinementError:
    report("cross-table column not borrowed", True, "")
except Exception as e:
    report("cross-table column not borrowed", False, f"| crash {type(e).__name__}: {e}")

# the route's execution guard rejects what the refiner must never emit
report("safe guard blocks app_users", not _is_safe_select("SELECT * FROM app_users"), "")
report("safe guard blocks stacked stmt", not _is_safe_select("SELECT * FROM student_info; DROP TABLE student_info"), "")
report("safe guard blocks union", not _is_safe_select("SELECT * FROM student_info UNION SELECT * FROM course"), "")
report("safe guard blocks non-select", not _is_safe_select("DELETE FROM student_info"), "")
report("safe guard allows plain select", _is_safe_select("SELECT * FROM student_info WHERE address = 'Bangalore'"), "")
report("safe guard allows subquery select", _is_safe_select("SELECT * FROM marks WHERE marks > (SELECT AVG(marks) FROM marks)"), "")

# parse_query only accepts something it can faithfully rebuild
for bad, label in [
    ("DELETE FROM employee_info", "delete"),
    ("SHOW TABLES", "show"),
    ("SELECT * FROM student_info; DROP TABLE student_info", "stacked"),
    ("this is not sql", "not sql"),
    ("", "empty"),
]:
    try:
        parse_query(bad)
        report(f"parse rejects {label}", False, "| parsed unexpectedly")
    except RefinementError:
        report(f"parse rejects {label}", True, "")
    except Exception as e:
        report(f"parse rejects {label}", False, f"| wrong error {type(e).__name__}: {e}")

# =========================================================================
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed")
if failures:
    print("\nFailed tests:")
    for f in failures:
        print(f"  - {f}")
print("=" * 60)

conn.close()
sys.exit(1 if FAIL else 0)
