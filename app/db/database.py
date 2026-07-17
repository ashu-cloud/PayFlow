import sqlite3
import os

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "payouts.db")

def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates a sqlite3 connection configured for dictionary-like row access,
    WAL mode, autocommit mode for explicit transaction management, and strict foreign keys."""
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def init_db(conn: sqlite3.Connection, schema_file_path: str = None) -> None:
    """Runs the SQL migration schema to initialize tables and indexes."""
    if schema_file_path is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        schema_file_path = os.path.join(base_dir, "..", "..", "001_schema.sql")
    
    if os.path.exists(schema_file_path):
        with open(schema_file_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn.executescript(schema_sql)
