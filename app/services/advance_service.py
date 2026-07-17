import sqlite3
from typing import Dict, Any
from decimal import Decimal

from app.repositories.user_repository import UserRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.payout_repository import PayoutRepository
from app.utils.financial import calc_advance, sum_amounts
from app.utils.errors import NotFoundError

class AdvancePayoutService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_repo: UserRepository,
        sale_repo: SaleRepository,
        wallet_repo: WalletRepository,
        payout_repo: PayoutRepository,
    ):
        self.conn = conn
        self.user_repo = user_repo
        self.sale_repo = sale_repo
        self.wallet_repo = wallet_repo
        self.payout_repo = payout_repo

    def process_advance(self, user_id: str) -> Dict[str, Any]:
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        eligible_sales = self.sale_repo.find_eligible_for_advance(user_id)
        if not eligible_sales:
            return {
                "payout": None,
                "eligible_sales": [],
                "total_advance": 0.0,
                "message": "No eligible pending sales found for advance payout.",
            }

        sales_breakdown = []
        advances = []
        for s in eligible_sales:
            adv = calc_advance(s["earning"])
            advances.append(adv)
            sales_breakdown.append({"sale": s, "advance": adv})

        total_advance = sum_amounts(advances)

        self.conn.execute("BEGIN")
        try:
            payout = self.payout_repo.create(
                user_id=user_id,
                payout_type="advance",
                amount=total_advance,
                status="initiated",
                notes={"sales_count": len(eligible_sales)},
            )

            processed_count = 0
            actual_advances = []
            for item in sales_breakdown:
                s = item["sale"]
                adv = item["advance"]
                updated_rows = self.sale_repo.mark_advance_paid(s["id"], payout["id"], adv)
                if updated_rows > 0:
                    self.payout_repo.add_sale_mapping(payout["id"], s["id"], adv)
                    processed_count += 1
                    actual_advances.append(adv)

            if processed_count == 0:
                raise Exception("Concurrent modification: no sales were claimed for advance payout.")

            actual_total = sum_amounts(actual_advances)
            self.wallet_repo.credit(user_id, actual_total)
            completed_payout = self.payout_repo.update_status(payout["id"], "completed")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return {
            "payout": completed_payout,
            "eligible_sales": eligible_sales,
            "total_advance": float(actual_total),
            "message": f"Advance payout of ₹{float(actual_total):.2f} processed for {processed_count} sale(s).",
        }
