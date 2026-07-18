# Edge Cases & Failure Scenarios

This document enumerates every non-happy-path scenario and explains exactly how the system handles it.

---

## Advance Payout Edge Cases

### EC-1: Advance payout job runs twice for the same user

**Scenario:** The advance payout cron job fires twice (e.g., double scheduling, operator error).

**Handling:**
The second run queries `WHERE status='pending' AND advance_payout_id IS NULL`. All eligible sales were marked with `advance_payout_id` during the first run, so the query returns zero rows. The service returns a no-op response. No duplicate credit is issued.

**Result:** ✅ Safe. Wallet unchanged. No payout created.

---

### EC-2: User has no pending sales when advance payout runs

**Scenario:** All of a user's sales are already approved/rejected (or they have no sales at all).

**Handling:**
`findEligibleForAdvance` returns an empty array. The service returns early with `totalAdvance: 0` and `payout: null`. No record is written to the DB.

**Result:** ✅ Clean early exit with an informative message.

---

### EC-3: Advance payout runs while reconciliation is happening concurrently

**Scenario:** Admin reconciles sale A at the exact moment the advance job processes sale A.

**Handling:**
The advance job does:
```sql
UPDATE sales SET advance_payout_id=? WHERE id=? AND advance_payout_id IS NULL AND status='pending'
```
If reconciliation committed first and changed `status` to `approved`/`rejected`, this UPDATE matches 0 rows (`status='pending'` guard fails). The advance job skips that sale. The sale will be picked up by the final payout instead (as a zero-advance sale).

**Result:** ✅ No double payment. Sale gets its full earning in the final payout (advance_paid = 0).

---

### EC-4: Advance payout partially fails mid-transaction

**Scenario:** The system crashes (power cut, OOM) after crediting 2 of 5 sales but before committing.

**Handling:**
SQLite's WAL mode ensures the transaction is fully rolled back on crash recovery. No partial state persists. All 5 sales retain `advance_payout_id IS NULL`. The next run picks them all up correctly.

**Result:** ✅ Full rollback. System is consistent.

---

## Reconciliation Edge Cases

### EC-5: Admin tries to reconcile an already-approved sale

**Scenario:** Reconcile endpoint called twice for the same sale.

**Handling:**
Service checks `sale.status !== 'pending'` before the UPDATE. Returns `409 SALE_ALREADY_RECONCILED` with a descriptive message. The `reconcile()` repository method also has `WHERE status='pending'` as a double guard.

**Result:** ✅ Rejected at the service layer. No DB write.

---

### EC-6: Reconcile called with an unknown sale ID

**Handling:**
`findById` returns `null`. Service throws `404 NOT_FOUND`. No DB write.

---

### EC-7: Batch reconcile has a mix of valid and invalid items

**Scenario:** Items [A: valid, B: already reconciled, C: valid] in one batch call.

**Handling (default `rollbackOnError: false`):**
- A → succeeds
- B → error collected, processing continues
- C → succeeds

Response includes `succeeded: 2, failed: 1` with per-item details. Caller can inspect errors and retry just the failed items.

**Handling (`rollbackOnError: true`):**
B fails → transaction is aborted → A and C are also rolled back → response reports all 3 as failed.

**Result:** ✅ Caller controls the semantics.

---

## Final Payout Edge Cases

### EC-8: All sales are rejected — negative final payout

**Scenario:** User received advance payouts on 3 sales. Admin rejects all 3.

**Example:**
- 3 × ₹40 sales, each with ₹4 advance paid
- Final: −₹4 + −₹4 + −₹4 = −₹12

**Handling:**
`totalFinal = -12`. The wallet is debited by ₹12. If wallet balance was ₹12 (from the advances), it goes to ₹0. If the user had also withdrawn some of it, the balance goes negative (representing a debt). Future earnings will offset this debt.

**Result:** ✅ Handled. Negative wallet balance is permitted by design.

---

### EC-9: Sale is reconciled but never received an advance

**Scenario:** The advance payout job was never run before reconciliation happened. `advance_paid = 0`, `advance_payout_id = NULL`.

**Handling:**
`findEligibleForFinalPayout` uses `WHERE status IN ('approved','rejected') AND final_payout_id IS NULL` — no condition on `advance_payout_id`. This sale IS eligible.
- If approved: `final = earning − 0 = earning` (user gets the full amount)
- If rejected: `final = −0 = 0` (no clawback since no advance was paid)

**Result:** ✅ Correct. System handles the missing advance gracefully.

---

### EC-10: Final payout run before any sales are reconciled

**Scenario:** `POST /payouts/final/:userId` called before the admin reconciles anything.

**Handling:**
`findEligibleForFinalPayout` returns empty array. Service returns early with `payout: null` and an explanatory message.

**Result:** ✅ Clean early exit.

---

### EC-11: Final payout run twice for the same sales

**Scenario:** Someone calls `POST /payouts/final/:userId` twice.

**Handling:**
First run sets `final_payout_id` on all eligible sales. Second run queries `WHERE final_payout_id IS NULL` and finds zero eligible sales. Returns early as a no-op.

**Result:** ✅ Idempotent.

---

## Withdrawal Edge Cases

### EC-12: User tries to withdraw more than their balance

**Scenario:** Balance = ₹30, requested = ₹50.

**Handling:**
The wallet is read INSIDE the transaction. Balance check fails. Throws `400 INSUFFICIENT_BALANCE`. No payout created, no wallet debit.

**Result:** ✅ Rejected with clear error.

---

### EC-13: Two concurrent withdrawal requests from the same user

**Scenario:** User double-taps, sending two simultaneous `POST /wallet/:id/withdraw` requests.

**Handling:**
SQLite serialises writers. One request acquires the write lock first and completes the transaction (debit + update `last_withdrawal_at`). The second request then reads the wallet INSIDE its transaction and sees either:
- An insufficient balance (if the first debit consumed it), OR
- A `last_withdrawal_at` set to just now, triggering the 24-hr cooldown rejection.

Either way, the second request is rejected. No double-debit.

**Result:** ✅ Safe due to serialised transaction + TOCTOU-safe design.

---

### EC-14: User tries to withdraw within the 24-hour cooldown window

**Scenario:** User withdrew 3 hours ago.

**Handling:**
Service checks `Date.now() − last_withdrawal_at < 24h`. Throws `429 RATE_LIMITED` with `cooldown_remaining_ms` included in the error payload so the client can display a countdown.

**Result:** ✅ Rejected with time-remaining info.

---

### EC-15: User withdraws ₹0 or a negative amount

**Handling:**
Joi input validation rejects `amount` that is not a positive number before the service is called. Returns `400 VALIDATION_ERROR`.

**Result:** ✅ Caught at the boundary.

---

## Failed Payout Recovery Edge Cases

### EC-16: Recovery triggered on an already-completed payout

**Scenario:** Gateway sends a duplicate failure webhook for a payout that is already marked `completed`.

**Handling:**
`recoverPayout` checks the payout's current status. If it's already `completed`, it throws `409 CONFLICT` — a completed payout cannot be failed. No wallet credit issued.

**Result:** ✅ Idempotent. No double-credit.

---

### EC-17: Recovery triggered twice for the same failed payout

**Scenario:** Recovery webhook is delivered twice (network retry).

**Handling:**
First call transitions payout to `failed` and issues a recovery credit. Second call checks payout status → already `failed` (terminal) → throws `409 CONFLICT`.

**Result:** ✅ No double-credit.

---

### EC-18: Advance payout fails at the bank level

**Scenario:** The advance payout's underlying bank transfer is rejected (e.g., platform's bank account has issues).

**Handling:**
`recoverPayout(advancePayoutId, 'failed', reason)` is called. It:
1. Marks the advance payout as `failed`.
2. Debits the wallet by the advance amount (reversal — since wallet was credited on initiation).
3. Resets `advance_payout_id = NULL` and `advance_paid = 0` on all associated sales, making them eligible for the next advance payout run.

**Result:** ✅ System is fully consistent. Sales can be re-processed.

---

### EC-19: Wallet goes negative after clawback and user tries to withdraw

**Scenario:** Balance = −₹5 (debt). User tries to withdraw ₹0 more.

**Handling:**
`withdrawable_balance (-5) < requested amount (anything > 0)` → `400 INSUFFICIENT_BALANCE`.

**Result:** ✅ User cannot withdraw while in debt.

---

### EC-20: User created but wallet creation fails

**Scenario:** Server crashes between INSERT user and INSERT wallet.

**Handling:**
User creation and wallet creation happen in the same transaction in `UserController`. If either INSERT fails, both are rolled back. No orphaned user record without a wallet.

**Result:** ✅ Atomic user+wallet creation.

---

## Summary Table

| # | Scenario | HTTP Status | Mechanism |
|---|---|---|---|
| EC-1 | Advance job runs twice | 200 (no-op) | `advance_payout_id IS NULL` guard |
| EC-2 | No pending sales | 200 (no-op) | Early return |
| EC-3 | Advance + reconcile race | 200 (skip) | `status='pending'` guard in UPDATE |
| EC-4 | Mid-transaction crash | — | SQLite WAL rollback |
| EC-5 | Double reconcile | 409 | Service + DB conditional UPDATE |
| EC-6 | Unknown sale in reconcile | 404 | `findById` null check |
| EC-7 | Mixed batch reconcile | 200 (partial) | Per-item error collection |
| EC-8 | All sales rejected | 200 | Negative wallet balance allowed |
| EC-9 | No advance before final | 200 | No `advance_payout_id` condition |
| EC-10 | Final before reconcile | 200 (no-op) | Early return |
| EC-11 | Final payout twice | 200 (no-op) | `final_payout_id IS NULL` guard |
| EC-12 | Withdraw over balance | 400 | In-transaction balance check |
| EC-13 | Concurrent withdrawals | 429/400 | SQLite write serialisation |
| EC-14 | Withdraw in cooldown | 429 | `last_withdrawal_at` check |
| EC-15 | Withdraw ₹0 | 400 | Joi validation |
| EC-16 | Recover completed payout | 409 | Status terminal check |
| EC-17 | Recover twice | 409 | Status terminal check |
| EC-18 | Advance bank failure | 200 | Reset `advance_payout_id` on sales |
| EC-19 | Withdraw with negative balance | 400 | Balance check |
| EC-20 | User+wallet partial failure | — | Single transaction |
