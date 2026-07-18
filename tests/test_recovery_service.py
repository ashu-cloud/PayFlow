import pytest
from decimal import Decimal
from sqlite3 import Connection

from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.advance_service import AdvancePayoutService
from app.services.withdrawal_service import WithdrawalService
from app.services.recovery_service import PayoutRecoveryService
from app.utils.errors import ConflictError

def test_withdrawal_recovery_credits_wallet_back(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Alice", "alice@example.com", "alice")
    wallet_repo.create("alice")
    wallet_repo.credit("alice", Decimal("100.00"))

    w_res = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo).initiate_withdrawal("alice", Decimal("50.00"))
    payout_id = w_res["payout"]["id"]

    rec_service = PayoutRecoveryService(db_conn, payout_repo, wallet_repo, sale_repo)
    res = rec_service.update_payout_status(payout_id, "failed", "Bank transfer rejected")

    assert res["wallet"]["withdrawable_balance"] == 100.0

def test_withdrawal_recovery_resets_cooldown(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Bob", "bob@example.com", "bob")
    wallet_repo.create("bob")
    wallet_repo.credit("bob", Decimal("100.00"))

    w_res = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo).initiate_withdrawal("bob", Decimal("50.00"))
    payout_id = w_res["payout"]["id"]

    rec_service = PayoutRecoveryService(db_conn, payout_repo, wallet_repo, sale_repo)
    res = rec_service.update_payout_status(payout_id, "cancelled", "User cancelled")

    assert res["wallet"]["last_withdrawal_at"] is None

def test_advance_recovery_debits_wallet_and_resets_sales(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Charlie", "charlie@example.com", "charlie")
    wallet_repo.create("charlie")
    s = sale_repo.create("charlie", "brand_1", Decimal("100.00"))

    adv_res = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("charlie")
    payout_id = adv_res["payout"]["id"]

    # Set status to processing before recovery
    payout_repo.update_status(payout_id, "processing")

    rec_service = PayoutRecoveryService(db_conn, payout_repo, wallet_repo, sale_repo)
    res = rec_service.update_payout_status(payout_id, "failed", "Gateway down")

    assert res["wallet"]["withdrawable_balance"] == 0.0
    updated_sale = sale_repo.find_by_id(s["id"])
    assert updated_sale["advance_payout_id"] is None
    assert updated_sale["advance_paid"] == 0.0

def test_double_recovery_raises_409(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Dave", "dave@example.com", "dave")
    wallet_repo.create("dave")
    wallet_repo.credit("dave", Decimal("100.00"))

    w_res = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo).initiate_withdrawal("dave", Decimal("50.00"))
    payout_id = w_res["payout"]["id"]

    rec_service = PayoutRecoveryService(db_conn, payout_repo, wallet_repo, sale_repo)
    rec_service.update_payout_status(payout_id, "failed", "First failure")

    with pytest.raises(ConflictError):
        rec_service.recover_payout(payout_id, "failed", "Second failure")

def test_recovery_of_completed_payout_raises_409(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Eve", "eve@example.com", "eve")
    wallet_repo.create("eve")
    s = sale_repo.create("eve", "brand_1", Decimal("100.00"))

    adv_res = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("eve")
    payout_id = adv_res["payout"]["id"] # Already completed

    rec_service = PayoutRecoveryService(db_conn, payout_repo, wallet_repo, sale_repo)
    with pytest.raises(ConflictError):
        rec_service.recover_payout(payout_id, "failed", "Attempt recover completed")

def test_patch_status_on_non_processing_payout_raises_409(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Frank", "frank@example.com", "frank")
    wallet_repo.create("frank")
    s = sale_repo.create("frank", "brand_1", Decimal("100.00"))

    adv_res = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo).process_advance("frank")
    payout_id = adv_res["payout"]["id"] # Status: completed

    rec_service = PayoutRecoveryService(db_conn, payout_repo, wallet_repo, sale_repo)
    with pytest.raises(ConflictError):
        rec_service.update_payout_status(payout_id, "failed", "Invalid update")
