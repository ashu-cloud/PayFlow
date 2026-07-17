import uuid
import json
import sqlite3
from typing import Optional, List, Dict, Any, Union
from decimal import Decimal
from app.repositories.base_repository import BaseRepository
from app.utils.financial import round_to_2dp

class PayoutRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "payouts")

    def create(
        self,
        user_id: str,
        payout_type: str,
        amount: Union[Decimal, float, int, str],
        status: str = "initiated",
        notes: Optional[Dict[str, Any]] = None,
        payout_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pid = payout_id or str(uuid.uuid4())
        amt_val = float(round_to_2dp(amount))
        notes_str = json.dumps(notes) if notes is not None else None
        
        cursor = self.conn.cursor()
        query = """
            INSERT INTO payouts (id, user_id, type, amount, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        cursor.execute(query, (pid, user_id, payout_type, amt_val, status, notes_str))
        return self.find_by_id(pid)

    def find_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM payouts WHERE user_id = ? ORDER BY created_at DESC"
        cursor.execute(query, (user_id,))
        return [dict(r) for r in cursor.fetchall()]

    def find_by_user_id_and_type(self, user_id: str, payout_type: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM payouts WHERE user_id = ? AND type = ? ORDER BY created_at DESC"
        cursor.execute(query, (user_id, payout_type))
        return [dict(r) for r in cursor.fetchall()]

    def update_status(
        self, payout_id: str, new_status: str, failure_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        completed_at_sql = "datetime('now')" if new_status == "completed" else "completed_at"
        failed_at_sql = "datetime('now')" if new_status in ("failed", "cancelled", "rejected") else "failed_at"

        query = f"""
            UPDATE payouts
            SET status = ?,
                failure_reason = COALESCE(?, failure_reason),
                completed_at = {completed_at_sql},
                failed_at = {failed_at_sql},
                updated_at = datetime('now')
            WHERE id = ?
        """
        cursor.execute(query, (new_status, failure_reason, payout_id))
        return self.find_by_id(payout_id)

    def add_sale_mapping(
        self, payout_id: str, sale_id: str, contribution_amount: Union[Decimal, float, int, str]
    ) -> Dict[str, Any]:
        mapping_id = str(uuid.uuid4())
        contrib_val = float(round_to_2dp(contribution_amount))
        cursor = self.conn.cursor()
        query = """
            INSERT OR IGNORE INTO payout_sale_mappings (id, payout_id, sale_id, contribution_amount)
            VALUES (?, ?, ?, ?)
        """
        cursor.execute(query, (mapping_id, payout_id, sale_id, contrib_val))
        return {"id": mapping_id, "payout_id": payout_id, "sale_id": sale_id, "contribution_amount": contrib_val}

    def get_sale_mappings(self, payout_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = """
            SELECT psm.*, s.brand, s.status as sale_status, s.earning, s.advance_paid
            FROM payout_sale_mappings psm
            JOIN sales s ON psm.sale_id = s.id
            WHERE psm.payout_id = ?
        """
        cursor.execute(query, (payout_id,))
        return [dict(r) for r in cursor.fetchall()]

    def find_by_status(self, status: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM payouts WHERE status = ? ORDER BY created_at DESC"
        cursor.execute(query, (status,))
        return [dict(r) for r in cursor.fetchall()]
