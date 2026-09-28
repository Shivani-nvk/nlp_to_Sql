import sys
sys.path.insert(0, ".")
from nltk.tokenize import word_tokenize
from services import nlp_to_sql as ns

qs = [
    "Show each project along with the name of its lead employee.",
    "Display project names and the department of their lead employees.",
    "Show project name, lead employee name, department, and salary for projects led by IT employees.",
    "Display the 5 highest-paid employees.",
    "Find students whose CGPA is above 8.5.",
    "Find departments where the average performance rating is greater than 4.",
    "Display departments whose total salary exceeds 200000.",
    "Find employees who lead at least one project.",
    "Find students who are not taking any subject.",
    "Find students whose marks are greater than ALL students taking Science.",
    "Find employees with salary greater than the salary of Amit.",
]
for q in qs:
    toks = word_tokenize(q.lower())
    toks = ns.merge_multiword_columns(toks)
    toks = ns.words_to_numbers(toks)
    toks = ns.merge_comparison_phrases(toks)
    print("Q:", q)
    print("  tokens:", toks)
    print()