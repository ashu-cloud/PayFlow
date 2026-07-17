import sqlite3
from typing import Optional, List, Dict, Any

class BaseRepository:
    def __init__(self, conn: sqlite3.Connection, table_name: str):
        self.conn = conn
        self.table_name = table_name

    def find_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = f"SELECT * FROM {self.table_name} WHERE id = ?"
        cursor.execute(query, (entity_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def find_all(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = f"SELECT * FROM {self.table_name}"
        cursor.execute(query)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def exists_by_id(self, entity_id: str) -> bool:
        cursor = self.conn.cursor()
        query = f"SELECT 1 FROM {self.table_name} WHERE id = ? LIMIT 1"
        cursor.execute(query, (entity_id,))
        return cursor.fetchone() is not None
