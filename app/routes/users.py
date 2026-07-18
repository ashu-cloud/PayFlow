from fastapi import APIRouter, Depends
from sqlite3 import Connection
from typing import Optional

from app.db.database import get_db_connection
from app.repositories.user_repository import UserRepository
from app.repositories.wallet_repository import WalletRepository
from app.models.requests import CreateUserRequest
from app.models.responses import success_response
from app.utils.errors import NotFoundError, ConflictError

router = APIRouter(prefix="/api/users", tags=["Users"])

@router.post("", status_code=201)
def create_user(req: CreateUserRequest, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    wallet_repo = WalletRepository(conn)

    existing = user_repo.find_by_email(req.email)
    if existing:
        raise ConflictError(f"User with email '{req.email}' already exists.", code="USER_ALREADY_EXISTS")

    user = user_repo.create(name=req.name, email=req.email, user_id=req.id)
    wallet = wallet_repo.create(user_id=user["id"])

    user_data = dict(user)
    user_data["wallet"] = wallet
    return success_response(user_data, status_code=201)

@router.get("")
def list_users(conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    wallet_repo = WalletRepository(conn)
    
    users = user_repo.find_all()
    res = []
    for u in users:
        u_dict = dict(u)
        u_dict["wallet"] = wallet_repo.find_by_user_id(u["id"])
        res.append(u_dict)
    return success_response(res)

@router.get("/{user_id}")
def get_user(user_id: str, conn: Connection = Depends(get_db_connection)):
    user_repo = UserRepository(conn)
    wallet_repo = WalletRepository(conn)

    user = user_repo.find_by_id(user_id)
    if not user:
        raise NotFoundError("User", user_id)

    user_data = dict(user)
    user_data["wallet"] = wallet_repo.find_by_user_id(user_id)
    return success_response(user_data)
