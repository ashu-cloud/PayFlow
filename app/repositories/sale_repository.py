import uuid
import sqlite3
from typing import Optional, List, Dict, Any, Union
from decimal import Decimal
from app.repositories.base_repository import BaseRepository
from app.utils.financial import round_to_2dp

class SaleRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "sales")

    def create(
        self,
        user_id: str,
        brand: str,
        earning: Union[Decimal, float, int, str],
        status: str = "pending",
        sale_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        sid = sale_id or str(uuid.uuid4())
        earn_val = float(round_to_2dp(earning))
        cursor = self.conn.cursor()
        query = """
            INSERT INTO sales (id, user_id, brand, status, earning, advance_paid)
            VALUES (?, ?, ?, ?, ?, 0)
        """
        cursor.execute(query, (sid, user_id, brand, status, earn_val))
        return self.find_by_id(sid)

    def find_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM sales WHERE user_id = ? ORDER BY created_at ASC"
        cursor.execute(query, (user_id,))
        return [dict(r) for r in cursor.fetchall()]

    def find_eligible_for_advance(self, user_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = """
            SELECT * FROM sales
            WHERE user_id = ? AND status = 'pending' AND advance_payout_id IS NULL
            ORDER BY created_at ASC
        """
        cursor.execute(query, (user_id,))
        return [dict(r) for r in cursor.fetchall()]

    def find_eligible_for_final_payout(self, user_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = """
            SELECT * FROM sales
            WHERE user_id = ? AND status IN ('approved', 'rejected') AND final_payout_id IS NULL
            ORDER BY created_at ASC
        """
        cursor.execute(query, (user_id,))
        return [dict(r) for r in cursor.fetchall()]

    def mark_advance_paid(
        self, sale_id: str, payout_id: str, advance_paid: Union[Decimal, float, int, str]
    ) -> int:
        amt = float(round_to_2dp(advance_paid))
        cursor = self.conn.cursor()
        query = """
            UPDATE sales
            SET advance_payout_id = ?, advance_paid = ?, updated_at = datetime('now')
            WHERE id = ? AND advance_payout_id IS NULL AND status = 'pending'
        """
        cursor.execute(query, (payout_id, amt, sale_id))
        return cursor.rowcount

    def mark_final_paid(self, sale_id: str, payout_id: str) -> int:
        cursor = self.conn.cursor()
        query = """
            UPDATE sales
            SET final_payout_id = ?, updated_at = datetime('now')
            WHERE id = ? AND final_payout_id IS NULL
        """
        cursor.execute(query, (payout_id, sale_id))
        return cursor.rowcount

    def reconcile(self, sale_id: str, new_status: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = """
            UPDATE sales
            SET status = ?, reconciled_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ? AND status = 'pending'
        """
        cursor.execute(query, (new_status, sale_id))
        if cursor.rowcount == 0:
            return None
        return self.find_by_id(sale_id)

    def reset_advance_payout_for_payout(self, payout_id: str) -> int:
        cursor = self.conn.cursor()
        query = """
            UPDATE sales
            SET advance_payout_id = NULL, advance_paid = 0, updated_at = datetime('now')
            WHERE advance_payout_id = ?
        """
        cursor.execute(query, (payout_id,))
        return cursor.rowcount

    def reset_final_payout_for_payout(self, payout_id: str) -> int:
        cursor = self.conn.cursor()
        query = """
            UPDATE sales
            SET final_payout_id = NULL, updated_at = datetime('now')
            WHERE final_payout_id = ?
        """
        cursor.execute(query, (payout_id,))
        return cursor.rowcount

    def find_by_advance_payout_id(self, payout_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM sales WHERE advance_payout_id = ?"
        cursor.execute(query, (payout_id,))
        return [dict(r) for r in cursor.fetchall()]

    def find_by_final_payout_id(self, payout_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM sales WHERE final_payout_id = ?"
        cursor.execute(query, (payout_id,))
        return [dict(r) for r in cursor.fetchall()]
