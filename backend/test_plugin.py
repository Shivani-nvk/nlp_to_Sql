"""
Plugin / multi-tenant database tests.

Uses SQLite only so the suite does not need MySQL or PostgreSQL.
The query path is tested with a stubbed LLM so no API key is required.

Run from backend/: python test_plugin.py
"""

import os
import sys
import tempfile

sys.path.insert(0, ".")

from sqlalchemy import text
from services.tenant_manager import (
    get_tenant_engine, test_connection, execute_tenant_sql, ensure_demo_sqlite,
)
from services.schema_service import get_schema, get_column_values, schema_summary, invalidate_schema_cache
from services.sql_validator import validate_sql
from services import hybrid_router
from services.hybrid_router import run_hybrid_query

PASS = 0
FAIL = 0
failures = []


def report(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        failures.append((name, detail))
        print(f"  FAIL  {name}  {detail}")


def make_sample_db():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    url = "sqlite:///" + path.replace("\\", "/")
    engine = get_tenant_engine(url)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                city TEXT,
                status TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO customers (name, city, status) VALUES
            ('Ada Lovelace', 'London', 'active'),
            ('Alan Turing', 'Manchester', 'active'),
            ('Grace Hopper', 'New York', 'paused')
        """))
    return url, engine, path


def main():
    print("\n=== Plugin multi-database tests ===\n")
    url, engine, path = make_sample_db()
    try:
        ok, dialect, err = test_connection(url)
        report("sqlite connection", ok and dialect == "sqlite", err or "")

        invalidate_schema_cache()
        schema = get_schema(engine=engine)
        report(
            "introspects customers table",
            "customers" in schema and "name" in schema["customers"],
            str(schema),
        )
        report(
            "does not require hardcoded student_info",
            "student_info" not in schema,
            str(list(schema)),
        )

        summary = schema_summary(schema)
        report("schema summary table_count", summary["table_count"] == 1, str(summary))

        values = get_column_values(engine=engine)
        cities = (values.get("customers") or {}).get("city") or []
        report("samples city values", "London" in cities, str(values))

        ok, reason = validate_sql("DROP TABLE customers")
        report("blocks DROP", not ok, reason or "")
        ok, reason = validate_sql("SELECT name FROM customers")
        report("allows SELECT", ok, reason or "")

        rows, columns, err = execute_tenant_sql(engine, "SELECT name FROM customers ORDER BY id")
        report("execute tenant sql", err is None and len(rows) == 3, err or str(rows))
        report("returns columns", columns == ["name"], str(columns))

        original = hybrid_router.llm_fallback_convert

        def fake_convert(question, schema, previous_sql=None, error=None,
                         dialect="mysql", column_values=None):
            return "SELECT name, city FROM customers WHERE status = 'active'"

        hybrid_router.llm_fallback_convert = fake_convert
        try:
            result = run_hybrid_query(
                "show active customers",
                engine=engine,
                is_custom_tenant=True,
            )
            report(
                "plugin query skips rule engine",
                result["source"] in ("agentic", "agentic_self_healed")
                and result["error"] is None
                and len(result["result"]) == 2,
                str(result),
            )
            report(
                "plugin query returns columns",
                "name" in (result.get("columns") or []),
                str(result.get("columns")),
            )
        finally:
            hybrid_router.llm_fallback_convert = original

        demo_engine = ensure_demo_sqlite()
        demo_schema = get_schema(engine=demo_engine)
        report(
            "demo sqlite has employees and orders",
            "employees" in demo_schema and "orders" in demo_schema,
            str(list(demo_schema)),
        )
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    print(f"\n{PASS} passed, {FAIL} failed")
    if failures:
        print("Failures:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
