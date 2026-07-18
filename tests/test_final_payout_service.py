import pytest
from decimal import Decimal
from sqlite3 import Connection

from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.advance_service import AdvancePayoutService
from app.services.reconciliation_service import ReconciliationService
from app.services.final_payout_service import FinalPayoutService

def test_approved_sale_final_is_earning_minus_advance(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Alice", "alice@example.com", "alice")
    wallet_repo.create("alice")
    s = sale_repo.create("alice", "brand_1", Decimal("100.00"))

    AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("alice")
    ReconciliationService(db_conn, sale_repo).reconcile_sale(s["id"], "approved")

    res = FinalPayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_final_payout("alice")
    assert res["total_final"] == 90.0
    assert wallet_repo.find_by_user_id("alice")["withdrawable_balance"] == 100.0

def test_rejected_sale_final_is_negative_advance_clawback(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Bob", "bob@example.com", "bob")
    wallet_repo.create("bob")
    s = sale_repo.create("bob", "brand_1", Decimal("100.00"))

    AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("bob")
    ReconciliationService(db_conn, sale_repo).reconcile_sale(s["id"], "rejected")

    res = FinalPayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_final_payout("bob")
    assert res["total_final"] == -10.0
    assert wallet_repo.find_by_user_id("bob")["withdrawable_balance"] == 0.0

def test_assignment_example_total_is_68(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("John", "john@example.com", "john_doe")
    wallet_repo.create("john_doe")
    s1 = sale_repo.create("john_doe", "brand_1", Decimal("40.00"))
    s2 = sale_repo.create("john_doe", "brand_1", Decimal("40.00"))
    s3 = sale_repo.create("john_doe", "brand_1", Decimal("40.00"))

    AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("john_doe")
    rec_service = ReconciliationService(db_conn, sale_repo)
    rec_service.reconcile_sale(s1["id"], "rejected")
    rec_service.reconcile_sale(s2["id"], "approved")
    rec_service.reconcile_sale(s3["id"], "approved")

    res = FinalPayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_final_payout("john_doe")
    assert res["total_final"] == 68.0
    assert wallet_repo.find_by_user_id("john_doe")["withdrawable_balance"] == 80.0

def test_all_rejected_gives_negative_total_and_debits_wallet(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Dave", "dave@example.com", "dave")
    wallet_repo.create("dave")
    s1 = sale_repo.create("dave", "brand_1", Decimal("50.00"))

    AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("dave")
    ReconciliationService(db_conn, sale_repo).reconcile_sale(s1["id"], "rejected")

    res = FinalPayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_final_payout("dave")
    assert res["total_final"] == -5.0
    assert wallet_repo.find_by_user_id("dave")["withdrawable_balance"] == 0.0

def test_final_payout_is_idempotent(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Eve", "eve@example.com", "eve")
    wallet_repo.create("eve")
    s1 = sale_repo.create("eve", "brand_1", Decimal("50.00"))

    ReconciliationService(db_conn, sale_repo).reconcile_sale(s1["id"], "approved")

    final_service = FinalPayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo)
    final_service.process_final_payout("eve")

    # Second call
    res2 = final_service.process_final_payout("eve")
    assert res2["payout"] is None
    assert res2["total_final"] == 0.0

def test_sale_with_no_advance_gets_full_earning_when_approved(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Frank", "frank@example.com", "frank")
    wallet_repo.create("frank")
    s1 = sale_repo.create("frank", "brand_1", Decimal("50.00"))

    ReconciliationService(db_conn, sale_repo).reconcile_sale(s1["id"], "approved")

    res = FinalPayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_final_payout("frank")
    assert res["total_final"] == 50.0
    assert wallet_repo.find_by_user_id("frank")["withdrawable_balance"] == 50.0
