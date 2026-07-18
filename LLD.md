# Low-Level Design — Affiliate Payout Management System

## 1. Problem Decomposition

The system has two distinct problems that share infrastructure:

**Q1 — Payout lifecycle management**
1. An advance payout job runs and credits 10% of pending sale earnings.
2. An admin reconciles each pending sale to `approved` or `rejected`.
3. A final payout is calculated and settled, accounting for what was already advanced.
4. The user may withdraw from their wallet once per 24 hours.

**Q2 — Failed payout recovery**
When a bank transfer (withdrawal) is reported as failed/cancelled/rejected by the payment gateway, the system must:
1. Credit the amount back to the user's wallet.
2. Reset the withdrawal cooldown so the user can retry immediately.
3. Record the failure for audit purposes.

---

## 2. Architecture

### 2.1 Layered Architecture

The system uses a strict three-layer architecture. Each layer has one job and no knowledge of the layer above it.

```
┌──────────────────────────────────────────────────┐
│  Controller Layer                                │
│  • Parse HTTP req / format HTTP res              │
│  • Input validation via Joi schemas              │
│  • Zero business logic                           │
└───────────────────┬──────────────────────────────┘
                    │ calls
┌───────────────────▼──────────────────────────────┐
│  Service Layer                                   │
│  • All business rules                            │
│  • Orchestrates repositories in transactions     │
│  • Raises domain-specific errors                 │
└───────────────────┬──────────────────────────────┘
                    │ calls
┌───────────────────▼──────────────────────────────┐
│  Repository Layer                                │
│  • Prepared SQL statements only                  │
│  • No conditionals, no math                      │
│  • Returns plain objects (rows)                  │
└───────────────────┬──────────────────────────────┘
                    │ reads/writes
┌───────────────────▼──────────────────────────────┐
│  SQLite Database                                 │
│  • Single-file, WAL mode                         │
│  • FK constraints enforced                       │
│  • Atomic writes via transactions                │
└──────────────────────────────────────────────────┘
```

### 2.2 Dependency Injection

All components receive their dependencies through constructor injection. The `app.js` file is the only place where concrete instances are wired together. This means:

- Every service can be unit-tested with mock repositories.
- The database can be swapped for an in-memory instance in tests with zero code changes.
- No global singletons, no hidden coupling.

```
app.js creates:
  db → shared single connection
  repos → UserRepository(db), SaleRepository(db), WalletRepository(db), PayoutRepository(db)
  services → each service receives { db, ...repos }
  controllers → each controller receives the services it needs
  routes → each router receives its controller
```

---

## 3. Entity Design

### 3.1 Core Entities

#### User
Represents an affiliate. Owns a wallet and sales.

```
User
├── id          (UUID, PK)
├── name        (text)
├── email       (text, unique)
├── created_at
└── updated_at
```

#### Wallet
Every user has exactly one wallet. It is the single source of truth for their available balance.

```
Wallet
├── id                   (UUID, PK)
├── user_id              (FK → users, UNIQUE — enforces 1:1)
├── withdrawable_balance (real, can be negative = debt)
├── last_withdrawal_at   (nullable — null means never withdrawn)
├── created_at
└── updated_at
```

**Why can `withdrawable_balance` go negative?**
If a user receives an advance and ALL their sales are subsequently rejected, the clawback amount may exceed their current balance. A negative balance represents a debt that is recovered from future earnings rather than requiring the user to make an immediate payment.

#### Sale
The canonical record of an affiliate sale. Drives both the advance and final payout calculations.

```
Sale
├── id                 (UUID, PK)
├── user_id            (FK → users)
├── brand              (brand_1 | brand_2 | brand_3)
├── status             (pending → approved | rejected)
├── earning            (positive real)
├── advance_paid       (real, default 0) ← how much advance was disbursed for THIS sale
├── advance_payout_id  (FK → payouts, nullable) ← THE idempotency guard
├── final_payout_id    (FK → payouts, nullable) ← set once final payout is processed
├── reconciled_at      (nullable)
├── created_at
└── updated_at
```

**Why `advance_payout_id` on the sale row (not a separate table)?**
It creates an atomic, indexed guard. The advance service does `UPDATE sales SET advance_payout_id = ? WHERE id = ? AND advance_payout_id IS NULL`. SQLite's row-level locking means only one writer wins. The NULL check is the idempotency contract expressed directly in SQL.

#### Payout
A unified ledger record for every money movement in the system.

```
Payout
├── id              (UUID, PK)
├── user_id         (FK → users)
├── type            (advance | final | withdrawal | recovery)
├── amount          (real — positive for credits, negative for debits in final type)
├── status          (initiated → processing → completed)
│                                         ↘ failed | cancelled | rejected
├── notes           (JSON string, metadata)
├── failure_reason  (nullable)
├── initiated_at
├── completed_at    (nullable)
├── failed_at       (nullable)
├── created_at
└── updated_at
```

#### PayoutSaleMapping
Joins a payout to the specific sales it covers. This is the audit trail — it lets you reconstruct exactly which sales contributed to any payout.

```
PayoutSaleMapping
├── id                  (UUID, PK)
├── payout_id           (FK → payouts)
├── sale_id             (FK → sales)
├── contribution_amount (real — the amount this specific sale contributed)
└── created_at
UNIQUE(payout_id, sale_id)   ← prevents duplicate entries
```

---

## 4. State Machines

### 4.1 Sale Status

```
        [Created]
            │
            ▼
         pending  ──── (admin reconciles) ────┬──→ approved
                                              └──→ rejected

Rules:
  • pending is the ONLY source state for reconciliation.
  • approved and rejected are terminal — no further transitions.
  • Attempting to reconcile a non-pending sale returns 409 Conflict.
```

### 4.2 Payout Status

```
         initiated
             │
             ▼
         processing  ←── (withdrawal payout starts here)
             │
      ┌──────┴───────────────────────┐
      ▼                              ▼
  completed (terminal)    failed | cancelled | rejected
                                     │
                                     ▼
                              [Recovery triggered]
                                     │
                                     ▼
                              recovery payout created
                              (status: completed)

Rules:
  • advance and final payouts move: initiated → completed (synchronously, simulating instant settlement).
  • withdrawal payouts move: initiated → processing (async bank transfer in-flight).
  • A payout in a terminal state (completed/failed/cancelled/rejected) cannot be transitioned again.
  • Recovery is ONLY triggered for failed/cancelled/rejected — never for completed.
```

---

## 5. Service Layer Design

### 5.1 AdvancePayoutService

**Responsibility:** Disburse 10% of pending sale earnings as an advance, exactly once per sale.

**Key method:** `processAdvance(userId)`

```
Algorithm:
  1. Fetch all sales WHERE status='pending' AND advance_payout_id IS NULL
  2. If none → return early (idempotent, no-op)
  3. Compute advance per sale: round(earning × 0.10, 2)
  4. Compute total advance = sum of per-sale advances
  5. BEGIN TRANSACTION
       a. INSERT payout (type='advance', status='initiated')
       b. For each sale:
            UPDATE sales SET advance_payout_id=?, advance_paid=?
            WHERE id=? AND advance_payout_id IS NULL   ← conditional guard
            IF changes=0 → concurrent claim, skip this sale
       c. Credit wallet by actual total (may differ from expected if race occurred)
       d. UPDATE payout status → 'completed'
     COMMIT
  6. Return payout + breakdown
```

**Idempotency guarantee:** Running this method twice for the same user is safe. The second call finds zero eligible sales (advance_payout_id is already set) and returns a no-op response. No duplicate credits are issued.

---

### 5.2 ReconciliationService

**Responsibility:** Allow admins to transition pending sales to approved or rejected.

**Key methods:**
- `reconcileSale(saleId, newStatus)` — reconcile one sale
- `reconcileBatch(reconciliations, { rollbackOnError })` — reconcile many in one transaction

```
Algorithm (per sale):
  1. Validate newStatus ∈ {approved, rejected}
  2. Fetch sale — 404 if not found
  3. Assert sale.status === 'pending' — 409 if already reconciled
  4. UPDATE sales SET status=?, reconciled_at=NOW() WHERE id=? AND status='pending'
     (conditional WHERE prevents double-reconciliation even in race conditions)
  5. Return updated sale
```

**Batch mode:**
- All reconciliations execute within an outer transaction.
- `rollbackOnError: false` (default) — Uses `SAVEPOINT s_i` / `RELEASE s_i` / `ROLLBACK TO s_i` for each item. If an item fails, its savepoint is rolled back and an error is collected; valid items are released and committed when the outer transaction finishes.
- `rollbackOnError: true` — Any single failure causes the entire outer transaction to roll back (all-or-nothing).

---

### 5.3 FinalPayoutService

**Responsibility:** Calculate and settle the final payout after reconciliation.

**Key method:** `processFinalPayout(userId)`

```
Business Rule applied per sale:
  approved → contribution = earning − advance_paid
  rejected → contribution = −advance_paid   (clawback only; full earning is forfeit)

Algorithm:
  1. Fetch sales WHERE status IN ('approved','rejected') AND final_payout_id IS NULL
  2. If none → return early
  3. For each sale: apply business rule → get contribution amount
  4. totalFinal = sum(contributions)   [can be negative]
  5. BEGIN TRANSACTION
       a. INSERT payout (type='final', amount=totalFinal)
       b. For each sale:
            INSERT payout_sale_mapping
            UPDATE sales SET final_payout_id=?
       c. Wallet adjustment:
            totalFinal > 0 → credit wallet
            totalFinal < 0 → debit wallet (clawback; balance may go negative)
            totalFinal = 0 → no wallet change
       d. UPDATE payout status → 'completed'
     COMMIT
  6. Return payout + per-sale breakdown
```

---

### 5.4 WithdrawalService

**Responsibility:** Let users transfer their wallet balance to their bank, with a 24-hour rate limit.

**Key method:** `initiateWithdrawal(userId, amount)`

```
Algorithm (entire flow is inside one transaction):
  1. Validate amount > 0
  2. Fetch wallet INSIDE transaction (prevents TOCTOU race)
  3. Check 24-hour cooldown:
       elapsed = NOW() − wallet.last_withdrawal_at
       IF elapsed < 24h → throw 429 with time-remaining
  4. Check balance:
       IF wallet.withdrawable_balance < amount → throw 400
  5. INSERT payout (type='withdrawal', status='processing')
  6. Debit wallet by amount
  7. SET wallet.last_withdrawal_at = NOW()
  8. Return payout (still in 'processing' — bank transfer is async)
```

**Why debit on initiation, not on completion?**
The wallet is debited immediately to prevent double-spend: if the user somehow fired two concurrent requests, the second would fail the balance check inside the transaction. The bank transfer completes asynchronously; if it fails, PayoutRecoveryService credits the amount back.

---

### 5.5 PayoutRecoveryService

**Responsibility:** Handle Q2 — recover failed/cancelled/rejected payouts with type-aware wallet adjustment and entity state reset.

**Key method:** `recoverPayout(payoutId, failureStatus, reason)`

```
Preconditions:
  • failureStatus ∈ {failed, cancelled, rejected}
  • payout.status must NOT already be a terminal state (completed/failed/cancelled/rejected) (prevent double-recovery)

Wallet Adjustment Matrix:
  • withdrawal (amount > 0): CREDIT wallet by amount (bank transfer failed; restore balance)
  • advance (amount > 0):    DEBIT wallet by amount (advance transfer failed; reverse initial credit)
  • final (amount > 0):      DEBIT wallet by amount (final payout transfer failed; reverse initial credit)
  • final (amount < 0):      CREDIT wallet by |amount| (final clawback debit failed; restore balance)

Algorithm:
  BEGIN TRANSACTION
    1. UPDATE payout SET status=failureStatus, failed_at=NOW(), failure_reason=reason
    2. Apply Wallet Adjustment according to matrix (credit or debit wallet)
    3. IF payout.type === 'withdrawal':
         Reset wallet.last_withdrawal_at = NULL
         (failed withdrawal should not consume the 24-hr slot)
    4. IF payout.type === 'advance':
         UPDATE sales SET advance_payout_id=NULL, advance_paid=0
         WHERE advance_payout_id = payoutId
         (makes those sales eligible for the next advance payout run)
    5. IF payout.type === 'final':
         UPDATE sales SET final_payout_id=NULL
         WHERE final_payout_id = payoutId
         (makes those sales eligible for re-calculation in next final payout run)
    6. INSERT recovery payout (type='recovery', amount=adjustedAmount, status='completed')
       (audit record — every money movement has a trace)
  COMMIT
  Return { failedPayout, recoveryPayout, amountAdjusted, updatedWallet }
```

---

## 6. Repository Layer Design

Each repository owns exactly one table and has no knowledge of business rules.

| Repository | Table | Key methods |
|---|---|---|
| `UserRepository` | `users` | `create`, `findById`, `findByEmail` |
| `WalletRepository` | `wallets` | `create`, `findByUserId`, `credit`, `debit`, `setLastWithdrawalAt` |
| `SaleRepository` | `sales` | `create`, `findByUserId`, `findEligibleForAdvance`, `findEligibleForFinalPayout`, `markAdvancePaid`, `markFinalPaid`, `reconcile`, `resetAdvancePayoutForPayout` |
| `PayoutRepository` | `payouts` + `payout_sale_mappings` | `create`, `findByUserId`, `updateStatus`, `addSaleMapping`, `getSaleMappings` |

---

## 7. API Layer Design

Controllers are intentionally thin. Each controller method does exactly three things:
1. Extract validated data from `req`.
2. Call the appropriate service method.
3. Send the response.

All error handling is delegated to a global `errorHandler` middleware that reads `err.statusCode` from `AppError` instances. Programming errors (unexpected) are masked as 500 with the stack logged server-side.

---

## 8. Transaction Strategy

Every operation that touches more than one table runs inside a `db.transaction()` block (better-sqlite3). This guarantees:

- **Atomicity:** Either all changes commit or none do. No partial states.
- **Consistency:** FK constraints are checked at commit time.
- **Isolation:** SQLite serialises writers, so concurrent requests cannot interleave within a transaction.
- **Durability:** WAL mode + `synchronous=NORMAL` ensures committed data survives crashes.

The critical transactions are:

| Operation | Tables touched |
|---|---|
| Advance payout | `payouts`, `sales` (multiple rows), `wallets`, `payout_sale_mappings` |
| Final payout | `payouts`, `sales` (multiple rows), `wallets`, `payout_sale_mappings` |
| Withdrawal | `payouts`, `wallets` |
| Recovery | `payouts`, `wallets`, `sales` (optional) |

---

## 9. Financial Precision

JavaScript's IEEE 754 doubles produce rounding errors in accumulated sums (e.g. `0.1 + 0.2 = 0.30000000000000004`). This system mitigates the issue by:

1. Rounding every calculated amount to 2 decimal places at the point of calculation using `Math.round((n + Number.EPSILON) * 100) / 100`.
2. Using SQLite's `ROUND(expr, 2)` in credit/debit UPDATE statements as a second safety net.

**Production recommendation:** Store all amounts as integers in the smallest currency unit (paisa = 1/100 of a rupee). Convert to decimal only at the API boundary. This eliminates floating-point error entirely.
