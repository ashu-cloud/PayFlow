import uuid
import sqlite3
from typing import Optional, Dict, Any
from app.repositories.base_repository import BaseRepository

class UserRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "users")

    def create(self, name: str, email: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        uid = user_id or str(uuid.uuid4())
        cursor = self.conn.cursor()
        query = """
            INSERT INTO users (id, name, email)
            VALUES (?, ?, ?)
        """
        cursor.execute(query, (uid, name, email))
        return self.find_by_id(uid)

    def find_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM users WHERE email = ?"
        cursor.execute(query, (email,))
        row = cursor.fetchone()
        return dict(row) if row else None
