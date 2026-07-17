import sqlite3
from typing import List, Dict, Any, Optional
from app.repositories.sale_repository import SaleRepository
from app.utils.errors import ValidationError, NotFoundError, ConflictError

VALID_STATUSES = {"approved", "rejected"}

class ReconciliationService:
    def __init__(self, conn: sqlite3.Connection, sale_repo: SaleRepository):
        self.conn = conn
        self.sale_repo = sale_repo

    def reconcile_sale(self, sale_id: str, new_status: str) -> Dict[str, Any]:
        if new_status not in VALID_STATUSES:
            raise ValidationError(f"Invalid status '{new_status}'. Must be 'approved' or 'rejected'.")

        sale = self.sale_repo.find_by_id(sale_id)
        if not sale:
            raise NotFoundError("Sale", sale_id)

        if sale["status"] != "pending":
            raise ConflictError(
                f"Sale '{sale_id}' is already '{sale['status']}' and cannot be reconciled again.",
                code="SALE_ALREADY_RECONCILED",
            )

        updated_sale = self.sale_repo.reconcile(sale_id, new_status)
        if not updated_sale:
            raise ConflictError(f"Failed to reconcile sale '{sale_id}'. Concurrent conflict detected.")

        return updated_sale

    def reconcile_batch(
        self, reconciliations: List[Dict[str, str]], rollback_on_error: bool = False
    ) -> Dict[str, Any]:
        results = []
        errors = []

        if rollback_on_error:
            self.conn.execute("BEGIN")
            try:
                for item in reconciliations:
                    sale_id = item.get("saleId") or item.get("sale_id")
                    new_status = item.get("status")
                    updated_sale = self.reconcile_sale(sale_id, new_status)
                    results.append({
                        "saleId": sale_id,
                        "status": new_status,
                        "sale": updated_sale,
                    })
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        else:
            for item in reconciliations:
                sale_id = item.get("saleId") or item.get("sale_id")
                new_status = item.get("status")
                try:
                    self.conn.execute("BEGIN")
                    updated_sale = self.reconcile_sale(sale_id, new_status)
                    self.conn.commit()
                    results.append({
                        "saleId": sale_id,
                        "status": new_status,
                        "sale": updated_sale,
                    })
                except Exception as err:
                    self.conn.rollback()
                    errors.append({
                        "saleId": sale_id,
                        "status": new_status,
                        "error": str(err),
                    })

        return {
            "total": len(reconciliations),
            "succeeded": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }
