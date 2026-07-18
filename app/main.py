from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from app.db.database import get_db_connection, init_db
from app.routes import users, sales, payouts, wallet
from app.utils.errors import AppError

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_db_connection()
    try:
        init_db(conn)
    finally:
        conn.close()
    yield

app = FastAPI(
    title="Affiliate Payout Management System",
    description="Production-grade API for managing affiliate sales payouts, advance disbursement, final payout reconciliation, rate-limited withdrawals, and failed payout recovery.",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount Routers
app.include_router(users.router)
app.include_router(sales.router)
app.include_router(payouts.router)
app.include_router(wallet.router)

# Custom Exception Handler for AppError
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    error_content = {
        "message": exc.message,
        "code": exc.code,
    }
    if exc.details:
        error_content.update(exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": error_content},
    )

# Handler for Pydantic Request Validation Errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    msg = f"Validation Error: {first_error.get('msg', 'Invalid request parameters')}"
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error": {
                "message": msg,
                "code": "VALIDATION_ERROR",
                "details": errors,
            },
        },
    )

# Fallback Handler for Unexpected Exceptions
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "message": "Internal Server Error",
                "code": "INTERNAL_ERROR",
            },
        },
    )

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "Affiliate Payout Management System"}
