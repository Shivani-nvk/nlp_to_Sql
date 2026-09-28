import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

_pool = None


def get_db_connection():
    global _pool
    if _pool is None:
        _pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="app_pool",
            pool_size=5,
            pool_reset_session=True,
            host=os.environ.get("DB_HOST"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            database=os.environ.get("DB_NAME"),
        )
    return _pool.get_connection()