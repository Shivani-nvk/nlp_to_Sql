"""
Every question this schema can be asked, checked against the LIVE database.

The other suites check the SHAPE of the SQL (does it join, does it group, does
it decline). This one checks the ANSWER: for each prompt it runs the SQL the
rule engine produced and a hand-written reference query, and compares the two
result sets. A query can have the right shape and still be answering a
different question, and that is the failure that matters:

  * "show projects in department 2" filtered on project_id - the shape was a
    perfect "WHERE <int column> = <int>", and the number meant a department.
  * "show good results" read 'Good' out of performance while querying marks,
    where that value does not exist, so it returned nothing and looked right.
  * "show students in course 1" joined the course table and then projected
    course_name, answering with a list of courses rather than students.
  * "show the average marks per subject" grouped by subject_id, so every
    average was labelled with a number instead of the subject's name.

Rows are compared order-insensitively, so a query is free to sort however it
likes. Prompts listed in ESCALATE must NOT be answered by the rules at all.

Run: python test_schema_coverage.py
"""

import sys

sys.path.insert(0, ".")

from db import get_db_connection
from services.nlp_to_sql import convert_to_sql, has_recognizable_keywords

# (label, prompt, reference SQL)
SUPPORTED = [
    # ---------------- student_info ----------------
    ("students all", "Show all students", "SELECT * FROM student_info"),
    ("student cols", "Show student id, student name and address",
     "SELECT Student_ID, Student_Name, Address FROM student_info"),
    ("students in city", "Show students from Bangalore",
     "SELECT * FROM student_info WHERE Address = 'Bangalore'"),
    ("count students", "Count the number of students",
     "SELECT COUNT(*) FROM student_info"),
    ("students by city", "Show the number of students in each city",
     "SELECT Address, COUNT(*) FROM student_info GROUP BY Address"),
    # "course 1" is a filter, and student_info already holds course_id. Joining
    # the course table to satisfy it answered with a list of course names.
    ("students in course", "Show students in course 1",
     "SELECT * FROM student_info WHERE Course_ID = 1"),
    ("one student", "Show Ananya's address and phone number",
     "SELECT Address, Phone_No FROM student_info WHERE Student_Name = 'Ananya'"),

    # ---------------- course ----------------
    ("courses", "Show all courses", "SELECT * FROM course"),
    ("count courses", "Count courses", "SELECT COUNT(*) FROM course"),
    ("course names", "Show course names", "SELECT Course_Name FROM course"),

    # ---------------- subject ----------------
    ("subjects all", "Show all subjects", "SELECT * FROM subject"),
    ("subject cols", "Show subject name, semester and max marks",
     "SELECT Subject_Name, Semester, Max_Marks FROM subject"),
    ("count subjects", "Count subjects", "SELECT COUNT(*) FROM subject"),
    ("subjects in course", "Show subjects in course 1",
     "SELECT * FROM subject WHERE Course_ID = 1"),
    ("subjects in semester", "Show subjects in semester 3",
     "SELECT * FROM subject WHERE Semester = 3"),
    ("subjects per semester", "Show the number of subjects per semester",
     "SELECT Semester, COUNT(*) FROM subject GROUP BY Semester"),

    # ---------------- marks ----------------
    ("marks all", "Show all marks", "SELECT * FROM marks"),
    ("marks above", "Show marks above 80",
     "SELECT * FROM marks WHERE Marks > 80"),
    ("marks below", "Show marks below 50",
     "SELECT * FROM marks WHERE Marks < 50"),
    ("exam filter", "Show final exam marks",
     "SELECT Exam, Marks FROM marks WHERE Exam = 'Final'"),
    ("result filter", "Show failed results",
     "SELECT * FROM marks WHERE Result = 'Fail'"),
    ("count marks", "Count marks", "SELECT COUNT(*) FROM marks"),
    ("avg marks", "Find the average marks", "SELECT AVG(Marks) FROM marks"),
    ("max marks row", "Show the highest marks",
     "SELECT * FROM marks ORDER BY Marks DESC LIMIT 1"),
    ("top 3 marks", "Show the top 3 marks by marks",
     "SELECT Marks FROM marks ORDER BY Marks DESC LIMIT 3"),
    ("count passed", "Count the number of passed results",
     "SELECT COUNT(*) FROM marks WHERE Result = 'Pass'"),
    ("marks for student id", "Show marks for student 3",
     "SELECT * FROM marks WHERE Student_ID = 3"),

    # ---------------- employee_info ----------------
    ("employees all", "Show all employees", "SELECT * FROM employee_info"),
    ("employee cols", "Show employee name and address",
     "SELECT Employee_Name, Address FROM employee_info"),
    ("employee in city", "Show employees from Bangalore",
     "SELECT * FROM employee_info WHERE Address = 'Bangalore'"),
    ("count employees", "Count the number of employees",
     "SELECT COUNT(*) FROM employee_info"),
    ("employees sorted", "Show employees sorted by name",
     "SELECT * FROM employee_info ORDER BY Employee_Name"),

    # ---------------- department ----------------
    ("departments", "Show all departments", "SELECT * FROM department"),
    ("count departments", "Count departments", "SELECT COUNT(*) FROM department"),
    ("dept names", "Show department names",
     "SELECT Department_Name FROM department"),
    ("employees per dept name", "Show the number of employees per department name",
     "SELECT department.Department_Name, COUNT(DISTINCT employee_info.Employee_ID) "
     "FROM employee_info JOIN department "
     "ON employee_info.Department_ID = department.Department_ID "
     "GROUP BY department.Department_Name"),
    ("employees in IT", "Show employees in IT",
     "SELECT * FROM employee_info WHERE Department_ID = "
     "(SELECT Department_ID FROM department WHERE Department_Name = 'IT')"),

    # ---------------- project ----------------
    ("projects all", "Show all projects", "SELECT * FROM project"),
    ("project cols", "Show project name, start year and budget",
     "SELECT Project_Name, Start_Year, Budget FROM project"),
    ("count projects", "Count projects", "SELECT COUNT(*) FROM project"),
    ("projects in year", "Show projects started in 2026",
     "SELECT * FROM project WHERE Start_Year = 2026"),
    ("budget above", "Show projects with budget above 100000",
     "SELECT * FROM project WHERE Budget > 100000"),
    # "department 2" is the department a project belongs to, not the project's
    # own key. The bare number had no column and fell back to project_id.
    ("projects in department", "Show projects in department 2",
     "SELECT * FROM project WHERE Department_ID = 2"),
    ("project name filter", "Show the budget of Budget Forecast",
     "SELECT Budget FROM project WHERE Project_Name = 'Budget Forecast'"),
    ("avg budget", "Find the average budget of all projects",
     "SELECT AVG(Budget) FROM project"),
    ("top project", "Show the project with the highest budget",
     "SELECT * FROM project ORDER BY Budget DESC LIMIT 1"),
    ("top 5 projects", "Show the top 5 projects by budget",
     "SELECT Budget FROM project ORDER BY Budget DESC LIMIT 5"),
    ("projects per dept", "Show the number of projects per department",
     "SELECT department.Department_Name, COUNT(project.Project_ID) "
     "FROM department JOIN project ON project.Department_ID = department.Department_ID "
     "GROUP BY department.Department_Name"),

    # ---------------- performance ----------------
    ("performance all", "Show all performance records",
     "SELECT * FROM performance"),
    ("ratings above", "Show ratings above 4.2",
     "SELECT * FROM performance WHERE Rating > 4.2"),
    ("count performance", "Count performance records",
     "SELECT COUNT(*) FROM performance"),
    ("avg rating", "Find the average rating", "SELECT AVG(Rating) FROM performance"),
    ("top rated", "Show the highest rating",
     "SELECT * FROM performance ORDER BY Rating DESC LIMIT 1"),
    ("lowest rating", "Show the lowest rating",
     "SELECT * FROM performance ORDER BY Rating ASC LIMIT 1"),
    # "Good" only exists in performance.result. `result` is a column of marks
    # too, so the guess used to land on marks and match nothing.
    ("good results", "Show good results",
     "SELECT Result FROM performance WHERE Result = 'Good'"),
    ("excellent results", "Show excellent results",
     "SELECT Result FROM performance WHERE Result = 'Excellent'"),
    # ...while "Pass" only exists in marks.result, so this one must stay there.
    ("pass results", "Show pass results",
     "SELECT * FROM marks WHERE Result = 'Pass'"),

    # ---------------- two-table joins ----------------
    ("student + course", "Show student name and course name",
     "SELECT student_info.Student_Name, course.Course_Name FROM student_info "
     "JOIN course ON student_info.Course_ID = course.Course_ID"),
    ("student + marks", "Show student name along with their marks",
     "SELECT student_info.Student_Name, marks.Marks FROM student_info "
     "JOIN marks ON student_info.Student_ID = marks.Student_ID"),
    ("subject + course", "Show course name and subject name",
     "SELECT course.Course_Name, subject.Subject_Name FROM subject "
     "JOIN course ON subject.Course_ID = course.Course_ID"),
    ("subject + marks", "Show subject name along with their marks",
     "SELECT subject.Subject_Name, marks.Marks FROM subject "
     "JOIN marks ON subject.Subject_ID = marks.Subject_ID"),
    ("employee + dept", "Show employee name and department name",
     "SELECT employee_info.Employee_Name, department.Department_Name "
     "FROM employee_info JOIN department "
     "ON employee_info.Department_ID = department.Department_ID"),
    ("project + dept", "Show project name and department name",
     "SELECT project.Project_Name, department.Department_Name FROM project "
     "JOIN department ON project.Department_ID = department.Department_ID"),
    ("employee + performance", "Show employee name and rating",
     "SELECT employee_info.Employee_Name, performance.Rating FROM performance "
     "JOIN employee_info ON performance.Employee_ID = employee_info.Employee_ID"),
    ("project + performance", "Show project name and rating",
     "SELECT project.Project_Name, performance.Rating FROM performance "
     "JOIN project ON performance.Project_ID = project.Project_ID"),

    # ---------------- three/four-table chains ----------------
    ("student + course + marks", "Show student name, course name and marks",
     "SELECT student_info.Student_Name, course.Course_Name, marks.Marks "
     "FROM student_info JOIN course ON student_info.Course_ID = course.Course_ID "
     "JOIN marks ON student_info.Student_ID = marks.Student_ID"),
    ("subject + course + marks", "Show course name, subject name and marks",
     "SELECT course.Course_Name, subject.Subject_Name, marks.Marks "
     "FROM subject JOIN course ON subject.Course_ID = course.Course_ID "
     "JOIN marks ON subject.Subject_ID = marks.Subject_ID"),
    # A star through department: every employee against every project of their
    # own department. That is what the sentence says, and it is a real join on
    # real keys - just not the same answer as "projects they worked on".
    ("employee + dept + project", "Show employee name, department name and project name",
     "SELECT employee_info.Employee_Name, department.Department_Name, project.Project_Name "
     "FROM employee_info JOIN department "
     "ON employee_info.Department_ID = department.Department_ID "
     "JOIN project ON project.Department_ID = department.Department_ID"),
    # The employees have to be IN the output, not just joined: the question
    # asked who did the rating, and a project with a number says nothing.
    ("project via performance", "Show project names along with the employees rating them",
     "SELECT project.Project_Name, performance.Rating, employee_info.Employee_Name "
     "FROM performance JOIN project ON performance.Project_ID = project.Project_ID "
     "JOIN employee_info ON performance.Employee_ID = employee_info.Employee_ID"),

    # ---------------- aggregation across tables ----------------
    # Grouped by the NAME, not the key: "per course" reported 1, 2, 3 before.
    ("students per course", "Show the number of students per course",
     "SELECT course.Course_Name, COUNT(DISTINCT student_info.Student_ID) "
     "FROM course JOIN student_info ON student_info.Course_ID = course.Course_ID "
     "GROUP BY course.Course_Name"),
    ("avg marks per subject", "Show the average marks per subject",
     "SELECT subject.Subject_Name, AVG(marks.Marks) FROM subject "
     "JOIN marks ON subject.Subject_ID = marks.Subject_ID "
     "GROUP BY subject.Subject_Name"),
    ("avg budget per dept", "Show the average budget per department",
     "SELECT department.Department_Name, AVG(project.Budget) FROM project "
     "JOIN department ON project.Department_ID = department.Department_ID "
     "GROUP BY department.Department_Name"),
    # Asking for the key on its own still groups by the key.
    ("students per course id", "Show the number of students per course id",
     "SELECT Course_ID, COUNT(*) FROM student_info GROUP BY Course_ID"),

    # ---------------- a name is a filter ----------------
    ("ananya marks", "Show Ananya's marks",
     "SELECT marks.Marks FROM marks JOIN student_info "
     "ON marks.Student_ID = student_info.Student_ID "
     "WHERE student_info.Student_Name = 'Ananya'"),
    ("ananyas marks", "Show Ananyas marks",
     "SELECT marks.Marks FROM marks JOIN student_info "
     "ON marks.Student_ID = student_info.Student_ID "
     "WHERE student_info.Student_Name = 'Ananya'"),
    ("ananya marks and exam", "Show Ananya's marks and exam",
     "SELECT marks.Marks, marks.Exam FROM marks JOIN student_info "
     "ON marks.Student_ID = student_info.Student_ID "
     "WHERE student_info.Student_Name = 'Ananya'"),
    ("ananya marks above", "Show Ananya's marks above 80",
     "SELECT marks.Marks FROM marks JOIN student_info "
     "ON marks.Student_ID = student_info.Student_ID "
     "WHERE student_info.Student_Name = 'Ananya' AND marks.Marks > 80"),
    ("amit ratings", "Show Amit's ratings",
     "SELECT performance.* FROM performance JOIN employee_info "
     "ON performance.Employee_ID = employee_info.Employee_ID "
     "WHERE employee_info.Employee_Name = 'Amit'"),
    ("amit department", "Show Amit's department",
     "SELECT department.* FROM department JOIN employee_info "
     "ON employee_info.Department_ID = department.Department_ID "
     "WHERE employee_info.Employee_Name = 'Amit'"),
]

# No honest rule-based answer exists for these. Answering anyway means
# returning a complete, runnable, wrong result set.
ESCALATE = [
    ("unknown name", "Show Watson's marks"),
    ("employee name on marks", "Show marks of Amit"),
    ("students and employees", "Show student names along with employee names"),
    ("marks and projects", "Show marks along with project names"),
    ("salary", "Show the top 5 employees by salary"),
]


def norm(rows):
    """Order-insensitive comparison that treats NULL and '' as the same thing."""
    return sorted(
        [tuple("" if v is None else str(v) for v in row) for row in rows]
    )


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    passed = 0
    total = 0
    failures = []

    for label, prompt, reference in SUPPORTED:
        total += 1
        problems = []
        try:
            recognized = has_recognizable_keywords(prompt)
            sql = convert_to_sql(prompt)
        except Exception as exc:
            failures.append((label, prompt, f"crashed: {exc}", ""))
            continue

        if not recognized:
            problems.append("escalated, but this schema CAN answer it")
        else:
            normalized = " ".join(sql.lower().split())
            if "id = id" in normalized or "app_users" in normalized:
                problems.append("invented a relationship")
            try:
                cur.execute(sql)
                got = cur.fetchall()
            except Exception as exc:
                problems.append(f"SQL ERROR: {str(exc).splitlines()[0][:110]}")
                got = None

            if got is not None:
                cur.execute(reference)
                want = cur.fetchall()
                if norm(got) != norm(want):
                    problems.append(
                        f"WRONG ANSWER: {len(got)} row(s), reference has {len(want)}"
                    )

        if problems:
            failures.append((label, prompt, "; ".join(problems),
                             " ".join(sql.split())))
        else:
            passed += 1
            print(f"[PASS] {label}")

    for label, prompt in ESCALATE:
        total += 1
        try:
            recognized = has_recognizable_keywords(prompt)
            sql = convert_to_sql(prompt)
        except Exception as exc:
            failures.append((label, prompt, f"crashed: {exc}", ""))
            continue
        if recognized:
            failures.append((label, prompt, "answered with a guess",
                             " ".join(sql.split())))
        else:
            passed += 1
            print(f"[PASS] {label} -> escalated (agentic)")

    print("=" * 60)
    for label, prompt, why, sql in failures:
        print(f"[FAIL] {label}: {why}")
        print(f"    prompt: {prompt}")
        print(f"    sql:    {sql}")
    print("=" * 60)
    print(f"RESULTS: {passed}/{total}")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
