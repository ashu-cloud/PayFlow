# Design Decisions & Trade-offs

This document explains the non-obvious choices made in the design, what alternatives were considered, and what the right answer would be in a production system.

---

## DD-1: Idempotency via FK column, not a status flag

**Decision:** Use `sales.advance_payout_id IS NULL` as the eligibility check for advance payouts rather than a boolean `advance_paid` flag.

**Reasoning:**
A FK column gives you two things for the price of one:
1. The idempotency guard (NULL = not yet paid)
2. A direct reference to the payout that paid it (for audit and recovery)

A boolean flag would require a separate JOIN to find which payout covered this sale. The FK column encodes the relationship directly.

**Alternative considered:** A separate `advance_state` enum (`ELIGIBLE | INITIATED | PAID`). This is more expressive but adds complexity without benefit here since the payout reference already implies the state.

---

## DD-2: Wallet as an intermediate ledger

**Decision:** Introduce a `wallets` table that holds a `withdrawable_balance`. Advance payouts and final payouts credit this balance; withdrawals debit it.

**Reasoning:**
Without a wallet, the system would need to calculate a user's balance by summing all payout amounts every time a withdrawal is requested. That's a full table scan on `payouts` for every withdrawal — expensive and fragile.

A wallet table acts as a **materialized balance** — a pre-computed aggregate that is updated atomically with each money movement. This is the standard pattern in fintech (double-entry bookkeeping at a simplified level).

**Production extension:** In a real system, the wallet balance would be verified on every read against a reconciliation of all payout records (a "balance audit job") to detect any corruption.

---

## DD-3: Debit wallet on withdrawal initiation, not on bank confirmation

**Decision:** When a withdrawal is initiated, the wallet is debited immediately and the payout is created with status `processing`. The bank transfer happens asynchronously.

**Reasoning:**
This prevents double-spend. If we only debit on bank confirmation, a user could fire N concurrent withdrawal requests, all see a positive balance, and all succeed — resulting in a balance of −N×amount.

By debiting immediately (inside a serialised transaction), the second concurrent request sees an insufficient balance (or is blocked by the write lock) and fails. The amount is "reserved" in-flight.

If the bank later rejects the transfer, PayoutRecoveryService credits the amount back. The net effect is correct in all cases.

**Alternative considered:** Optimistic locking with a `version` column on `wallets`. This works but adds complexity; SQLite's write serialisation makes it unnecessary here.

---

## DD-4: Single `payouts` table for all payout types

**Decision:** Use one table with a `type` discriminator (`advance | final | withdrawal | recovery`) instead of separate tables per type.

**Reasoning:**
All payout types share the same shape: user, amount, status, timestamps. A single table means:
- One place to query "show me all money movements for user X."
- One place for Q2 recovery logic (it handles any payout type with a failure status).
- Simpler joins for the audit trail.

**Trade-off:** The `notes` column carries JSON metadata that varies per type. In a large system, this could become a pain point if you need to query on type-specific metadata. The fix would be a `payout_metadata` side-table or per-type sub-tables with shared PK.

---

## DD-5: `payout_sale_mappings` as a separate audit table

**Decision:** Maintain a join table recording which sales contributed to each payout, and the contribution amount.

**Reasoning:**
This provides a full audit trail. Without it, a finance team member would have to reconstruct which sales were in a final payout by looking at `sales.final_payout_id` — which only shows the latest payout, not intermediate states. The mapping table also supports the case where a sale contributes different amounts to different payouts (advance vs. final).

**Production benefit:** Regulatory requirements (RBI/SEBI for Indian fintechs) typically mandate maintaining an immutable audit log of all financial transactions. This table is the beginning of that log.

---

## DD-6: Batch reconciliation with per-item error collection

**Decision:** `reconcileBatch` processes each reconciliation independently and collects errors, rather than failing fast.

**Reasoning:**
An admin reconciling 100 sales should not have the entire operation fail because one sale ID in the batch is a typo. They want to know which 99 succeeded and which 1 failed, so they can fix and retry just the failure.

The `rollbackOnError: true` option gives them atomic all-or-nothing semantics when they explicitly need it.

---

## DD-7: Negative wallet balance (debt) instead of blocking

**Decision:** Allow `withdrawable_balance` to go negative rather than blocking the final payout when clawback > current balance.

**Reasoning:**
Blocking the final payout would leave the system in an irresolvable state: the system knows the user owes money but has no mechanism to collect it. Allowing negative balances means:
1. The system correctly records the debt.
2. Future earnings (from new approved sales) automatically offset the debt.
3. The user cannot withdraw while in debt (the balance check prevents it).

**Alternative considered:** Create a separate `debts` table. This is cleaner conceptually but adds a parallel accounting system. For the scale of this assignment, a signed balance is sufficient.

---

## DD-8: SQLite over PostgreSQL

**Decision:** Use SQLite for this assignment.

**Reasoning:**
SQLite requires zero infrastructure setup (no server, no credentials). This makes the assignment trivially runnable by the reviewer. The schema, transaction semantics, and indexing are identical to PostgreSQL — swapping the database requires only changing the connection driver.

**Production recommendation:** Use PostgreSQL with the following changes:
- Replace `better-sqlite3` with `pg` or `Prisma`.
- `REAL` → `NUMERIC(12, 2)` for precise decimal storage.
- `TEXT` dates → `TIMESTAMPTZ`.
- Add `FOR UPDATE SKIP LOCKED` on the withdrawal query for proper row-level locking.
- Add `SELECT ... FOR UPDATE` on wallet reads inside withdrawal transaction.
- Separate read replicas for `GET` endpoints.

---

## DD-9: Storing amounts as REAL instead of integer (paisa)

**Decision:** Store amounts as REAL (float) with application-level rounding.

**Reasoning:**
The assignment amounts (₹40, ₹30, etc.) are simple enough that IEEE 754 errors don't manifest. Explicit `roundTo2dp()` at every calculation boundary and SQLite's `ROUND(expr, 2)` in UPDATE statements provide sufficient protection.

**Production recommendation:** Store all amounts as `INTEGER` in paisa (1 rupee = 100 paisa). Convert to decimal only at the API serialisation boundary. This eliminates floating-point error entirely and makes all arithmetic exact.

```
₹40.00 → store as 4000 (paisa)
10% → 400 paisa = ₹4.00 exactly
```

---

## DD-10: No authentication layer

**Decision:** The admin reconcile endpoint and payout endpoints have no auth.

**Reasoning:**
Adding JWT or API-key auth would make the assignment harder to run without adding to the system design. The design explicitly separates admin endpoints (reconcile) from user endpoints (withdraw), and the code is structured so adding auth middleware is a one-line change per route.

**Production requirement:** Admin endpoints must be protected by role-based access control (RBAC). User endpoints must authenticate the user and assert `params.userId === req.user.id` to prevent one user from triggering payouts for another.

---

## Production Readiness Checklist

| Concern | Current State | Production Fix |
|---|---|---|
| Decimal precision | REAL + rounding | Store as INTEGER (paisa) |
| Database | SQLite | PostgreSQL with connection pool |
| Concurrency | SQLite write serialisation | PostgreSQL `SELECT FOR UPDATE` |
| Auth | None | JWT + RBAC middleware |
| Async bank transfers | Mocked synchronously | Webhook receiver + queue (BullMQ/SQS) |
| Idempotency keys | DB-level FK guard | + API-level idempotency header |
| Rate limiting | 24-hr DB check | + Redis-based rate limiter for API |
| Observability | Winston logs | OpenTelemetry traces + metrics |
| Audit log | `payout_sale_mappings` | Immutable append-only event log |
| Retry logic | Manual | Exponential backoff on bank transfer failures |
| Soft deletes | Hard deletes | Add `deleted_at` columns |
