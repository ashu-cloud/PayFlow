import uuid
import sqlite3
from typing import Optional, Dict, Any, Union
from decimal import Decimal
from app.repositories.base_repository import BaseRepository
from app.utils.financial import round_to_2dp

class WalletRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "wallets")

    def create(self, user_id: str, wallet_id: Optional[str] = None) -> Dict[str, Any]:
        wid = wallet_id or str(uuid.uuid4())
        cursor = self.conn.cursor()
        query = """
            INSERT INTO wallets (id, user_id, withdrawable_balance)
            VALUES (?, ?, 0)
        """
        cursor.execute(query, (wid, user_id))
        return self.find_by_id(wid)

    def find_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM wallets WHERE user_id = ?"
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def credit(self, user_id: str, amount: Union[Decimal, float, int, str]) -> Dict[str, Any]:
        amt = float(round_to_2dp(amount))
        cursor = self.conn.cursor()
        query = """
            UPDATE wallets
            SET withdrawable_balance = ROUND(withdrawable_balance + ?, 10),
                updated_at = datetime('now')
            WHERE user_id = ?
        """
        cursor.execute(query, (amt, user_id))
        return self.find_by_user_id(user_id)

    def debit(self, user_id: str, amount: Union[Decimal, float, int, str]) -> Dict[str, Any]:
        amt = float(round_to_2dp(amount))
        cursor = self.conn.cursor()
        query = """
            UPDATE wallets
            SET withdrawable_balance = ROUND(withdrawable_balance - ?, 10),
                updated_at = datetime('now')
            WHERE user_id = ?
        """
        cursor.execute(query, (amt, user_id))
        return self.find_by_user_id(user_id)

    def set_last_withdrawal_at(self, user_id: str, timestamp: Optional[str]) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        query = """
            UPDATE wallets
            SET last_withdrawal_at = ?,
                updated_at = datetime('now')
            WHERE user_id = ?
        """
        cursor.execute(query, (timestamp, user_id))
        return self.find_by_user_id(user_id)
