from fastapi import status
from typing import Optional, Dict, Any

class AppError(Exception):
    """Base exception for all domain operational errors."""
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: Optional[str] = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}

class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: Optional[str] = None):
        msg = f"{resource} '{identifier}' not found." if identifier else f"{resource} not found."
        super().__init__(
            message=msg,
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
        )

class ConflictError(AppError):
    def __init__(self, message: str, code: str = "CONFLICT"):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code=code,
        )

class ValidationError(AppError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
        )

class InsufficientBalanceError(AppError):
    def __init__(self, message: str = "Insufficient withdrawable balance."):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INSUFFICIENT_BALANCE",
        )

class RateLimitError(AppError):
    def __init__(self, message: str, cooldown_remaining_ms: int = 0):
        super().__init__(
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMITED",
            details={"cooldown_remaining_ms": cooldown_remaining_ms},
        )
