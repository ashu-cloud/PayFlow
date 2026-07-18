# Database Schema

## Entity-Relationship Overview

```
users ──────────────── wallets (1:1)
  │
  ├── sales (1:N)
  │     │
  │     ├── advance_payout_id ──→ payouts
  │     └── final_payout_id   ──→ payouts
  │
  └── payouts (1:N)
        │
        └── payout_sale_mappings (1:N) ──→ sales
```

---

## Table Definitions

### `users`

```sql
CREATE TABLE users (
  id         TEXT PRIMARY KEY,                          -- UUIDv4
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Nothing unusual here. Email is UNIQUE — used to prevent duplicate accounts and for login lookups.

---

### `wallets`

```sql
CREATE TABLE wallets (
  id                   TEXT PRIMARY KEY,
  user_id              TEXT NOT NULL UNIQUE,            -- enforces 1:1 with users
  withdrawable_balance REAL NOT NULL DEFAULT 0,         -- CAN be negative (debt)
  last_withdrawal_at   TEXT,                            -- NULL = never withdrawn
  created_at           TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at           TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

**Design notes:**
- `withdrawable_balance` is not constrained to `>= 0`. If all of a user's sales are rejected after an advance was paid, the clawback can exceed the current balance. We represent this as a negative balance (a debt) rather than blocking the final payout calculation.
- `last_withdrawal_at` being `NULL` means the user has never withdrawn; this is treated as "eligible to withdraw now" rather than an error.
- `ON DELETE CASCADE`: deleting a user automatically removes their wallet.

---

### `payouts`

```sql
CREATE TABLE payouts (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL,
  type           TEXT NOT NULL CHECK(type IN ('advance', 'final', 'withdrawal', 'recovery')),
  amount         REAL NOT NULL,
  status         TEXT NOT NULL DEFAULT 'initiated'
                   CHECK(status IN ('initiated','processing','completed','cancelled','rejected','failed')),
  notes          TEXT,                                  -- JSON metadata
  failure_reason TEXT,
  initiated_at   TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at   TEXT,                                  -- NULL until terminal success
  failed_at      TEXT,                                  -- NULL until terminal failure
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

**Why a single `payouts` table for all types?**

All money movements share the same shape: who, how much, what type, what status. A single table means:
- One place to query "all money movements for user X."
- One place to check for failed payouts (Q2).
- Simpler recovery logic (every payout is recoverable by the same service).

The `type` discriminator tells you the purpose; `payout_sale_mappings` links it to the source sales where relevant.

**Payout types:**
| Type | Description |
|---|---|
| `advance` | 10% of pending sale earnings disbursed upfront |
| `final` | Net settlement after reconciliation |
| `withdrawal` | User transferring wallet balance to bank |
| `recovery` | Amount credited back after a failed withdrawal |

---

### `sales`

```sql
CREATE TABLE sales (
  id                TEXT PRIMARY KEY,
  user_id           TEXT NOT NULL,
  brand             TEXT NOT NULL CHECK(brand IN ('brand_1', 'brand_2', 'brand_3')),
  status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK(status IN ('pending', 'approved', 'rejected')),
  earning           REAL NOT NULL CHECK(earning > 0),
  advance_paid      REAL NOT NULL DEFAULT 0,            -- amount advanced for THIS sale
  advance_payout_id TEXT,                               -- NULL = advance not yet paid
  final_payout_id   TEXT,                               -- NULL = final not yet settled
  reconciled_at     TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id)           REFERENCES users(id),
  FOREIGN KEY (advance_payout_id) REFERENCES payouts(id),
  FOREIGN KEY (final_payout_id)   REFERENCES payouts(id)
);
```

**The idempotency guard — `advance_payout_id`:**

This is the most important column in the schema. The advance payout service does:

```sql
UPDATE sales
SET advance_payout_id = :payoutId, advance_paid = :amount
WHERE id = :saleId
  AND advance_payout_id IS NULL    -- ← THE GUARD
  AND status = 'pending'
```

- If `advance_payout_id IS NULL` → this sale has never received an advance → set it.
- If `advance_payout_id IS NOT NULL` → already paid → 0 rows updated → skip.

No separate "advance_paid" boolean flag needed; the FK itself is the flag.

**Why store `advance_paid` per sale (not just total on payout)?**

The final payout must calculate `earning − advance_paid` per sale. We need the per-sale figure, not the batch total, to compute the correct clawback for each rejected sale.

---

### `payout_sale_mappings`

```sql
CREATE TABLE payout_sale_mappings (
  id                  TEXT PRIMARY KEY,
  payout_id           TEXT NOT NULL,
  sale_id             TEXT NOT NULL,
  contribution_amount REAL NOT NULL,   -- how much this sale contributed to this payout
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (payout_id) REFERENCES payouts(id),
  FOREIGN KEY (sale_id)   REFERENCES sales(id),
  UNIQUE(payout_id, sale_id)
);
```

**Purpose:** Full audit trail. For any payout, you can reconstruct exactly which sales it covered and what each contributed. This is critical for:
- Debugging incorrect payout amounts.
- Finance team reconciliation.
- Regulatory compliance / audit requests.

`UNIQUE(payout_id, sale_id)` prevents the same sale from being credited twice to the same payout even if a bug triggers the mapping insert twice.

---

## Indexes

```sql
-- Hot query paths
CREATE INDEX idx_sales_user_id         ON sales(user_id);
CREATE INDEX idx_sales_status          ON sales(status);
CREATE INDEX idx_sales_advance_payout  ON sales(advance_payout_id);   -- eligibility check
CREATE INDEX idx_sales_final_payout    ON sales(final_payout_id);     -- eligibility check
CREATE INDEX idx_payouts_user_id       ON payouts(user_id);
CREATE INDEX idx_payouts_status        ON payouts(status);
CREATE INDEX idx_payouts_type          ON payouts(type);
CREATE INDEX idx_psm_payout_id         ON payout_sale_mappings(payout_id);
CREATE INDEX idx_psm_sale_id           ON payout_sale_mappings(sale_id);
```

**Index rationale:**

| Index | Query it serves |
|---|---|
| `sales(user_id)` | Fetching all sales / eligible-for-advance sales for a user |
| `sales(advance_payout_id)` | Finding sales to reset when an advance payout fails |
| `sales(final_payout_id)` | Checking which sales are already in a final payout |
| `payouts(user_id)` | Listing all payouts for a user |
| `payouts(status)` | Finding all failed payouts for recovery (admin dashboard) |
| `psm(payout_id)` | Loading the sale breakdown for a payout |

---

## Constraints Summary

| Constraint | Table.Column | Enforces |
|---|---|---|
| `PRIMARY KEY` | all tables `.id` | uniqueness |
| `UNIQUE` | `wallets.user_id` | one wallet per user |
| `UNIQUE` | `users.email` | no duplicate accounts |
| `UNIQUE` | `payout_sale_mappings(payout_id, sale_id)` | no duplicate mapping |
| `CHECK` | `sales.brand` | only known brands accepted |
| `CHECK` | `sales.status` | only valid status values |
| `CHECK` | `sales.earning > 0` | earnings must be positive |
| `CHECK` | `payouts.type` | only known payout types |
| `CHECK` | `payouts.status` | only valid status transitions |
| `FOREIGN KEY` | `sales.advance_payout_id → payouts.id` | referential integrity |
| `ON DELETE CASCADE` | `wallets.user_id → users.id` | auto-clean wallet on user delete |
