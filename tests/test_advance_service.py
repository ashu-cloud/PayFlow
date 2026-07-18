import pytest
from decimal import Decimal
from sqlite3 import Connection

from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.advance_service import AdvancePayoutService

def test_advance_credits_10_percent_of_pending_earnings(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Alice", "alice@example.com", "alice")
    wallet_repo.create("alice")
    sale_repo.create("alice", "brand_1", Decimal("100.00"))

    service = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo)
    res = service.process_advance("alice")

    assert res["total_advance"] == 10.0
    assert res["payout"]["status"] == "completed"
    wallet = wallet_repo.find_by_user_id("alice")
    assert wallet["withdrawable_balance"] == 10.0

def test_advance_is_idempotent_second_run_is_noop(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Bob", "bob@example.com", "bob")
    wallet_repo.create("bob")
    sale_repo.create("bob", "brand_1", Decimal("100.00"))

    service = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo)
    service.process_advance("bob")

    # Second call
    res2 = service.process_advance("bob")
    assert res2["payout"] is None
    assert res2["total_advance"] == 0.0
    assert wallet_repo.find_by_user_id("bob")["withdrawable_balance"] == 10.0

def test_advance_skips_sales_with_no_eligible_pending(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Charlie", "charlie@example.com", "charlie")
    wallet_repo.create("charlie")

    service = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo)
    res = service.process_advance("charlie")
    assert res["payout"] is None
    assert res["total_advance"] == 0.0

def test_advance_marks_sales_with_payout_id(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Dave", "dave@example.com", "dave")
    wallet_repo.create("dave")
    s = sale_repo.create("dave", "brand_1", Decimal("50.00"))

    service = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo)
    res = service.process_advance("dave")
    payout_id = res["payout"]["id"]

    updated_sale = sale_repo.find_by_id(s["id"])
    assert updated_sale["advance_payout_id"] == payout_id
    assert updated_sale["advance_paid"] == 5.0

def test_advance_assignment_example(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("John", "john@example.com", "john_doe")
    wallet_repo.create("john_doe")
    for _ in range(3):
        sale_repo.create("john_doe", "brand_1", Decimal("40.00"))

    service = AdvancePayoutService(db_conn, user_repo, sale_repo, wallet_repo, payout_repo)
    res = service.process_advance("john_doe")
    assert res["total_advance"] == 12.0
    assert wallet_repo.find_by_user_id("john_doe")["withdrawable_balance"] == 12.0
