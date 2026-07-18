# Affiliate Payout Management System

A production-grade Low-Level Design and implementation for managing affiliate sales payouts — including advance disbursement, post-reconciliation final payouts, withdrawal rate-limiting, and failed payout recovery.

---

## Table of Contents

- [Problem Summary](#problem-summary)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Running Tests](#running-tests)
- [API Reference](#api-reference)
- [Documentation](#documentation)

---

## Problem Summary

| Question | What it solves |
|---|---|
| **Q1 – Payout Management** | Advance 10% of pending sale earnings → admin reconciles → calculate final payout with clawback for rejected sales → enforce one withdrawal per 24 hours |
| **Q2 – Failed Payout Recovery** | When a bank transfer (withdrawal) fails/is cancelled/rejected, automatically credit the amount back to the user's wallet and allow re-withdrawal |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          HTTP Layer                             │
│  POST /sales   POST /sales/reconcile   POST /payouts/advance   │
│  POST /payouts/final   POST /wallet/:id/withdraw               │
│  PATCH /payouts/:id/status                                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                       Service Layer                             │
│                                                                 │
│  AdvancePayoutService   ReconciliationService                   │
│  FinalPayoutService     WithdrawalService                       │
│  PayoutRecoveryService                                          │
│                                                                 │
│  (all business rules, validations, and atomic transactions      │
│   live here — controllers are intentionally thin)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     Repository Layer                            │
│                                                                 │
│  UserRepository   WalletRepository                             │
│  SaleRepository   PayoutRepository                             │
│                                                                 │
│  (pure data access — zero business logic)                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     SQLite Database                             │
│                                                                 │
│  users  wallets  sales  payouts  payout_sale_mappings           │
└─────────────────────────────────────────────────────────────────┘
```

### End-to-End Payout Flow

```
[Sale Created: pending]
        │
        ▼
[Advance Payout Job runs]
  → 10% of earning credited to wallet
  → sale.advance_payout_id set (idempotency guard)
        │
        ▼
[Admin Reconciles]
  → pending → approved / rejected
        │
        ▼
[Final Payout runs]
  → approved: earning − advance_paid  → wallet +
  → rejected: −advance_paid           → wallet − (clawback)
        │
        ▼
[User Initiates Withdrawal]
  → 24-hr cooldown checked
  → wallet debited, bank transfer initiated (status: processing)
        │
        ├─── Bank confirms ──→ status: completed ✓
        │
        └─── Bank fails ─────→ PayoutRecoveryService
                                  → amount credited back to wallet
                                  → cooldown reset
                                  → user can retry
```

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11 | High productivity, modern typing, built-in Decimal |
| Framework | FastAPI | Async/sync routing, automatic OpenAPI docs, fast performance |
| Database | SQLite via `sqlite3` | Zero-setup, WAL mode, foreign keys enabled, easy transaction control |
| Validation | Pydantic v2 | Robust schema validation and type checking |
| Testing | pytest | Standard Python testing framework |

---

## Project Structure

```
PayFlow/
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI app + DI wiring + all routers
│   ├── db/
│   │   ├── __init__.py
│   │   └── database.py                # get_db_connection(), init_db()
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base_repository.py         # BaseRepository with find_by_id, find_all
│   │   ├── user_repository.py
│   │   ├── wallet_repository.py       # credit(), debit(), set_last_withdrawal_at()
│   │   ├── sale_repository.py         # find_eligible_for_advance(), mark_advance_paid()
│   │   └── payout_repository.py       # add_sale_mapping(), get_sale_mappings()
│   ├── services/
│   │   ├── __init__.py
│   │   ├── advance_service.py         # AdvancePayoutService.process_advance()
│   │   ├── reconciliation_service.py  # ReconciliationService.reconcile_batch()
│   │   ├── final_payout_service.py    # FinalPayoutService.process_final_payout()
│   │   ├── withdrawal_service.py      # WithdrawalService.initiate_withdrawal()
│   │   └── recovery_service.py        # PayoutRecoveryService.update_payout_status()
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── users.py
│   │   ├── sales.py
│   │   ├── payouts.py
│   │   └── wallet.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── requests.py                # Pydantic request bodies
│   │   └── responses.py               # Pydantic response models
│   └── utils/
│       ├── __init__.py
│       ├── errors.py                  # AppError, NotFoundError, ConflictError, etc
│       ├── financial.py               # ADVANCE_RATE, round_to_2dp(), calc_advance(), calc_final_for_sale()
│       └── id_generator.py            # generate_id() using uuid4
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # in-memory SQLite fixtures, repo + service factories
│   ├── test_advance_service.py
│   ├── test_reconciliation_service.py
│   ├── test_final_payout_service.py
│   ├── test_withdrawal_service.py
│   ├── test_recovery_service.py
│   └── test_integration_flow.py       # full end-to-end assignment scenario
├── 001_schema.sql
├── seed.py
├── requirements.txt
├── README.md
├── LLD.md
├── SCHEMA.md
├── API.md
├── EDGE_CASES.md
├── DESIGN_DECISIONS.md
├── CLASS_DESIGN.md
├── .gitignore
└── .env.example
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the application
uvicorn app.main:app --reload

# 3. Seed example assignment data
python seed.py
```

---

## Running Tests

```bash
pytest
```

Tests use an **in-memory SQLite database** — fully isolated between test runs.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/users` | Create a user |
| `GET` | `/api/users` | List all users |
| `GET` | `/api/users/{id}` | Get user details |
| `POST` | `/api/sales` | Create a sale |
| `GET` | `/api/sales?userId=` | List sales |
| `POST` | `/api/sales/reconcile` | Admin: batch reconcile sales |
| `POST` | `/api/payouts/advance/{userId}` | Run advance payout for a user |
| `POST` | `/api/payouts/final/{userId}` | Run final payout after reconciliation |
| `GET` | `/api/payouts?userId=` | List payouts for a user |
| `GET` | `/api/payouts/{id}` | Get payout details + sale mappings |
| `PATCH` | `/api/payouts/{id}/status` | Update payout status (gateway callback) |
| `GET` | `/api/wallet/{userId}` | Get wallet balance |
| `POST` | `/api/wallet/{userId}/withdraw` | Initiate a withdrawal |

See [`API.md`](API.md) for full request/response shapes and curl examples.

---

## Documentation

| Document | What it covers |
|---|---|
| [`LLD.md`](LLD.md) | Architecture, entity design, state machines, data flows |
| [`SCHEMA.md`](SCHEMA.md) | Database schema with rationale |
| [`API.md`](API.md) | Full API specification + curl examples |
| [`EDGE_CASES.md`](EDGE_CASES.md) | Edge cases & failure scenarios |
| [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) | Trade-offs & design decisions |
| [`CLASS_DESIGN.md`](CLASS_DESIGN.md) | Comprehensive class diagram & object hierarchy |
