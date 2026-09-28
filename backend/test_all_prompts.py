"""Test all NLP-to-SQL prompts for correctness."""

import sys
sys.path.insert(0, ".")

from services.nlp_to_sql import convert_to_sql, has_recognizable_keywords

def normalize(s):
    return " ".join(s.lower().split())

def check(name, question, expected_sql_patterns, not_expected_patterns=None):
    """Check if generated SQL matches expected patterns (case-insensitive substrings)."""
    sql = convert_to_sql(question)
    recognized = has_recognizable_keywords(question)
    sql_norm = normalize(sql)
    
    passed = True
    failures = []
    
    for pat in expected_sql_patterns:
        if pat.lower() not in sql_norm:
            passed = False
            failures.append(f"  MISSING: '{pat}'")
    
    if not_expected_patterns:
        for pat in not_expected_patterns:
            if pat.lower() in sql_norm:
                passed = False
                failures.append(f"  UNWANTED: '{pat}'")
    
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}")
    if not passed:
        print(f"  Prompt: {question}")
        print(f"  SQL: {sql}")
        for f in failures:
            print(f)
    return passed

total = 0
passed_count = 0
failed_tests = []
ALL_TEST_CASES = []

def run(tests):
    global total, passed_count
    for name, question, expected, not_expected in tests:
        total += 1
        ALL_TEST_CASES.append((name, question, expected, not_expected))
        if __name__ != "__main__":
            continue
        ok = check(name, question, expected, not_expected)
        if ok:
            passed_count += 1
        else:
            failed_tests.append(name)

# ==================== 1. Basic SELECT ====================
run([
    ("Show all employees",
     "Show all employees",
     ["select", "*", "from employees"], []),
    
    ("Show all students",
     "Show all students",
     ["select", "*", "from students"], []),
    
    ("Display names and salaries of all employees",
     "Display the names and salaries of all employees",
     ["select", "name", "salary", "from employees"], []),
    
    ("Show name, age, gender, city of all students",
     "Show the name, age, gender, and city of all students",
     ["select", "name", "age", "gender", "city", "from students"], []),
    
    ("List all employees in IT",
     "List all employees who work in the IT department",
     ["select", "*", "from employees", "department", "it"], []),
    
    ("Show all students studying Computer Science",
     "Show all students studying Computer Science",
     ["select", "*", "from students", "computer science"], []),
    
    ("Display all projects and their deadlines",
     "Display all projects and their deadlines",
     ["select", "*", "from projects"], []),
    
    ("Show names and credits of all subjects",
     "Show the names and credits of all subjects",
     ["select", "credits", "from subjects"], []),
])

# ==================== 2. WHERE conditions ====================
run([
    ("Employees salary > 60000",
     "Find employees whose salary is greater than 60000",
     ["select", "from employees", "salary", ">", "60000"], []),
    
    ("Students marks > 80",
     "Find students who scored more than 80 marks",
     ["select", "from students", "marks", ">", "80"], []),
    
    ("Employees from Bangalore",
     "Show employees who are from Bangalore",
     ["select", "from employees", "bangalore"], []),
    
    ("Female employees in HR",
     "Find female employees who work in HR",
     ["select", "from employees", "female", "hr"], []),
    
    ("Students CGPA > 8",
     "Show students whose CGPA is greater than 8",
     ["select", "from students", "cgpa", ">", "8"], []),
    
    ("Employees experience > 5",
     "Find employees with more than 5 years of experience",
     ["select", "from employees", "experience", ">", "5"], []),
    
    ("Projects deadline after April 1 2026",
     "Show projects with deadlines after April 1, 2026",
     ["select", "from projects", "deadline"], []),
])

# ==================== 3. AND / OR / NOT ====================
run([
    ("IT and salary > 60000",
     "Find employees who work in IT and have a salary above 60000",
     ["select", "from employees", "it", "salary", ">", "60000"], []),
    
    ("Female and CGPA > 8",
     "Find students who are female and have a CGPA above 8",
     ["select", "from students", "female", "cgpa", ">", "8"], []),
    
    ("HR or Finance",
     "Show employees who work in HR or Finance",
     ["select", "from employees", "hr", "finance"], []),
    
    ("Bangalore or Mysore students",
     "Find students who are from Bangalore or Mysore",
     ["select", "from students", "bangalore", "mysore"], []),
    
    ("Not from Bangalore",
     "Show employees who are not from Bangalore",
     ["select", "from employees", "city", "!=", "'bangalore'"], []),
])

# ==================== 4. ORDER BY ====================
run([
    ("Employees ordered by salary desc",
     "Show employees ordered by salary from highest to lowest",
     ["select", "from employees", "order by", "salary", "desc"], []),
    
    ("Students ordered by CGPA desc",
     "List students ordered by CGPA from highest to lowest",
     ["select", "from students", "order by", "cgpa", "desc"], []),
    
    ("Employees ordered by experience asc",
     "Show employees ordered by experience in ascending order",
     ["select", "from employees", "order by", "experience", "asc"], []),
    
    ("Students ordered by marks desc",
     "Display students ordered by marks from highest to lowest",
     ["select", "from students", "order by", "marks", "desc"], []),
])

# ==================== 5. Aggregate functions ====================
run([
    ("Average salary",
     "What is the average salary of all employees",
     ["select", "avg(salary)", "from employees"], []),
    
    ("Highest salary",
     "What is the highest salary among employees",
     ["select", "from employees", "salary", "desc"], []),
    
    ("Lowest CGPA",
     "What is the lowest CGPA among students",
     ["select", "from students", "cgpa", "asc"], []),
    
    ("Count employees",
     "How many employees are there",
     ["select", "count(*)", "from employees"], []),
    
    ("Count students from Bangalore",
     "How many students are from Bangalore",
     ["select", "count(*)", "from students", "bangalore"], []),
    
    ("Average CGPA of female students",
     "What is the average CGPA of female students",
     ["select", "avg(cgpa)", "from students", "female"], []),
    
    ("Total scholarship amount",
     "What is the total scholarship amount given to students",
     ["select", "sum(scholarship_amount)", "from students"], []),
])

# ==================== 6. GROUP BY ====================
run([
    ("Count employees per department",
     "Count the number of employees in each department",
     ["select", "department", "count(*)", "from employees", "group by", "department"], []),
    
    ("Average salary per department",
     "Find the average salary for each department",
     ["select", "department", "avg(salary)", "from employees", "group by", "department"], []),
    
    ("Average CGPA per city",
     "Find the average CGPA for each city",
     ["select", "city", "avg(cgpa)", "from students", "group by", "city"], []),
    
    ("Count students per subject",
     "Count the number of students in each subject",
     ["select", "count(*)", "from students"], []),
    
    ("Highest salary per department",
     "Find the highest salary in each department",
     ["select", "department", "from employees"], []),
])

# ==================== 7. HAVING ====================
run([
    ("Departments with > 3 employees",
     "Show departments having more than 3 employees",
     ["select", "department", "count(*)", "from employees", "group by", "department", "having"], []),
    
    ("Departments avg salary > 60000",
     "Show departments where the average salary is greater than 60000",
     ["select", "department", "from employees", "group by", "department", "having"], []),
    
    ("Cities with > 3 students",
     "Show cities having more than 3 students",
     ["select", "city", "count(*)", "from students", "group by", "city", "having"], []),
    
    ("Subjects with > 1 student",
     "Show subjects having more than one student",
     ["select", "count(*)", "from students", "group by", "having"], []),
])

# ==================== 8. NULL testing ====================
run([
    ("Employees without manager",
     "Find employees who do not have a manager",
     ["select", "from employees", "manager_id", "is null"], []),
    
    ("Employees with manager",
     "Show employees who have a manager",
     ["select", "from employees", "manager_id", "is not null"], []),
    
    ("Students without email",
     "Find students who do not have an email address",
     ["select", "from students", "email", "is null"], []),
    
    ("Students with guardian",
     "Show students who have a guardian",
     ["select", "from students", "guardian_id", "is not null"], []),
    
    ("Employees manager_id is NULL",
     "Find employees whose manager ID is NULL",
     ["select", "from employees", "manager_id", "is null"], []),
])

# ==================== 9. LIKE / pattern matching ====================
run([
    ("Names starting with A",
     "Find employees whose names start with A",
     ["select", "from employees", "name", "like", "a%"], []),
    
    ("Students names starting with S",
     "Find students whose names start with S",
     ["select", "from students", "name", "like", "s%"], []),
    
    ("Employee email contains company",
     "Show employees whose email contains the word company",
     ["select", "from employees", "email", "like", "%company%"], []),
    
    ("Students city starts with B",
     "Find students whose city starts with B",
     ["select", "from students", "city", "like", "b%"], []),
    
    ("Employee department contains I",
     "Find employees whose department contains the letter I",
     ["select", "from employees", "department", "like"], []),
])

# ==================== 10. JOIN ====================
run([
    ("Student name with subject",
     "Show each student's name along with their subject",
     ["select", "from students", "join"], []),
    
    ("Students with subjects",
     "Display student names and the subjects they are taking",
     ["select", "from students", "join"], []),
    
    ("Subject with student name",
     "Show each subject and the name of the student who took it",
     ["select", "from subjects", "join"], []),
    
    ("Project with lead employee name",
     "Show project names along with the names of their lead employees",
     ["select", "from projects", "join"], []),
    
    ("Employee names with projects",
     "Display employee names and the projects they are leading",
     ["select", "from employees", "join"], []),
    
    ("Students with scholarship and subject",
     "Show students along with their scholarship amounts and subject names",
     ["select", "from students", "join"], []),
])

# ==================== 11. EXISTS ====================
run([
    ("Employees leading projects",
     "Find employees who are leading at least one project",
     ["select", "from employees", "exists", "projects"], []),
    
    ("Students with subjects",
     "Find students who have a subject assigned to them",
     ["select", "from students", "exists"], []),
    
    ("Employees with project",
     "Show employees for whom a project exists",
     ["select", "from employees", "exists", "projects"], []),
    
    ("Students with subject record",
     "Find students for whom a subject record exists",
     ["select", "from students", "exists"], []),
])

# ==================== 12. IN ====================
run([
    ("Employees in HR IT or Finance",
     "Find employees who work in HR, IT, or Finance",
     ["select", "from employees", "hr", "it", "finance"], []),
    
    ("Students from Bangalore or Mysore",
     "Find students who are from Bangalore or Mysore",
     ["select", "from students", "bangalore", "mysore"], []),
    
    ("Employees in HR Sales or Marketing",
     "Show employees whose department is in HR, Sales, or Marketing",
     ["select", "from employees", "hr", "sales", "marketing"], []),
])

# ==================== 13. ANY / ALL ====================
run([
    ("Salary > any HR employee",
     "Find employees whose salary is greater than any employee in the HR department",
     ["select", "from employees", "salary", ">", "any", "employees", "hr"], []),
    
    ("Salary > all HR employees",
     "Find employees whose salary is greater than all employees in the HR department",
     ["select", "from employees", "salary", ">", "all", "employees", "hr"], []),
    
    ("CGPA > any Mysore student",
     "Find students whose CGPA is greater than any student from Mysore",
     ["select", "from students", "cgpa", ">", "any"], []),
    
    ("CGPA > all Mysore students",
     "Find students whose CGPA is greater than all students from Mysore",
     ["select", "from students", "cgpa", ">", "all"], []),
])

# ==================== 13b. Named-person comparison ====================
run([
    ("Salary > Ravi",
     "Find employees earning more than Ravi",
     ["select", "from employees", "salary", ">", "(select salary from employees where name = 'ravi')"], []),

    ("Salary < Priya",
     "Show employees earning less than Priya",
     ["select", "from employees", "salary", "<", "(select salary from employees where name = 'priya')"], []),

    ("Salary > Priya",
     "Find all employees earning more than Priya",
     ["select", "from employees", "salary", ">", "(select salary from employees where name = 'priya')"], []),

    ("Marks < Divya",
     "Find students with marks less than Divya",
     ["select", "from students", "marks", "<", "(select marks from students where name = 'divya')"], []),
])

# ==================== 13c. Aggregate-subquery comparison ====================
run([
    ("Salary > avg salary of all",
     "Show the names of employees whose salary is greater than the average salary of all employees",
     ["select", "name", "from employees", "salary", ">", "(select avg(salary) from employees)"], []),

    ("Marks > avg marks",
     "Find students whose marks are higher than the average marks of all students",
     ["select", "from students", "marks", ">", "(select avg(marks) from students)"], []),

    ("Salary > avg salary (no all)",
     "Find employees whose salary is more than the average salary",
     ["select", "from employees", "salary", ">", "(select avg(salary) from employees)"], []),

    ("Salary < avg salary",
     "Show employees earning less than the average salary of all employees",
     ["select", "from employees", "salary", "<", "(select avg(salary) from employees)"], []),

    ("Salary > max salary in HR",
     "Find employees whose salary is greater than the maximum salary in the HR department",
     ["select", "from employees", "salary", ">", "(select max(salary) from employees where department = 'hr')"], []),

    ("Avg salary (plain aggregate preserved)",
     "What is the average salary of all employees",
     ["select", "avg(salary)", "from employees"], []),

    ("Salary > all HR preserved",
     "Find employees whose salary is greater than all employees in the HR department",
     ["select", "from employees", "salary", ">", "all", "(select salary from employees where department = 'hr')"], []),
])

# ==================== 14. BETWEEN ====================
run([
    ("Salary between 50000 and 70000",
     "Find employees whose salary is between 50000 and 70000",
     ["select", "from employees", "salary", "between", "50000", "70000"], []),
    
    ("Marks between 70 and 90",
     "Find students whose marks are between 70 and 90",
     ["select", "from students", "marks", "between", "70", "90"], []),
    
    ("Experience between 5 and 10",
     "Find employees with experience between 5 and 10 years",
     ["select", "from employees", "experience", "between", "5", "10"], []),
])

# ==================== 15. DISTINCT ====================
run([
    ("Unique departments",
     "Show all unique employee departments",
     ["select", "distinct", "department", "from employees"], []),
    
    ("Unique student cities",
     "List all unique cities of students",
     ["select", "distinct", "city", "from students"], []),
    
    ("Distinct employee cities",
     "Show the distinct cities where employees work",
     ["select", "distinct", "city", "from employees"], []),
])

# ==================== DEMO PROMPTS ====================
run([
    ("Demo: employees salary > 60000",
     "Show all employees who have a salary greater than 60000",
     ["select", "from employees", "salary", ">", "60000"], []),
    
    ("Demo: avg salary per dept",
     "Find the average salary of employees in each department",
     ["select", "department", "avg(salary)", "from employees", "group by", "department"], []),
    
    ("Demo: depts with > 3 employees",
     "Show departments having more than 3 employees",
     ["select", "department", "count(*)", "from employees", "group by", "department", "having"], []),
    
    ("Demo: employees without manager",
     "Find employees who do not have a manager",
     ["select", "from employees", "manager_id", "is null"], []),
    
    ("Demo: project with lead employee",
     "Show each project along with the name of the employee leading it",
     ["select", "from projects", "join"], []),
    
    ("Demo: employees leading projects",
     "Find employees who are leading at least one project",
     ["select", "from employees", "exists", "projects"], []),
    
    ("Demo: students with subjects",
     "Show students along with the subjects they are taking",
     ["select", "from students", "join"], []),
    
    ("Demo: salary > all HR",
     "Find employees whose salary is greater than all employees in the HR department",
     ["select", "from employees", "salary", ">", "all", "employees", "hr"], []),
    
    ("Demo: CGPA > any Mysore",
     "Find students whose CGPA is greater than any student from Mysore",
     ["select", "from students", "cgpa", ">", "any"], []),
    
    ("Demo: dept with highest avg salary",
     "Show the department with the highest average employee salary",
     ["select", "department", "from employees"], []),
])

# ==================== 16. USER-AUDITED PROMPTS ====================
# The 10 prompts from the project's prompt checklist - higher-order
# comparisons (subqueries, ANY/ALL, correlated per-group averages, HAVING
# vs average-of-counts, rank offsets, NULL membership).
run([
    ("Names > avg salary of all employees",
     "Show the names of employees whose salary is greater than the average salary of all employees.",
     ["select", "name", "from employees", "salary", ">", "(select avg(salary) from employees)"], []),

    ("Dept with highest avg salary",
     "Find the department with the highest average employee salary.",
     ["select", "department", "avg(salary)", "from employees", "group by", "department", "order by", "desc", "limit 1"], []),

    ("Salary > all HR employees",
     "Show employees who earn more than every employee in the HR department.",
     ["select", "from employees", "salary", ">", "all", "(select salary from employees where department = 'hr')"], []),

    ("Salary > at least one IT employee",
     "Find employees whose salary is greater than at least one employee in the IT department.",
     ["select", "from employees", "salary", ">", "any", "(select salary from employees where department = 'it')"], []),

    ("Depts with > avg employees per dept",
     "Display departments that have more employees than the average number of employees per department.",
     ["select", "department", "count(*)", "from employees", "group by", "department", "having", "count(*)", ">", "avg(cnt)"], []),

    ("Students CGPA > their dept avg",
     "Show the names of students whose CGPA is higher than the average CGPA of students from their department.",
     ["select", "name", "from students", "cgpa", ">", "avg(cgpa)", "t2.subject = students.subject"], []),

    ("Employees in depts w/ member earning > 100000",
     "Find employees who belong to departments where at least one employee earns more than 100000.",
     ["select", "from employees", "department", "in", "select distinct department", "salary", ">", "100000"], []),

    ("Employees not in any department",
     "Show employees who do not belong to any department.",
     ["select", "from employees", "department", "is null"], []),

    ("Second-highest-paid employee",
     "Find the second-highest-paid employee.",
     ["select", "from employees", "order by", "salary", "desc", "limit 1", "offset 1"], []),

    ("Depts with avg salary above 60000",
     "Show the department name and average salary, but only for departments whose average salary is above 60000.",
     ["select", "department", "avg(salary)", "from employees", "group by", "department", "having", "avg(salary)", ">", "60000"], []),
])

# ==================== SUMMARY ====================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed_count}/{total} tests passed")
    if failed_tests:
        print(f"\nFailed tests ({len(failed_tests)}):")
        for t in failed_tests:
            print(f"  - {t}")
    print("=" * 60)
