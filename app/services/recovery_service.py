import sqlite3
from typing import Dict, Any, Optional
from decimal import Decimal

from app.repositories.payout_repository import PayoutRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.utils.financial import round_to_2dp
from app.utils.errors import ValidationError, NotFoundError, ConflictError

RECOVERABLE_STATUSES = {"failed", "cancelled", "rejected"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "rejected"}

class PayoutRecoveryService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        payout_repo: PayoutRepository,
        wallet_repo: WalletRepository,
        sale_repo: SaleRepository,
    ):
        self.conn = conn
        self.payout_repo = payout_repo
        self.wallet_repo = wallet_repo
        self.sale_repo = sale_repo

    def recover_payout(
        self, payout_id: str, failure_status: str, reason: Optional[str] = None
    ) -> Dict[str, Any]:
        if failure_status not in RECOVERABLE_STATUSES:
            raise ValidationError(
                f"Invalid recovery status '{failure_status}'. Must be one of {RECOVERABLE_STATUSES}."
            )

        payout = self.payout_repo.find_by_id(payout_id)
        if not payout:
            raise NotFoundError("Payout", payout_id)

        if payout["status"] in TERMINAL_STATUSES:
            raise ConflictError(
                f"Payout '{payout_id}' is already in terminal state '{payout['status']}' and cannot be recovered.",
                code="PAYOUT_TERMINAL_STATE",
            )

        payout_type = payout["type"]
        user_id = payout["user_id"]
        amount_dec = round_to_2dp(payout["amount"])

        self.conn.execute("BEGIN")
        try:
            failed_payout = self.payout_repo.update_status(
                payout_id, failure_status, failure_reason=reason
            )

            adjusted_amount = Decimal("0.00")
            if payout_type == "withdrawal":
                adjusted_amount = amount_dec
                self.wallet_repo.credit(user_id, amount_dec)
                self.wallet_repo.set_last_withdrawal_at(user_id, None)

            elif payout_type == "advance":
                adjusted_amount = -amount_dec
                self.wallet_repo.debit(user_id, amount_dec)
                self.sale_repo.reset_advance_payout_for_payout(payout_id)

            elif payout_type == "final":
                if amount_dec > 0:
                    adjusted_amount = -amount_dec
                    self.wallet_repo.debit(user_id, amount_dec)
                elif amount_dec < 0:
                    adjusted_amount = abs(amount_dec)
                    self.wallet_repo.credit(user_id, abs(amount_dec))
                self.sale_repo.reset_final_payout_for_payout(payout_id)

            else:
                raise ValidationError(f"Payout type '{payout_type}' cannot be recovered.")

            recovery_payout = self.payout_repo.create(
                user_id=user_id,
                payout_type="recovery",
                amount=adjusted_amount,
                status="completed",
                notes={
                    "original_payout_id": payout_id,
                    "original_type": payout_type,
                    "failure_status": failure_status,
                },
            )

            updated_wallet = self.wallet_repo.find_by_user_id(user_id)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return {
            "failed_payout": failed_payout,
            "recovery_payout": recovery_payout,
            "amount_adjusted": float(adjusted_amount),
            "wallet": updated_wallet,
            "message": f"Payout '{payout_id}' failed. Recovery executed with amount adjustment ₹{float(adjusted_amount):.2f}.",
        }

    def update_payout_status(
        self, payout_id: str, new_status: str, reason: Optional[str] = None
    ) -> Dict[str, Any]:
        payout = self.payout_repo.find_by_id(payout_id)
        if not payout:
            raise NotFoundError("Payout", payout_id)

        if payout["status"] != "processing":
            raise ConflictError(
                f"Payout '{payout_id}' is in state '{payout['status']}' and cannot be updated. Status can only be updated from 'processing'.",
                code="PAYOUT_NOT_PROCESSING",
            )

        if new_status in RECOVERABLE_STATUSES:
            return self.recover_payout(payout_id, new_status, reason)
        elif new_status == "completed":
            updated = self.payout_repo.update_status(payout_id, "completed")
            return {"payout": updated, "message": "Payout status updated to completed."}
        else:
            raise ValidationError(f"Invalid payout status '{new_status}'.")
