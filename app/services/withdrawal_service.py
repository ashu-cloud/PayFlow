import sqlite3
from typing import Dict, Any
from datetime import datetime, timezone
from decimal import Decimal
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.payout_repository import PayoutRepository
from app.utils.financial import round_to_2dp
from app.utils.errors import (
    ValidationError,
    NotFoundError,
    InsufficientBalanceError,
    RateLimitError,
)

TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000

class WithdrawalService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_repo: UserRepository,
        wallet_repo: WalletRepository,
        payout_repo: PayoutRepository,
    ):
        self.conn = conn
        self.user_repo = user_repo
        self.wallet_repo = wallet_repo
        self.payout_repo = payout_repo

    def get_cooldown_remaining_ms(self, user_id: str) -> int:
        wallet = self.wallet_repo.find_by_user_id(user_id)
        if not wallet:
            raise NotFoundError("Wallet for user", user_id)

        last_ts_str = wallet.get("last_withdrawal_at")
        if not last_ts_str:
            return 0

        try:
            last_ts_str = last_ts_str.replace(" ", "T")
            if not last_ts_str.endswith("Z") and "+" not in last_ts_str:
                last_ts_str += "+00:00"
            last_dt = datetime.fromisoformat(last_ts_str)
        except Exception:
            return 0

        now_dt = datetime.now(timezone.utc)
        elapsed_ms = int((now_dt - last_dt).total_seconds() * 1000)

        if elapsed_ms < TWENTY_FOUR_HOURS_MS:
            return TWENTY_FOUR_HOURS_MS - elapsed_ms
        return 0

    def initiate_withdrawal(self, user_id: str, amount: Any) -> Dict[str, Any]:
        amt_dec = round_to_2dp(amount)
        if amt_dec <= Decimal("0.00"):
            raise ValidationError("Withdrawal amount must be greater than zero.")

        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        self.conn.execute("BEGIN")
        try:
            cooldown_ms = self.get_cooldown_remaining_ms(user_id)
            if cooldown_ms > 0:
                hours_rem = cooldown_ms / (1000 * 60 * 60)
                raise RateLimitError(
                    f"Withdrawal cooldown active. Try again in {hours_rem:.1f} hours.",
                    cooldown_remaining_ms=cooldown_ms,
                )

            wallet = self.wallet_repo.find_by_user_id(user_id)
            if not wallet:
                raise NotFoundError("Wallet for user", user_id)

            balance_dec = Decimal(str(wallet["withdrawable_balance"]))
            if balance_dec < amt_dec:
                raise InsufficientBalanceError(
                    f"Insufficient balance. Available: ₹{balance_dec:.2f}, Requested: ₹{amt_dec:.2f}"
                )

            payout = self.payout_repo.create(
                user_id=user_id,
                payout_type="withdrawal",
                amount=amt_dec,
                status="processing",
                notes={"method": "bank_transfer"},
            )

            updated_wallet = self.wallet_repo.debit(user_id, amt_dec)
            now_iso = datetime.now(timezone.utc).isoformat()
            self.wallet_repo.set_last_withdrawal_at(user_id, now_iso)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return {
            "payout": payout,
            "wallet": updated_wallet,
            "message": f"Withdrawal of ₹{float(amt_dec):.2f} initiated. Transfer is processing.",
        }
