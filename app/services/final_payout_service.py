import sqlite3
from typing import Dict, Any
from decimal import Decimal

from app.repositories.user_repository import UserRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.payout_repository import PayoutRepository
from app.utils.financial import calc_final_for_sale, sum_amounts
from app.utils.errors import NotFoundError

class FinalPayoutService:
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

    def process_final_payout(self, user_id: str) -> Dict[str, Any]:
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        eligible_sales = self.sale_repo.find_eligible_for_final_payout(user_id)
        if not eligible_sales:
            return {
                "payout": None,
                "breakdown": [],
                "total_final": 0.0,
                "message": "No reconciled sales eligible for final payout.",
            }

        breakdown = []
        contributions = []
        for s in eligible_sales:
            final_amt = calc_final_for_sale(s["status"], s["earning"], s["advance_paid"])
            contributions.append(final_amt)
            
            if s["status"] == "approved":
                reason = f"Approved: ₹{s['earning']:.2f} − ₹{s['advance_paid']:.2f} advance = ₹{float(final_amt):.2f}"
            else:
                reason = f"Rejected: clawback of ₹{s['advance_paid']:.2f} advance = ₹{float(final_amt):.2f}"
                
            breakdown.append({
                "sale": s,
                "final_amount": float(final_amt),
                "reason": reason,
            })

        total_final = sum_amounts(contributions)

        self.conn.execute("BEGIN")
        try:
            payout = self.payout_repo.create(
                user_id=user_id,
                payout_type="final",
                amount=total_final,
                status="initiated",
                notes={"sales_count": len(eligible_sales)},
            )

            for item in breakdown:
                s = item["sale"]
                final_amt = Decimal(str(item["final_amount"]))
                self.sale_repo.mark_final_paid(s["id"], payout["id"])
                self.payout_repo.add_sale_mapping(payout["id"], s["id"], final_amt)

            # Adjust wallet balance cleanly
            if total_final > 0:
                self.wallet_repo.credit(user_id, total_final)
            elif total_final < 0:
                self.wallet_repo.debit(user_id, abs(total_final))

            completed_payout = self.payout_repo.update_status(payout["id"], "completed")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        action_msg = "credited to" if total_final >= 0 else "debited from (clawback)"
        return {
            "payout": completed_payout,
            "total_final": float(total_final),
            "breakdown": breakdown,
            "message": f"Final payout processed. ₹{abs(float(total_final)):.2f} {action_msg} wallet.",
        }
