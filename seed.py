import os
import json
from decimal import Decimal
from app.db.database import get_db_connection, init_db
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.advance_service import AdvancePayoutService
from app.services.reconciliation_service import ReconciliationService
from app.services.final_payout_service import FinalPayoutService
from app.services.withdrawal_service import WithdrawalService
from app.services.recovery_service import PayoutRecoveryService

def p(msg: str):
    s = str(msg).replace("₹", "INR ").replace("−", "-")
    print(s.encode("ascii", errors="replace").decode("ascii"))

def run_seed():
    db_path = "payouts.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        p(f"Removed existing database '{db_path}'.")

    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        p("Initialized database schema.")

        user_repo = UserRepository(conn)
        wallet_repo = WalletRepository(conn)
        sale_repo = SaleRepository(conn)
        payout_repo = PayoutRepository(conn)

        advance_service = AdvancePayoutService(conn, user_repo, sale_repo, wallet_repo, payout_repo)
        reconcile_service = ReconciliationService(conn, sale_repo)
        final_service = FinalPayoutService(conn, user_repo, sale_repo, wallet_repo, payout_repo)
        withdrawal_service = WithdrawalService(conn, user_repo, wallet_repo, payout_repo)
        recovery_service = PayoutRecoveryService(conn, payout_repo, wallet_repo, sale_repo)

        p("\n--- 1. Creating User 'john_doe' ---")
        user = user_repo.create(name="John Doe", email="john@example.com", user_id="john_doe")
        wallet = wallet_repo.create(user_id="john_doe")
        p(f"User created: {user['id']} | Wallet balance: INR {wallet['withdrawable_balance']}")

        p("\n--- 2. Creating 3 Pending Sales (INR 40 each) ---")
        s1 = sale_repo.create(user_id="john_doe", brand="brand_1", earning=Decimal("40.00"))
        s2 = sale_repo.create(user_id="john_doe", brand="brand_1", earning=Decimal("40.00"))
        s3 = sale_repo.create(user_id="john_doe", brand="brand_1", earning=Decimal("40.00"))
        p(f"Sales created: {s1['id']}, {s2['id']}, {s3['id']}")

        p("\n--- 3. Running Advance Payout Job ---")
        adv_result = advance_service.process_advance("john_doe")
        p(f"Message: {adv_result['message']}")
        wallet_after_adv = wallet_repo.find_by_user_id("john_doe")
        p(f"Wallet balance after advance: INR {wallet_after_adv['withdrawable_balance']}")

        p("\n--- 4. Admin Batch Reconciling Sales ---")
        reconcile_batch = [
            {"saleId": s1["id"], "status": "rejected"},
            {"saleId": s2["id"], "status": "approved"},
            {"saleId": s3["id"], "status": "approved"},
        ]
        rec_result = reconcile_service.reconcile_batch(reconcile_batch)
        p(f"Batch reconciled: {rec_result['succeeded']} succeeded, {rec_result['failed']} failed.")

        p("\n--- 5. Running Final Payout Job ---")
        final_result = final_service.process_final_payout("john_doe")
        p(f"Message: {final_result['message']}")
        for b in final_result["breakdown"]:
            p(f"  - Sale {b['sale']['id']}: {b['reason']}")
        wallet_after_final = wallet_repo.find_by_user_id("john_doe")
        p(f"Wallet balance after final payout: INR {wallet_after_final['withdrawable_balance']}")

        p("\n--- 6. Initiating Withdrawal of INR 50 ---")
        w_result = withdrawal_service.initiate_withdrawal("john_doe", Decimal("50.00"))
        p(f"Message: {w_result['message']}")
        p(f"Withdrawal Payout ID: {w_result['payout']['id']} (status: {w_result['payout']['status']})")
        p(f"Wallet balance after withdrawal: INR {w_result['wallet']['withdrawable_balance']}")

        p("\n--- 7. Simulating Bank Failure & Recovery ---")
        recov_result = recovery_service.update_payout_status(
            w_result["payout"]["id"], "failed", reason="Bank transfer rejected by destination bank"
        )
        p(f"Message: {recov_result['message']}")
        p(f"Wallet balance after recovery: INR {recov_result['wallet']['withdrawable_balance']}")
        p(f"Last withdrawal at: {recov_result['wallet']['last_withdrawal_at']} (cooldown reset!)")

        p("\n=== SUCCESS: Full Assignment Seed Scenario Completed Perfectly! ===")

    finally:
        conn.close()

if __name__ == "__main__":
    run_seed()
