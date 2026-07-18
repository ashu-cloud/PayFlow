from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from decimal import Decimal

class CreateUserRequest(BaseModel):
    name: str = Field(..., min_length=1, description="User full name")
    email: str = Field(..., description="User email address")
    id: Optional[str] = Field(None, description="Optional custom user ID")

class CreateSaleRequest(BaseModel):
    userId: str = Field(..., description="ID of the user who made the sale")
    brand: Literal["brand_1", "brand_2", "brand_3"] = Field(..., description="Brand identifier")
    earning: Decimal = Field(..., gt=0, description="Gross earning amount for the sale")

class ReconciliationItem(BaseModel):
    saleId: str = Field(..., description="ID of the sale to reconcile")
    status: Literal["approved", "rejected"] = Field(..., description="Reconciliation decision")

class ReconcileBatchRequest(BaseModel):
    reconciliations: List[ReconciliationItem] = Field(..., min_items=1)
    rollbackOnError: bool = Field(False, description="Whether to rollback all if any item fails")

class WithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Amount to withdraw")

class UpdatePayoutStatusRequest(BaseModel):
    status: Literal["completed", "failed", "cancelled", "rejected"] = Field(..., description="New payout status")
    reason: Optional[str] = Field("", description="Optional reason for status update or failure")
