import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlite3 import Connection

from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.advance_service import AdvancePayoutService
from app.services.withdrawal_service import WithdrawalService
from app.services.recovery_service import PayoutRecoveryService
from app.utils.errors import ConflictError

def test_full_assignment_happy_path(client: TestClient):
    # 1. Create User
    user_res = client.post("/api/users", json={"name": "John Doe", "email": "john@example.com", "id": "john_doe"})
    assert user_res.status_code == 201
    assert user_res.json()["data"]["wallet"]["withdrawable_balance"] == 0

    # 2. Create 3 sales @ ₹40 each
    for _ in range(3):
        s_res = client.post("/api/sales", json={"userId": "john_doe", "brand": "brand_1", "earning": 40})
        assert s_res.status_code == 201
        assert s_res.json()["data"]["status"] == "pending"

    # 3. Advance Payout -> 10% of ₹120 = ₹12 credited
    adv_res = client.post("/api/payouts/advance/john_doe")
    assert adv_res.status_code == 200
    assert adv_res.json()["data"]["total_advance"] == 12.0
    assert adv_res.json()["data"]["payout"]["status"] == "completed"

    w_res = client.get("/api/wallet/john_doe")
    assert w_res.json()["data"]["withdrawable_balance"] == 12.0

    # 4. Advance Payout Idempotency -> calling again returns no-op (0 sales eligible)
    adv_res_2 = client.post("/api/payouts/advance/john_doe")
    assert adv_res_2.status_code == 200
    assert adv_res_2.json()["data"]["payout"] is None
    assert adv_res_2.json()["data"]["total_advance"] == 0.0

    # 5. Batch Reconcile -> Sale 1 rejected, Sales 2 & 3 approved
    sales = client.get("/api/sales?userId=john_doe").json()["data"]
    reconcile_payload = {
        "reconciliations": [
            {"saleId": sales[0]["id"], "status": "rejected"},
            {"saleId": sales[1]["id"], "status": "approved"},
            {"saleId": sales[2]["id"], "status": "approved"},
        ]
    }
    rec_res = client.post("/api/sales/reconcile", json=reconcile_payload)
    assert rec_res.status_code == 200
    assert rec_res.json()["data"]["succeeded"] == 3

    # 6. Final Payout -> -₹4 + ₹36 + ₹36 = ₹68 credited -> Balance becomes ₹80
    final_res = client.post("/api/payouts/final/john_doe")
    assert final_res.status_code == 200
    assert final_res.json()["data"]["total_final"] == 68.0

    w_res_2 = client.get("/api/wallet/john_doe")
    assert w_res_2.json()["data"]["withdrawable_balance"] == 80.0

    # 7. Initiate Withdrawal of ₹50 -> Balance becomes ₹30, payout status processing
    with_res = client.post("/api/wallet/john_doe/withdraw", json={"amount": 50})
    assert with_res.status_code == 200
    payout_id = with_res.json()["data"]["payout"]["id"]
    assert with_res.json()["data"]["payout"]["status"] == "processing"
    assert with_res.json()["data"]["wallet"]["withdrawable_balance"] == 30.0

    # 8. Attempt Second Withdrawal immediately -> Rate Limited (24h cooldown)
    with_res_2 = client.post("/api/wallet/john_doe/withdraw", json={"amount": 10})
    assert with_res_2.status_code == 429
    assert with_res_2.json()["error"]["code"] == "RATE_LIMITED"

    # 9. Bank Failure Simulation -> Recovery credits ₹50 back, balance becomes ₹80, cooldown reset
    patch_res = client.patch(f"/api/payouts/{payout_id}/status", json={"status": "failed", "reason": "Bank rejected"})
    assert patch_res.status_code == 200
    assert patch_res.json()["data"]["wallet"]["withdrawable_balance"] == 80.0
    assert patch_res.json()["data"]["wallet"]["last_withdrawal_at"] is None

    # 10. Re-withdrawal after cooldown reset -> Succeeds!
    with_res_3 = client.post("/api/wallet/john_doe/withdraw", json={"amount": 50})
    assert with_res_3.status_code == 200
    assert with_res_3.json()["data"]["wallet"]["withdrawable_balance"] == 30.0

def test_insufficient_balance_withdrawal(client: TestClient):
    client.post("/api/users", json={"name": "Alice", "email": "alice@example.com", "id": "alice"})
    res = client.post("/api/wallet/alice/withdraw", json={"amount": 100})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INSUFFICIENT_BALANCE"

def test_batch_reconcile_savepoint_partial_success(client: TestClient):
    client.post("/api/users", json={"name": "Bob", "email": "bob@example.com", "id": "bob"})
    s1 = client.post("/api/sales", json={"userId": "bob", "brand": "brand_1", "earning": 50}).json()["data"]

    client.post("/api/sales/reconcile", json={"reconciliations": [{"saleId": s1["id"], "status": "approved"}]})

    s2 = client.post("/api/sales", json={"userId": "bob", "brand": "brand_2", "earning": 100}).json()["data"]

    batch_res = client.post(
        "/api/sales/reconcile",
        json={
            "reconciliations": [
                {"saleId": s1["id"], "status": "rejected"},
                {"saleId": s2["id"], "status": "approved"},
            ],
            "rollbackOnError": False,
        },
    )
    assert batch_res.status_code == 200
    data = batch_res.json()["data"]
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert data["results"][0]["saleId"] == s2["id"]
