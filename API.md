# API Specification

**Base URL:** `http://localhost:3000/api`

All responses follow this envelope:

```json
// Success
{ "success": true, "data": { ... } }

// Error
{ "success": false, "error": { "message": "...", "code": "..." } }
```

---

## Users

### `POST /api/users`
Create a new user. A wallet is automatically created alongside.

**Request body:**
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "id": "john_doe"        // optional — if omitted, a UUID is generated
}
```

**Response `201`:**
```json
{
  "success": true,
  "data": {
    "user": { "id": "john_doe", "name": "John Doe", "email": "john@example.com" },
    "wallet": { "id": "...", "user_id": "john_doe", "withdrawable_balance": 0 }
  }
}
```

**Errors:**
- `400` — missing required fields
- `409` — email already exists

```bash
curl -X POST http://localhost:3000/api/users \
  -H "Content-Type: application/json" \
  -d '{"name":"John Doe","email":"john@example.com","id":"john_doe"}'
```

---

### `GET /api/users/:id`
Get a user by ID.

```bash
curl http://localhost:3000/api/users/john_doe
```

---

## Sales

### `POST /api/sales`
Create a new affiliate sale (starts in `pending` status).

**Request body:**
```json
{
  "userId": "john_doe",
  "brand": "brand_1",
  "earning": 40
}
```

**Response `201`:**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "user_id": "john_doe",
    "brand": "brand_1",
    "status": "pending",
    "earning": 40,
    "advance_paid": 0,
    "advance_payout_id": null,
    "final_payout_id": null
  }
}
```

**Validations:**
- `brand` must be one of: `brand_1`, `brand_2`, `brand_3`
- `earning` must be a positive number
- `userId` must reference an existing user

```bash
curl -X POST http://localhost:3000/api/sales \
  -H "Content-Type: application/json" \
  -d '{"userId":"john_doe","brand":"brand_1","earning":40}'
```

---

### `GET /api/sales`
List sales. Filter by user with query param.

```bash
curl "http://localhost:3000/api/sales?userId=john_doe"
```

**Response `200`:**
```json
{
  "success": true,
  "count": 3,
  "data": [ { ...sale }, { ...sale }, { ...sale } ]
}
```

---

### `GET /api/sales/:id`
Get a single sale by ID.

```bash
curl http://localhost:3000/api/sales/<sale-id>
```

---

### `POST /api/sales/reconcile`
**Admin endpoint.** Batch-reconcile multiple sales in one atomic operation.

**Request body:**
```json
{
  "reconciliations": [
    { "saleId": "uuid-1", "status": "rejected" },
    { "saleId": "uuid-2", "status": "approved" },
    { "saleId": "uuid-3", "status": "approved" }
  ],
  "rollbackOnError": false
}
```

- `status` must be `approved` or `rejected`.
- `rollbackOnError` (optional, default `false`): if `true`, a single failure rolls back all reconciliations in the batch.

**Response `200`:**
```json
{
  "success": true,
  "data": {
    "total": 3,
    "succeeded": 3,
    "failed": 0,
    "results": [
      { "saleId": "uuid-1", "status": "rejected", "sale": { ... } },
      { "saleId": "uuid-2", "status": "approved", "sale": { ... } },
      { "saleId": "uuid-3", "status": "approved", "sale": { ... } }
    ],
    "errors": []
  }
}
```

**Errors (per-item, when `rollbackOnError: false`):**
```json
{
  "errors": [
    { "saleId": "uuid-x", "status": "approved", "error": "Sale 'uuid-x' is already 'approved'." }
  ]
}
```

```bash
curl -X POST http://localhost:3000/api/sales/reconcile \
  -H "Content-Type: application/json" \
  -d '{
    "reconciliations": [
      {"saleId":"<id-1>","status":"rejected"},
      {"saleId":"<id-2>","status":"approved"},
      {"saleId":"<id-3>","status":"approved"}
    ]
  }'
```

---

## Payouts

### `POST /api/payouts/advance/:userId`
Run the advance payout job for a specific user. Safe to call multiple times — idempotent.

**Response `200`:**
```json
{
  "success": true,
  "data": {
    "payout": {
      "id": "uuid",
      "user_id": "john_doe",
      "type": "advance",
      "amount": 12,
      "status": "completed"
    },
    "eligibleSales": [ { ...sale }, { ...sale }, { ...sale } ],
    "totalAdvance": 12,
    "message": "Advance payout of ₹12 processed for 3 sale(s)."
  }
}
```

**When no eligible sales exist:**
```json
{
  "success": true,
  "data": {
    "payout": null,
    "eligibleSales": [],
    "totalAdvance": 0,
    "message": "No eligible pending sales found for advance payout."
  }
}
```

```bash
curl -X POST http://localhost:3000/api/payouts/advance/john_doe
```

---

### `POST /api/payouts/final/:userId`
Calculate and process the final payout for a user after reconciliation.

**Response `200`:**
```json
{
  "success": true,
  "data": {
    "payout": {
      "id": "uuid",
      "type": "final",
      "amount": 68,
      "status": "completed"
    },
    "totalFinal": 68,
    "breakdown": [
      {
        "sale": { "id": "...", "status": "rejected", "earning": 40, "advance_paid": 4 },
        "finalAmount": -4,
        "reason": "Rejected: clawback of ₹4 advance = ₹-4"
      },
      {
        "sale": { "id": "...", "status": "approved", "earning": 40, "advance_paid": 4 },
        "finalAmount": 36,
        "reason": "Approved: ₹40 − ₹4 advance = ₹36"
      },
      {
        "sale": { "id": "...", "status": "approved", "earning": 40, "advance_paid": 4 },
        "finalAmount": 36,
        "reason": "Approved: ₹40 − ₹4 advance = ₹36"
      }
    ],
    "message": "Final payout processed. ₹68 credited to wallet."
  }
}
```

```bash
curl -X POST http://localhost:3000/api/payouts/final/john_doe
```

---

### `GET /api/payouts`
List all payouts. Filter by user.

```bash
curl "http://localhost:3000/api/payouts?userId=john_doe"
```

---

### `GET /api/payouts/:id`
Get a payout by ID, including its sale mappings (breakdown).

**Response `200`:**
```json
{
  "success": true,
  "data": {
    "payout": { ...payout },
    "saleMappings": [
      { "sale_id": "...", "contribution_amount": 36, "sale_status": "approved", "earning": 40 }
    ]
  }
}
```

---

### `PATCH /api/payouts/:id/status`
Update a payout's status. Used to simulate a payment gateway callback.

**If status is `failed`, `cancelled`, or `rejected` → recovery is automatically triggered.**

**Request body:**
```json
{
  "status": "failed",
  "reason": "Bank account invalid"
}
```

Valid statuses: `completed`, `failed`, `cancelled`, `rejected`

**Response (when recovery triggered) `200`:**
```json
{
  "success": true,
  "data": {
    "failedPayout": { "id": "...", "status": "failed", "failure_reason": "Bank account invalid" },
    "recoveryPayout": { "id": "...", "type": "recovery", "amount": 50, "status": "completed" },
    "amountCredited": 50,
    "wallet": { "withdrawable_balance": 150 },
    "message": "Payout failed. ₹50 has been credited back to the user's wallet."
  }
}
```

```bash
# Simulate bank rejection of a withdrawal
curl -X PATCH http://localhost:3000/api/payouts/<payout-id>/status \
  -H "Content-Type: application/json" \
  -d '{"status":"failed","reason":"Bank transfer timed out"}'
```

---

## Wallet

### `GET /api/wallet/:userId`
Get a user's wallet including current balance and last withdrawal time.

```bash
curl http://localhost:3000/api/wallet/john_doe
```

**Response `200`:**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "user_id": "john_doe",
    "withdrawable_balance": 80,
    "last_withdrawal_at": null,
    "withdrawal_eligible": true,
    "cooldown_remaining_ms": 0
  }
}
```

---

### `POST /api/wallet/:userId/withdraw`
Initiate a withdrawal. Enforces the 24-hour cooldown.

**Request body:**
```json
{ "amount": 50 }
```

**Response `200`:**
```json
{
  "success": true,
  "data": {
    "payout": {
      "id": "uuid",
      "type": "withdrawal",
      "amount": 50,
      "status": "processing"
    },
    "wallet": {
      "withdrawable_balance": 30
    },
    "message": "Withdrawal of ₹50 initiated. Transfer is processing."
  }
}
```

**Errors:**
- `400` — insufficient balance
- `429` — cooldown active (includes `cooldown_remaining_ms` in error body)

```bash
curl -X POST http://localhost:3000/api/wallet/john_doe/withdraw \
  -H "Content-Type: application/json" \
  -d '{"amount": 50}'
```

---

## Error Response Reference

| HTTP Code | Code | When |
|---|---|---|
| `400` | `VALIDATION_ERROR` | Invalid request body / params |
| `400` | `INSUFFICIENT_BALANCE` | Withdrawal amount > balance |
| `404` | `NOT_FOUND` | User / Sale / Payout not found |
| `409` | `CONFLICT` | Sale already reconciled, etc. |
| `409` | `SALE_ALREADY_RECONCILED` | Attempting to reconcile non-pending sale |
| `429` | `RATE_LIMITED` | Withdrawal within 24-hr cooldown |
| `500` | `INTERNAL_ERROR` | Unexpected server error (details logged server-side) |

---

## Complete Flow — Assignment Example

```bash
# 1. Create user
curl -X POST /api/users -d '{"name":"John Doe","email":"john@example.com","id":"john_doe"}'

# 2. Create 3 pending sales (₹40 each)
curl -X POST /api/sales -d '{"userId":"john_doe","brand":"brand_1","earning":40}'
curl -X POST /api/sales -d '{"userId":"john_doe","brand":"brand_1","earning":40}'
curl -X POST /api/sales -d '{"userId":"john_doe","brand":"brand_1","earning":40}'

# 3. Run advance payout → wallet gets ₹12 (10% of ₹120)
curl -X POST /api/payouts/advance/john_doe

# 4. Admin reconciles
curl -X POST /api/sales/reconcile -d '{
  "reconciliations":[
    {"saleId":"<id1>","status":"rejected"},
    {"saleId":"<id2>","status":"approved"},
    {"saleId":"<id3>","status":"approved"}
  ]
}'

# 5. Run final payout → -₹4 + ₹36 + ₹36 = ₹68 credited to wallet
curl -X POST /api/payouts/final/john_doe

# Wallet now has ₹12 (advance) + ₹68 (final) = ₹80

# 6. User withdraws ₹50
curl -X POST /api/wallet/john_doe/withdraw -d '{"amount":50}'

# 7. Simulate bank failure → ₹50 credited back
curl -X PATCH /api/payouts/<withdrawal-payout-id>/status \
  -d '{"status":"failed","reason":"Bank rejected transfer"}'

# Wallet back to ₹80, cooldown reset, user can retry
```
