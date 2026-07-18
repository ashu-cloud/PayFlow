from fastapi import APIRouter, Depends
from sqlite3 import Connection

from app.db.database import get_db_connection
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.withdrawal_service import WithdrawalService
from app.models.requests import WithdrawRequest
from app.models.responses import success_response
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/api/wallet", tags=["Wallet"])

@router.get("/{user_id}")
def get_wallet(user_id: str, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    wallet_repo = WalletRepository(conn)
    payout_repo = PayoutRepository(conn)

    if not user_repo.exists_by_id(user_id):
        raise NotFoundError("User", user_id)

    wallet = wallet_repo.find_by_user_id(user_id)
    if not wallet:
        raise NotFoundError("Wallet for user", user_id)

    service = WithdrawalService(conn, user_repo, wallet_repo, payout_repo)
    cooldown_ms = service.get_cooldown_remaining_ms(user_id)

    wallet_dict = dict(wallet)
    balance = float(wallet_dict.get("withdrawable_balance", 0.0))
    wallet_dict["withdrawal_eligible"] = balance > 0 and cooldown_ms == 0
    wallet_dict["cooldown_remaining_ms"] = cooldown_ms

    return success_response(wallet_dict)

@router.post("/{user_id}/withdraw")
def withdraw(user_id: str, req: WithdrawRequest, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    wallet_repo = WalletRepository(conn)
    payout_repo = PayoutRepository(conn)

    service = WithdrawalService(conn, user_repo, wallet_repo, payout_repo)
    result = service.initiate_withdrawal(user_id, req.amount)
    return success_response(result)
