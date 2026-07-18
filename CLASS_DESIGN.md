# Class & Module Design

## Dependency Wiring (app.js)

```
db (createDatabase)
 │
 ├── UserRepository(db)
 ├── WalletRepository(db)
 ├── SaleRepository(db)
 └── PayoutRepository(db)
      │
      ├── AdvancePayoutService({ db, userRepo, saleRepo, payoutRepo, walletRepo })
      ├── ReconciliationService({ db, saleRepo })
      ├── FinalPayoutService({ db, userRepo, saleRepo, payoutRepo, walletRepo })
      ├── WithdrawalService({ db, userRepo, payoutRepo, walletRepo })
      └── PayoutRecoveryService({ db, payoutRepo, walletRepo, saleRepo })
           │
           ├── UserController({ userRepo, walletRepo })
           ├── SaleController({ saleRepo, userRepo, reconciliationService })
           ├── PayoutController({ advancePayoutService, finalPayoutService,
           │                      payoutRecoveryService, payoutRepo })
           └── WalletController({ walletRepo, withdrawalService })
```

---

## Utils

### `utils/AppError.js`

```js
class AppError extends Error
  constructor(message: string, statusCode: number = 500, code: string | null = null)
  .statusCode: number
  .code: string | null
  .isOperational: boolean   // true = safe to expose to client

class NotFoundError extends AppError
  constructor(resource: string, id?: string)

class ConflictError extends AppError
  constructor(message: string, code?: string)

class ValidationError extends AppError
  constructor(message: string)

class RateLimitError extends AppError
  constructor(message: string)
```

---

### `utils/financial.js`

```js
ADVANCE_RATE: number                                          // 0.10

roundTo2dp(amount: number): number
  // Math.round((amount + Number.EPSILON) * 100) / 100

calcAdvance(earning: number): number
  // roundTo2dp(earning * ADVANCE_RATE)

calcFinalForSale(
  status: 'approved' | 'rejected',
  earning: number,
  advancePaid: number
): number
  // approved → roundTo2dp(earning - advancePaid)
  // rejected → roundTo2dp(-advancePaid)

sumAmounts(amounts: number[]): number
  // amounts.map(a => roundTo2dp(a)).reduce((a, b) => roundTo2dp(a + b), 0)
```

---

## Repositories

### `repositories/BaseRepository`

```js
class BaseRepository
  constructor(db: Database, tableName: string)
  findById(id: string): object | null
  findAll(): object[]
  existsById(id: string): boolean
```

---

### `repositories/UserRepository extends BaseRepository`

```js
class UserRepository
  constructor(db: Database)
  create({ name, email, id? }): User
  findByEmail(email: string): User | null
```

---

### `repositories/WalletRepository extends BaseRepository`

```js
class WalletRepository
  constructor(db: Database)
  create(userId: string): Wallet
  findByUserId(userId: string): Wallet | null
  credit(userId: string, amount: number): Wallet        // balance += amount (SQL: WHERE user_id = ?)
  debit(userId: string, amount: number): Wallet         // balance -= amount (SQL: WHERE user_id = ?, can go negative)
  setLastWithdrawalAt(userId: string, timestamp: string | null): Wallet
```

---

### `repositories/SaleRepository extends BaseRepository`

```js
class SaleRepository
  constructor(db: Database)
  create({ userId, brand, earning, status?, id? }): Sale
  findByUserId(userId: string): Sale[]
  findEligibleForAdvance(userId: string): Sale[]
    // WHERE status='pending' AND advance_payout_id IS NULL
  findEligibleForFinalPayout(userId: string): Sale[]
    // WHERE status IN ('approved','rejected') AND final_payout_id IS NULL
  markAdvancePaid(saleId: string, payoutId: string, advancePaid: number): RunResult
    // UPDATE WHERE advance_payout_id IS NULL AND status='pending'
    // returns { changes: 0 | 1 } — use changes===0 to detect concurrent claim
  markFinalPaid(saleId: string, payoutId: string): RunResult
  reconcile(saleId: string, newStatus: string): Sale | null
    // UPDATE WHERE status='pending' — returns null if already reconciled
  resetAdvancePayoutForPayout(payoutId: string): RunResult
    // UPDATE SET advance_payout_id=NULL, advance_paid=0 WHERE advance_payout_id=payoutId
  resetFinalPayoutForPayout(payoutId: string): RunResult
    // UPDATE SET final_payout_id=NULL WHERE final_payout_id=payoutId
  findByAdvancePayoutId(payoutId: string): Sale[]
  findByFinalPayoutId(payoutId: string): Sale[]
```

---

### `repositories/PayoutRepository extends BaseRepository`

```js
class PayoutRepository
  constructor(db: Database)
  create({ userId, type, amount, status?, notes? }): Payout
  findByUserId(userId: string): Payout[]
  findByUserIdAndType(userId: string, type: string): Payout[]
  updateStatus(payoutId: string, status: string, extra?: { failureReason?: string }): Payout
  addSaleMapping(payoutId: string, saleId: string, contributionAmount: number): void
  getSaleMappings(payoutId: string): PayoutSaleMapping[]
  findByStatus(status: string): Payout[]
```

---

## Services

### `services/AdvancePayoutService`

```js
class AdvancePayoutService
  constructor({ db, userRepo, saleRepo, payoutRepo, walletRepo })

  processAdvance(userId: string): {
    payout: Payout | null,
    eligibleSales: Sale[],
    totalAdvance: number,
    message: string
  }
  // Throws: NotFoundError (user), AppError 409 (concurrent conflict)
  // Transaction: payouts + sales (multi-row) + wallets + payout_sale_mappings
  // Idempotent: safe to call multiple times
```

---

### `services/ReconciliationService`

```js
class ReconciliationService
  constructor({ db, saleRepo })

  reconcileSale(saleId: string, newStatus: 'approved' | 'rejected'): Sale
  // Throws: ValidationError (bad status), NotFoundError, ConflictError (already reconciled)

  reconcileBatch(
    reconciliations: Array<{ saleId: string, status: string }>,
    opts?: { rollbackOnError?: boolean }
  ): {
    total: number,
    succeeded: number,
    failed: number,
    results: Array<{ saleId, status, sale }>,
    errors: Array<{ saleId, status, error }>
  }
  // All items in one transaction
  // rollbackOnError=false (default): errors collected, other items still commit
  // rollbackOnError=true: any failure rolls back everything
```

---

### `services/FinalPayoutService`

```js
class FinalPayoutService
  constructor({ db, userRepo, saleRepo, payoutRepo, walletRepo })

  processFinalPayout(userId: string): {
    payout: Payout | null,
    breakdown: Array<{
      sale: Sale,
      finalAmount: number,    // + for approved, - for rejected
      reason: string          // human-readable explanation
    }>,
    totalFinal: number,       // can be negative
    message: string
  }
  // Throws: NotFoundError (user)
  // Transaction: payouts + sales (multi-row) + wallets + payout_sale_mappings
  // Idempotent: second call finds no eligible sales, returns no-op
```

---

### `services/WithdrawalService`

```js
class WithdrawalService
  constructor({ db, userRepo, payoutRepo, walletRepo })

  initiateWithdrawal(userId: string, amount: number): Payout
  // Throws:
  //   ValidationError  — amount <= 0
  //   NotFoundError    — user or wallet not found
  //   RateLimitError   — within 24-hr cooldown (includes cooldown_remaining_ms)
  //   AppError 400     — insufficient balance
  // Transaction: wallets (read+write) + payouts
  // Returns payout with status='processing'

  getCooldownRemainingMs(userId: string): number
  // Returns 0 if eligible, positive ms if still in cooldown
```

---

### `services/PayoutRecoveryService`

```js
class PayoutRecoveryService
  constructor({ db, payoutRepo, walletRepo, saleRepo })

  recoverPayout(
    payoutId: string,
    status: 'failed' | 'cancelled' | 'rejected',
    reason?: string
  ): {
    failedPayout: Payout,
    recoveryPayout: Payout,
    amountAdjusted: number,
    wallet: Wallet,
    message: string
  }
  // Throws:
  //   ValidationError — status not in recoverable set
  //   NotFoundError   — payout not found
  //   ConflictError   — payout already in terminal state
  // Side effects:
  //   - Applies type-aware wallet adjustment (withdrawal -> CREDIT, advance -> DEBIT, final -> reverse delta)
  //   - If type='withdrawal': resets wallet.last_withdrawal_at = NULL
  //   - If type='advance':    resets sales.advance_payout_id = NULL (retry eligible)
  //   - If type='final':      resets sales.final_payout_id = NULL (retry eligible)
  //   - Always:               creates recovery payout for audit trail
  // Transaction: payouts + wallets + sales (optional) + payouts (recovery record)

  updatePayoutStatus(
    payoutId: string,
    newStatus: string,
    reason?: string
  ): object
  // Routes: 'failed'|'cancelled'|'rejected' → recoverPayout()
  //         'completed' → simple status update (sets completed_at = NOW())
```

---

## Controllers (thin layer)

### `controllers/UserController`

```js
createUser(req, res, next)    // POST /api/users
getUser(req, res, next)       // GET  /api/users/:id
```

### `controllers/SaleController`

```js
createSale(req, res, next)     // POST /api/sales
getSales(req, res, next)       // GET  /api/sales
getSaleById(req, res, next)    // GET  /api/sales/:id
reconcileBatch(req, res, next) // POST /api/sales/reconcile
```

### `controllers/PayoutController`

```js
processAdvance(req, res, next)      // POST  /api/payouts/advance/:userId
processFinalPayout(req, res, next)  // POST  /api/payouts/final/:userId
getPayouts(req, res, next)          // GET   /api/payouts
getPayoutById(req, res, next)       // GET   /api/payouts/:id
updatePayoutStatus(req, res, next)  // PATCH /api/payouts/:id/status
```

### `controllers/WalletController`

```js
getWallet(req, res, next)     // GET  /api/wallet/:userId
withdraw(req, res, next)      // POST /api/wallet/:userId/withdraw
```

---

## Middleware

### `middleware/validate.js`

```js
// Factory: returns Express middleware that validates req.body against a Joi schema
validate(schema: Joi.Schema): (req, res, next) => void

// Validation schemas
schemas.createUser
schemas.createSale
schemas.reconcileBatch
schemas.withdraw
schemas.updatePayoutStatus
```

### `middleware/errorHandler.js`

```js
// Global Express error handler (4-arg middleware)
errorHandler(err, req, res, next): void

// AppError (isOperational=true):
//   → res.status(err.statusCode).json({ success: false, error: { message, code } })
// Other errors (programming errors):
//   → log stack trace, res.status(500).json({ success: false, error: { message: 'Internal Server Error' } })
```

---

## Data Types Reference

```ts
type Sale = {
  id: string
  user_id: string
  brand: 'brand_1' | 'brand_2' | 'brand_3'
  status: 'pending' | 'approved' | 'rejected'
  earning: number
  advance_paid: number
  advance_payout_id: string | null
  final_payout_id: string | null
  reconciled_at: string | null
  created_at: string
  updated_at: string
}

type Payout = {
  id: string
  user_id: string
  type: 'advance' | 'final' | 'withdrawal' | 'recovery'
  amount: number
  status: 'initiated' | 'processing' | 'completed' | 'cancelled' | 'rejected' | 'failed'
  notes: string | null
  failure_reason: string | null
  initiated_at: string
  completed_at: string | null
  failed_at: string | null
  created_at: string
  updated_at: string
}

type Wallet = {
  id: string
  user_id: string
  withdrawable_balance: number   // can be negative (debt)
  last_withdrawal_at: string | null
  created_at: string
  updated_at: string
}
```
