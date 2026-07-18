from fastapi import APIRouter, Depends, Query
from sqlite3 import Connection
from typing import Optional

from app.db.database import get_db_connection
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.repositories.sale_repository import SaleRepository
from app.repositories.payout_repository import PayoutRepository
from app.services.advance_service import AdvancePayoutService
from app.services.final_payout_service import FinalPayoutService
from app.services.recovery_service import PayoutRecoveryService
from app.models.requests import UpdatePayoutStatusRequest
from app.models.responses import success_response
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/api/payouts", tags=["Payouts"])

@router.post("/advance/{user_id}")
def process_advance_payout(user_id: str, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    sale_repo = SaleRepository(conn)
    wallet_repo = WalletRepository(conn)
    payout_repo = PayoutRepository(conn)

    service = AdvancePayoutService(conn, user_repo, sale_repo, wallet_repo, payout_repo)
    result = service.process_advance(user_id)
    return success_response(result)

@router.post("/final/{user_id}")
def process_final_payout(user_id: str, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    sale_repo = SaleRepository(conn)
    wallet_repo = WalletRepository(conn)
    payout_repo = PayoutRepository(conn)

    service = FinalPayoutService(conn, user_repo, sale_repo, wallet_repo, payout_repo)
    result = service.process_final_payout(user_id)
    return success_response(result)

@router.get("")
def list_payouts(userId: Optional[str] = Query(None), conn: Connection = Depends(get_db_connection)):
    payout_repo = PayoutRepository(conn)
    if userId:
        payouts = payout_repo.find_by_user_id(userId)
    else:
        payouts = payout_repo.find_all()
    return success_response(payouts)

@router.get("/{payout_id}")
def get_payout(payout_id: str, conn: Connection = Depends(get_db_connection)):
    payout_repo = PayoutRepository(conn)
    payout = payout_repo.find_by_id(payout_id)
    if not payout:
        raise NotFoundError("Payout", payout_id)

    p_dict = dict(payout)
    p_dict["sale_mappings"] = payout_repo.get_sale_mappings(payout_id)
    return success_response(p_dict)

@router.patch("/{payout_id}/status")
def update_payout_status(payout_id: str, req: UpdatePayoutStatusRequest, conn: Connection = Depends(get_db_connection)):
    payout_repo = PayoutRepository(conn)
    wallet_repo = WalletRepository(conn)
    sale_repo = SaleRepository(conn)

    service = PayoutRecoveryService(conn, payout_repo, wallet_repo, sale_repo)
    result = service.update_payout_status(payout_id, req.status, req.reason)
    return success_response(result)
