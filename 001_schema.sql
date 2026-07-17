-- =============================================================================
-- Payout Management System — Database Schema
-- =============================================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  email       TEXT NOT NULL UNIQUE,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Wallets: one per user, holds the withdrawable balance
-- Balance can go negative (represents debt owed by user, e.g. full rejection clawback)
CREATE TABLE IF NOT EXISTS wallets (
  id                    TEXT PRIMARY KEY,
  user_id               TEXT NOT NULL UNIQUE,
  withdrawable_balance  REAL NOT NULL DEFAULT 0,
  last_withdrawal_at    TEXT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Payouts: every money movement is recorded here for a full audit trail
-- Types: advance | final | withdrawal | recovery
-- Status lifecycle: initiated → processing → completed
--                                          → failed | cancelled | rejected
CREATE TABLE IF NOT EXISTS payouts (
  id              TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,
  type            TEXT NOT NULL CHECK(type IN ('advance', 'final', 'withdrawal', 'recovery')),
  amount          REAL NOT NULL,
  status          TEXT NOT NULL DEFAULT 'initiated'
                    CHECK(status IN ('initiated', 'processing', 'completed', 'cancelled', 'rejected', 'failed')),
  notes           TEXT,
  failure_reason  TEXT,
  initiated_at    TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at    TEXT,
  failed_at       TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Sales: the source of truth for affiliate sales
-- advance_payout_id IS NULL → not yet advanced (eligible for advance)
-- advance_payout_id IS NOT NULL → advance already initiated for this sale (idempotency guard)
-- final_payout_id IS NULL → not yet in a final payout
CREATE TABLE IF NOT EXISTS sales (
  id                  TEXT PRIMARY KEY,
  user_id             TEXT NOT NULL,
  brand               TEXT NOT NULL CHECK(brand IN ('brand_1', 'brand_2', 'brand_3')),
  status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'approved', 'rejected')),
  earning             REAL NOT NULL CHECK(earning > 0),
  advance_paid        REAL NOT NULL DEFAULT 0 CHECK(advance_paid >= 0),
  advance_payout_id   TEXT,
  final_payout_id     TEXT,
  reconciled_at       TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (user_id)           REFERENCES users(id),
  FOREIGN KEY (advance_payout_id) REFERENCES payouts(id),
  FOREIGN KEY (final_payout_id)   REFERENCES payouts(id)
);

-- Payout ↔ Sale mapping: tracks exactly which sales contributed to each payout
-- Useful for audit, reconciliation, and debugging
CREATE TABLE IF NOT EXISTS payout_sale_mappings (
  id                  TEXT PRIMARY KEY,
  payout_id           TEXT NOT NULL,
  sale_id             TEXT NOT NULL,
  contribution_amount REAL NOT NULL,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (payout_id) REFERENCES payouts(id),
  FOREIGN KEY (sale_id)   REFERENCES sales(id),
  UNIQUE(payout_id, sale_id)
);

-- =============================================================================
-- Indexes
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_sales_user_id          ON sales(user_id);
CREATE INDEX IF NOT EXISTS idx_sales_status           ON sales(status);
CREATE INDEX IF NOT EXISTS idx_sales_user_status      ON sales(user_id, status);
CREATE INDEX IF NOT EXISTS idx_sales_advance_payout   ON sales(advance_payout_id);
CREATE INDEX IF NOT EXISTS idx_sales_final_payout     ON sales(final_payout_id);
CREATE INDEX IF NOT EXISTS idx_payouts_user_id        ON payouts(user_id);
CREATE INDEX IF NOT EXISTS idx_payouts_status         ON payouts(status);
CREATE INDEX IF NOT EXISTS idx_payouts_type           ON payouts(type);
CREATE INDEX IF NOT EXISTS idx_psm_payout_id          ON payout_sale_mappings(payout_id);
CREATE INDEX IF NOT EXISTS idx_psm_sale_id            ON payout_sale_mappings(sale_id);

-- Constraint and index audit complete
