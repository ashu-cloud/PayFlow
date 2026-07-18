import pytest
from decimal import Decimal
from sqlite3 import Connection

from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.services.reconciliation_service import ReconciliationService
from app.utils.errors import NotFoundError, ConflictError

def test_reconcile_pending_to_approved(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    user_repo.create("Alice", "alice@example.com", "alice")
    s = sale_repo.create("alice", "brand_1", Decimal("100.00"))

    service = ReconciliationService(db_conn, sale_repo)
    updated = service.reconcile_sale(s["id"], "approved")
    assert updated["status"] == "approved"
    assert updated["reconciled_at"] is not None

def test_reconcile_pending_to_rejected(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    user_repo.create("Bob", "bob@example.com", "bob")
    s = sale_repo.create("bob", "brand_1", Decimal("100.00"))

    service = ReconciliationService(db_conn, sale_repo)
    updated = service.reconcile_sale(s["id"], "rejected")
    assert updated["status"] == "rejected"

def test_reconcile_already_approved_raises_409(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    user_repo.create("Charlie", "charlie@example.com", "charlie")
    s = sale_repo.create("charlie", "brand_1", Decimal("100.00"))

    service = ReconciliationService(db_conn, sale_repo)
    service.reconcile_sale(s["id"], "approved")

    with pytest.raises(ConflictError):
        service.reconcile_sale(s["id"], "rejected")

def test_reconcile_unknown_sale_raises_404(db_conn: Connection):
    sale_repo = SaleRepository(db_conn)
    service = ReconciliationService(db_conn, sale_repo)
    with pytest.raises(NotFoundError):
        service.reconcile_sale("unknown_id", "approved")

def test_reconcile_batch_partial_success(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    user_repo.create("Dave", "dave@example.com", "dave")
    s1 = sale_repo.create("dave", "brand_1", Decimal("50.00"))
    s2 = sale_repo.create("dave", "brand_2", Decimal("100.00"))

    service = ReconciliationService(db_conn, sale_repo)
    service.reconcile_sale(s1["id"], "approved")

    batch = [
        {"saleId": s1["id"], "status": "rejected"}, # Should fail
        {"saleId": s2["id"], "status": "approved"}, # Should succeed
    ]
    res = service.reconcile_batch(batch, rollback_on_error=False)
    assert res["succeeded"] == 1
    assert res["failed"] == 1
    assert res["results"][0]["saleId"] == s2["id"]

def test_reconcile_batch_rollback_on_error(db_conn: Connection):
    user_repo = UserRepository(db_conn)
    sale_repo = SaleRepository(db_conn)
    user_repo.create("Eve", "eve@example.com", "eve")
    s1 = sale_repo.create("eve", "brand_1", Decimal("50.00"))

    service = ReconciliationService(db_conn, sale_repo)
    batch = [
        {"saleId": s1["id"], "status": "approved"},
        {"saleId": "non_existent_id", "status": "approved"},
    ]
    with pytest.raises(NotFoundError):
        service.reconcile_batch(batch, rollback_on_error=True)

    # Verify s1 was rolled back and remains pending
    assert sale_repo.find_by_id(s1["id"])["status"] == "pending"
