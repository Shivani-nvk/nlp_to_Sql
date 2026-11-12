"""
Tenant Database Manager.

Manages dynamic database connection engines and pools for multiple organizations/tenants.
Supports MySQL, PostgreSQL, SQLite, etc. via SQLAlchemy.

Tenant lookup (plugin path):
  1. X-API-Key / api_key  -> PLUGIN_TENANTS registry (server-side URLs)
  2. X-Database-URL       -> only when PLUGIN_ALLOW_INLINE_URL is enabled (local tests)
  3. Otherwise            -> no tenant (plugin endpoints return 401)

The default local MySQL app (.env) is NOT used as a silent plugin fallback.
"""

import os
import threading
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

load_dotenv()

# In-memory engine cache { cache_key: Engine }
_engines = {}
_lock = threading.Lock()
_registry_cache = None
_demo_seeded = False


def _demo_sqlite_url():
    demo_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "plugin_demo.db")
    )
    # SQLAlchemy on Windows wants forward slashes in sqlite URLs
    return "sqlite:///" + demo_path.replace("\\", "/")


def _parse_tenant_registry():
    """
    PLUGIN_TENANTS format: key=url;key2=url
    Example: demo=sqlite:///plugin_demo.db;acme=postgresql://user:pass@host/db
    """
    raw = (os.environ.get("PLUGIN_TENANTS") or "").strip()
    tenants = {}
    if raw:
        for part in raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, url = part.split("=", 1)
            key = key.strip()
            url = url.strip()
            if key and url:
                tenants[key] = url
    if "demo" not in tenants:
        tenants["demo"] = _demo_sqlite_url()
    return tenants


def get_tenant_registry():
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = _parse_tenant_registry()
    return _registry_cache


def inline_urls_allowed():
    return os.environ.get("PLUGIN_ALLOW_INLINE_URL", "").lower() in ("1", "true", "yes")


def _get_default_url():
    """Builds connection URL from local .env settings for backward compatibility."""
    host = os.environ.get("DB_HOST", "localhost")
    user = os.environ.get("DB_USER", "root")
    password = os.environ.get("DB_PASSWORD", "")
    db_name = os.environ.get("DB_NAME", "")
    port = os.environ.get("DB_PORT", "3306")
    return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{db_name}"


def get_tenant_engine(connection_url=None, tenant_id=None):
    """
    Returns a SQLAlchemy Engine for the specified connection URL or tenant ID.
    If neither is provided, returns the default local database engine.
    """
    url = (connection_url or "").strip()

    if not url and tenant_id:
        url = get_tenant_registry().get(tenant_id, "")

    if not url:
        url = _get_default_url()

    cache_key = tenant_id or url

    with _lock:
        if cache_key in _engines:
            engine = _engines[cache_key]
        else:
            connect_args = {}
            if url.startswith("sqlite"):
                connect_args = {"check_same_thread": False}
                engine = create_engine(
                    url,
                    connect_args=connect_args,
                    poolclass=NullPool,
                )
            else:
                engine_kwargs = dict(
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                )
                if url.startswith("postgresql") or url.startswith("postgres"):
                    engine_kwargs["connect_args"] = {"connect_timeout": 5}
                engine = create_engine(url, **engine_kwargs)
            _engines[cache_key] = engine

    if tenant_id == "demo" or (url and "plugin_demo.db" in url):
        ensure_demo_sqlite(engine)

    return engine


def resolve_plugin_engine(api_key=None, database_url=None):
    """
    Resolve a plugin request to (engine, tenant_id, error_message).
    engine is None when the request is not authorized.
    """
    api_key = (api_key or "").strip()
    database_url = (database_url or "").strip()

    if api_key:
        registry = get_tenant_registry()
        if api_key not in registry:
            return None, None, "Invalid API key."
        engine = get_tenant_engine(registry[api_key], tenant_id=api_key)
        return engine, api_key, None

    if database_url:
        if not inline_urls_allowed():
            return None, None, (
                "Inline database URLs are disabled. "
                "Set PLUGIN_ALLOW_INLINE_URL=1 for local tests, or use an API key."
            )
        engine = get_tenant_engine(database_url)
        return engine, None, None

    return None, None, "Missing API key. Pass X-API-Key or api_key."


def test_connection(connection_url):
    """
    Tests connecting to a database.
    Returns:
        (success: bool, dialect: str or None, error_message: str or None)
    """
    try:
        connect_args = {}
        if not connection_url.startswith("sqlite"):
            connect_args = {"connect_timeout": 5}
        else:
            connect_args = {"check_same_thread": False}
        engine = create_engine(
            connection_url,
            poolclass=NullPool,
            connect_args=connect_args,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        dialect = engine.dialect.name
        engine.dispose()
        return True, dialect, None
    except Exception as e:
        return False, None, str(e)


def execute_tenant_sql(engine, sql):
    """
    Executes a validated read-only SQL query against an engine.
    Returns:
        (rows: list[dict], columns: list[str], error: str or None)
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            if result.returns_rows:
                columns = list(result.keys())
                rows = [dict(row._mapping) for row in result.fetchall()]
                return rows, columns, None
            return [], [], None
    except Exception as e:
        return None, [], str(e)


def ensure_demo_sqlite(engine=None):
    """Creates a small sample org database for the embeddable widget demo."""
    global _demo_seeded
    if engine is None:
        engine = get_tenant_engine(tenant_id="demo")
    if _demo_seeded:
        return engine

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY,
                name TEXT,
                department TEXT,
                salary INTEGER,
                location TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                customer TEXT,
                product TEXT,
                amount INTEGER,
                status TEXT
            )
        """))
        count = conn.execute(text("SELECT COUNT(*) FROM employees")).scalar()
        if not count:
            conn.execute(text("""
                INSERT INTO employees (name, department, salary, location) VALUES
                ('Amina Khan', 'Sales', 72000, 'Bengaluru'),
                ('Rohit Mehta', 'Engineering', 98000, 'Hyderabad'),
                ('Priya Nair', 'Sales', 68000, 'Mumbai'),
                ('Daniel Ortiz', 'Finance', 81000, 'Bengaluru'),
                ('Sara Ali', 'Engineering', 105000, 'Pune')
            """))
        count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        if not count:
            conn.execute(text("""
                INSERT INTO orders (customer, product, amount, status) VALUES
                ('Northwind Ltd', 'Analytics Seat', 2400, 'paid'),
                ('Helios Corp', 'Warehouse Sync', 1800, 'pending'),
                ('Northwind Ltd', 'Support Pack', 900, 'paid'),
                ('Kite Retail', 'Analytics Seat', 2400, 'refunded'),
                ('Helios Corp', 'Analytics Seat', 2400, 'paid')
            """))
    _demo_seeded = True
    return engine
