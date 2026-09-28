from services.hybrid_router import run_hybrid_query

cases = [
    "Show each project along with the name of its lead employee",
    "Display project names and the department of their lead employees",
    "Display the names of employees and the projects they lead",
    "Find projects led by employees from the IT department",
    "Show project names, employee names, and their salaries",
    "Show the project name, lead employee name, department, and salary for projects led by IT employees",
    "Show students and subjects together",
    "Show the names of employees who lead projects with a deadline after 2026-04-01",
    "Find employees who lead a project with a deadline after 2026-05-01",
    "Find employees with salary greater than the salary of Amit",
    "Display departments whose average salary is greater than the overall average salary",
    "Find employees who lead at least one project",
    "Find employees who do not lead any project",
    "Find students who are not taking any subject",
    "Find students whose marks are greater than ALL students taking Science",
    "Find students whose salary is greater than any student from Mysore",
    "Show employees and label their performance as Excellent if rating is greater than or equal to 4.5, otherwise Good",
    "Categorize employees as: High salary if salary > 70000 Medium salary if salary between 50000 and 70000 Low salary otherwise",
    "Label students and their CGPA as Excellent if cgpa above 8.5 else Average",
    "Show enrollments along with student names",
]

from collections import Counter
c = Counter()
for q in cases:
    r = run_hybrid_query(q, role="user")
    c[r["source"]] += 1
    err = r.get("error") or ""
    print(f'[{r["source"]:20s}] {q[:72]} rows={len(r["result"] or [])} err={err[:40]}')

print("SOURCES:", dict(c))