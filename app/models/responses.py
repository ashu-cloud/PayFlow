from typing import Any, Optional, Dict
from fastapi.responses import JSONResponse

def success_response(data: Any, status_code: int = 200) -> JSONResponse:
    """Returns a standardized JSON success response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"success": True, "data": data},
    )

def error_response(message: str, code: str = "ERROR", details: Optional[Dict[str, Any]] = None, status_code: int = 400) -> JSONResponse:
    """Returns a standardized JSON error response envelope."""
    content: Dict[str, Any] = {
        "success": False,
        "error": {
            "message": message,
            "code": code,
        },
    }
    if details:
        content["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=content)
