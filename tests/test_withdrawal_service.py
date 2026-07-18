import pytest
from decimal import Decimal
from sqlite3 import Connection

from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.withdrawal_service import WithdrawalService
from app.utils.errors import ValidationError, InsufficientBalanceError, RateLimitError

def test_withdrawal_debits_wallet(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Alice", "alice@example.com", "alice")
    wallet_repo.create("alice")
    wallet_repo.credit("alice", Decimal("100.00"))

    service = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo)
    res = service.initiate_withdrawal("alice", Decimal("40.00"))

    assert res["wallet"]["withdrawable_balance"] == 60.0

def test_withdrawal_creates_processing_payout(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Bob", "bob@example.com", "bob")
    wallet_repo.create("bob")
    wallet_repo.credit("bob", Decimal("100.00"))

    service = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo)
    res = service.initiate_withdrawal("bob", Decimal("50.00"))

    assert res["payout"]["status"] == "processing"
    assert res["payout"]["type"] == "withdrawal"

def test_withdrawal_rejects_if_insufficient_balance(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Charlie", "charlie@example.com", "charlie")
    wallet_repo.create("charlie")

    service = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo)
    with pytest.raises(InsufficientBalanceError):
        service.initiate_withdrawal("charlie", Decimal("50.00"))

def test_withdrawal_rejects_within_24hr_cooldown(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Dave", "dave@example.com", "dave")
    wallet_repo.create("dave")
    wallet_repo.credit("dave", Decimal("100.00"))

    service = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo)
    service.initiate_withdrawal("dave", Decimal("30.00"))

    with pytest.raises(RateLimitError):
        service.initiate_withdrawal("dave", Decimal("20.00"))

def test_withdrawal_allows_after_24hr_cooldown(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Eve", "eve@example.com", "eve")
    wallet_repo.create("eve")
    wallet_repo.credit("eve", Decimal("100.00"))

    service = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo)
    service.initiate_withdrawal("eve", Decimal("30.00"))

    # Reset last_withdrawal_at manually to simulate 24hr elapsed
    wallet_repo.set_last_withdrawal_at("eve", None)

    res = service.initiate_withdrawal("eve", Decimal("20.00"))
    assert res["wallet"]["withdrawable_balance"] == 50.0

def test_withdrawal_rejects_zero_amount(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    wallet_repo = WalletRepository(db_conn)
    payout_repo = PayoutRepository(db_conn)

    user_repo.create("Frank", "frank@example.com", "frank")
    wallet_repo.create("frank")
    wallet_repo.credit("frank", Decimal("100.00"))

    service = WithdrawalService(db_conn, user_repo, wallet_repo, payout_repo)
    with pytest.raises(ValidationError):
        service.initiate_withdrawal("frank", Decimal("0.00"))
