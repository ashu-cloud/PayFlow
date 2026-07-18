import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlite3 import Connection
from fastapi.testclient import TestClient
from app.db.database import get_db_connection, init_db
from app.main import app

@pytest.fixture
def db_conn() -> Connection:
    conn = get_db_connection(":memory:")
    init_db(conn)
    yield conn
    conn.close()

@pytest.fixture
def client(db_conn: Connection) -> TestClient:
    def _get_test_db():
        yield db_conn

    app.dependency_overrides[get_db_connection] = _get_test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
