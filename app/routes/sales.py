from fastapi import APIRouter, Depends, Query
from sqlite3 import Connection
from typing import Optional

from app.db.database import get_db_connection
from app.repositories.user_repository import UserRepository
from app.repositories.sale_repository import SaleRepository
from app.services.reconciliation_service import ReconciliationService
from app.models.requests import CreateSaleRequest, ReconcileBatchRequest
from app.models.responses import success_response
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/api/sales", tags=["Sales"])

@router.post("", status_code=201)
def create_sale(req: CreateSaleRequest, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    sale_repo = SaleRepository(conn)

    if not user_repo.exists_by_id(req.userId):
        raise NotFoundError("User", req.userId)

    sale = sale_repo.create(user_id=req.userId, brand=req.brand, earning=req.earning)
    return success_response(sale, status_code=201)

@router.get("")
def list_sales(userId: Optional[str] = Query(None), conn: Connection = Depends(get_db_connection)):
    sale_repo = SaleRepository(conn)
    if userId:
        sales = sale_repo.find_by_user_id(userId)
    else:
        sales = sale_repo.find_all()
    return success_response(sales)

@router.get("/{sale_id}")
def get_sale(sale_id: str, conn: Connection = Depends(get_db_connection)):
    sale_repo = SaleRepository(conn)
    sale = sale_repo.find_by_id(sale_id)
    if not sale:
        raise NotFoundError("Sale", sale_id)
    return success_response(sale)

@router.post("/reconcile")
def reconcile_sales(req: ReconcileBatchRequest, conn: Connection = Depends(get_db_connection)):
    sale_repo = SaleRepository(conn)
    service = ReconciliationService(conn, sale_repo)

    reconcile_items = [item.model_dump() for item in req.reconciliations]
    result = service.reconcile_batch(reconcile_items, rollback_on_error=req.rollbackOnError)
    return success_response(result)
