import os
from dotenv import load_dotenv
from services.schema_service import get_column_values

load_dotenv()

# Toggle point for later: just change this env var (or the default
# below) to switch providers - nothing else in the project needs to
# change, since query.py only ever calls llm_fallback_convert(), and
# refine.py only ever calls llm_refine_convert().
AI_PROVIDER = os.environ.get("AI_PROVIDER", "groq")

# Ollama (fully local / offline): Ollama exposes an OpenAI-compatible API
# on http://localhost:11434/v1, so the same `openai` SDK is reused - no
# extra pip packages. Just `pip install` nothing, run `ollama serve`, and
# pick a model you have pulled (see README section below). The api_key is
# ignored by Ollama but the OpenAI client requires the field to exist.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")

# xAI's API is OpenAI-compatible - same /v1/chat/completions shape, just a
# different base_url and API key - so the openai SDK is reused as the
# client rather than writing raw HTTP calls for it.
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_MODEL = "grok-2-latest"

# Groq (GroqCloud) is also OpenAI-compatible, and its free tier needs no
# billing/card on file - unlike the Grok/xAI path above, which requires
# credits. gpt-oss-120b is plenty for "turn this question + schema into
# one SELECT" - this isn't a task that needs a frontier model.
# Note: llama-3.3-70b-versatile (the model originally used here) was
# deprecated by Groq for free/developer-tier accounts on Aug 16, 2026 -
# gpt-oss-120b is their recommended replacement.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"


def llm_fallback_convert(question, schema, previous_sql=None, error=None):
    """
    Called only when the rule-based nlp_to_sql.py couldn't recognise
    anything meaningful in the question (or as a self-healing repair when
    the generated SQL fails at runtime). Returns a SQL string, or None
    if the AI call failed or produced something unusable.

    When previous_sql + error are supplied, the prompt asks the model to
    correct the faulty SQL rather than generate from scratch.
    """
    try:
        if AI_PROVIDER == "groq":
            return _convert_with_groq(question, schema, previous_sql, error)
        elif AI_PROVIDER == "grok":
            return _convert_with_grok(question, schema, previous_sql, error)
        elif AI_PROVIDER == "gemini":
            return _convert_with_gemini(question, schema, previous_sql, error)
        elif AI_PROVIDER == "ollama":
            return _convert_with_ollama(question, schema, previous_sql, error)
        # Placeholder for later - uncomment and implement when ready:
        # elif AI_PROVIDER == "openai":
        #     return _convert_with_openai(question, schema)
        else:
            print(f"Unknown AI_PROVIDER '{AI_PROVIDER}'")
            return None
    except Exception as e:
        print(f"AI fallback failed: {e}")
        return None


def _build_prompt(question, schema, previous_sql=None, error=None):
    schema_text = "\n".join(
        f"{table}: {', '.join(columns.keys())}"
        for table, columns in schema.items()
        if table != "app_users"   # never expose the auth table to the AI
    )

    if previous_sql and error:
        return f"""Fix the SQL query below so it runs correctly against this database.

Database schema:
{schema_text}
{_values_section()}
Original question: {question}

Previous SQL (failed):
{previous_sql}

Problem:
{error}

Rules:
- Output ONLY the corrected raw SQL query - no explanation, no markdown, no backticks.
- The query MUST start with SELECT.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any non-SELECT statement.
- Only use tables and columns listed above - never invent column or table names.
- Fix whatever caused it while keeping the question's intent.
{_VALUE_GROUNDING_RULES}
Corrected SQL:"""

    return f"""Convert this English question into a single MySQL SELECT query.

Database schema:
{schema_text}
{_values_section()}
Rules:
- Output ONLY the raw SQL query - no explanation, no markdown, no backticks.
- The query MUST start with SELECT.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any non-SELECT statement.
- Only use tables and columns listed above - never invent column or table names.
{_VALUE_GROUNDING_RULES}
Question: {question}
SQL:"""


def _get_xai_client():
    from openai import OpenAI
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is not set in the environment/.env file.")
    return OpenAI(api_key=api_key, base_url=XAI_BASE_URL)


def _get_ollama_client():
    from openai import OpenAI
    return OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL)


def _get_groq_client():
    from openai import OpenAI
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set in the environment/.env file.")
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def _clean_sql(text):
    # Grok, like Gemini, sometimes wraps output in markdown fences despite
    # instructions not to.
    sql = text.strip()
    sql = sql.replace("```sql", "").replace("```", "").strip()
    sql = sql.rstrip(";").strip()
    return sql


# Only a sample of each column's values is rendered into the prompt, to keep
# it readable - the sampler already dropped any column with too many distinct
# values, so what remains is short by construction. This is a display cap on
# top of that, not a correctness cap.
_MAX_VALUES_SHOWN_PER_COLUMN = 25


def _build_values_hint():
    """
    Renders the real contents of low-cardinality text columns as a prompt
    section, or "" when the values could not be sampled (DB down, no such
    columns). Callers splice this in unconditionally; an empty string simply
    produces the same prompt as before this existed.

    This is what stops the model from inventing literals. Knowing only that a
    column is called Student_Name or Exam is not enough to write a WHERE
    clause against it - the model guesses a plausible-looking value, the SQL
    runs fine, and it silently returns nothing. Handing over the actual
    values lets it either match real data or notice the thing it was asked
    about genuinely isn't there.
    """
    try:
        column_values = get_column_values()
    except Exception:
        return ""

    if not column_values:
        return ""

    lines = []
    for table in sorted(column_values):
        for column in sorted(column_values[table]):
            values = column_values[table][column]
            shown = values[:_MAX_VALUES_SHOWN_PER_COLUMN]
            rendered = ", ".join(f"'{v}'" for v in shown)
            if len(values) > len(shown):
                rendered += f", ... ({len(values) - len(shown)} more)"
            lines.append(f"- {table}.{column}: {rendered}")

    if not lines:
        return ""

    return (
        "Actual values stored in these columns (from the live database):\n"
        + "\n".join(lines)
        + "\n"
    )


# The rules that make the value hint actionable. Kept in one place because
# both the fresh-question prompt and the refine prompt need them verbatim -
# the refine path is where the bad literals were actually being produced.
_VALUE_GROUNDING_RULES = """- Only compare a column against values that appear in that column's list above, \
copied EXACTLY. Never invent or guess a value for a column.
- If the user asks about something with NO matching value in that column's list, \
that thing does not exist in this database. Write the query WITHOUT that filter \
so the user gets the real records, rather than adding a filter that can never match.
- If the user's word is only PART of a stored value (e.g. they said "ananya" but \
the column stores "Ananya Singh"), match the stored value with LIKE '%ananya%' \
instead of an exact `= 'ananya'`."""


def _values_section():
    """The value-hint block plus its rules, or "" when values are unavailable."""
    hint = _build_values_hint()
    if not hint:
        return ""
    return f"\n{hint}\nRules:\n{_VALUE_GROUNDING_RULES}\n"


# Fed back to the model when a generated query executed cleanly but matched
# nothing. This is the failure mode value grounding prevents, and this is the
# safety net for when it doesn't: a query with a string literal that exists
# in no row is perfectly valid SQL, so it raises no error, the self-healing
# loop used to treat it as success, and the user was told "no records matched"
# - which is a confident and completely wrong answer.
EMPTY_RESULT_HINT = (
    "The query ran successfully but returned 0 rows. In practice this almost "
    "always means a string literal in a WHERE clause does not exist in the "
    "column being filtered - e.g. filtering Exam = 'final' when the only "
    "stored values are 'Internal 1' and 'Semester'. Check EVERY string "
    "literal you wrote against the actual values listed above, then either "
    "use a value that really exists, use LIKE '%value%' when the user's word "
    "is only part of a stored value, or drop that filter entirely if the "
    "thing being asked about genuinely does not exist in this database. "
    "Returning the real rows is far better than returning none."
)


def _convert_with_grok(question, schema, previous_sql=None, error=None):
    client = _get_xai_client()

    response = client.chat.completions.create(
        model=XAI_MODEL,
        messages=[{"role": "user", "content": _build_prompt(question, schema, previous_sql, error)}],
    )
    return _clean_sql(response.choices[0].message.content)


def _convert_with_groq(question, schema, previous_sql=None, error=None):
    client = _get_groq_client()

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": _build_prompt(question, schema, previous_sql, error)}],
    )
    return _clean_sql(response.choices[0].message.content)


def _convert_with_gemini(question, schema, previous_sql=None, error=None):
    from google import genai
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=_build_prompt(question, schema, previous_sql, error)
    )
    return _clean_sql(response.text)


def _convert_with_ollama(question, schema, previous_sql=None, error=None):
    client = _get_ollama_client()

    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": _build_prompt(question, schema, previous_sql, error)}],
        temperature=0,
    )
    return _clean_sql(response.choices[0].message.content)


def llm_refine_convert(previous_sql, feedback, schema, error=None):
    """
    Called only when the rule-based query_refiner.py couldn't confidently
    map the user's feedback to an edit (RefinementError), or when the refined
    SQL needs self-healing repair after a database error.
    Returns a SQL string, or None if the call failed or produced something unusable.
    """
    try:
        if AI_PROVIDER == "groq":
            return _refine_with_groq(previous_sql, feedback, schema, error)
        elif AI_PROVIDER == "grok":
            return _refine_with_grok(previous_sql, feedback, schema, error)
        elif AI_PROVIDER == "gemini":
            return _refine_with_gemini(previous_sql, feedback, schema, error)
        elif AI_PROVIDER == "ollama":
            return _refine_with_ollama(previous_sql, feedback, schema, error)
        else:
            print(f"Unknown AI_PROVIDER '{AI_PROVIDER}'")
            return None
    except Exception as e:
        print(f"AI refine failed: {e}")
        return None


def _build_refine_prompt(previous_sql, feedback, schema, error=None):
    schema_text = "\n".join(
        f"{table}: {', '.join(columns.keys())}"
        for table, columns in schema.items()
        if table != "app_users"
    )

    error_section = (
        f"\nProblem with the previous query:\n{error}\n"
        "Please fix whatever caused it while applying the requested changes.\n"
        if error else ""
    )

    return f"""You are refining an existing MySQL SELECT query based on user feedback.

Database schema:
{schema_text}
{_values_section()}
Previous SQL query:
{previous_sql}

User feedback: {feedback}
{error_section}
Rules:
- Output ONLY the updated raw SQL query - no explanation, no markdown, no backticks.
- The query MUST start with SELECT.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any non-SELECT statement.
- Only use tables and columns listed in the schema above - never invent column or table names.
- The user feedback is the PRIMARY instruction and MUST be reflected in the output.
  Never return the previous query unchanged - always apply what was asked.
- The feedback wins over the previous query's shape. If satisfying it needs a
  JOIN, a subquery or an extra WHERE condition that the previous query did not
  have, add it. Keeping the previous query "unchanged" is never the answer.
- Keep only what the feedback did not mention: unrelated columns, filters and
  ordering from the previous query should survive.
{_VALUE_GROUNDING_RULES}
Updated SQL:"""


def _refine_with_grok(previous_sql, feedback, schema, error=None):
    client = _get_xai_client()

    response = client.chat.completions.create(
        model=XAI_MODEL,
        messages=[{"role": "user", "content": _build_refine_prompt(previous_sql, feedback, schema, error)}],
    )
    return _clean_sql(response.choices[0].message.content)


def _refine_with_groq(previous_sql, feedback, schema, error=None):
    client = _get_groq_client()

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": _build_refine_prompt(previous_sql, feedback, schema, error)}],
    )
    return _clean_sql(response.choices[0].message.content)


def _refine_with_gemini(previous_sql, feedback, schema, error=None):
    from google import genai
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=_build_refine_prompt(previous_sql, feedback, schema, error)
    )
    return _clean_sql(response.text)


def _refine_with_ollama(previous_sql, feedback, schema, error=None):
    client = _get_ollama_client()

    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": _build_refine_prompt(previous_sql, feedback, schema, error)}],
        temperature=0,
    )
    return _clean_sql(response.choices[0].message.content)