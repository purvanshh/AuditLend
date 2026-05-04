# AuditLend: Comprehensive Study Guide

This document provides a deep technical breakdown of AuditLend, an audit-grade credit decision engine built with FastAPI, PostgreSQL, Redis, and Celery.

---

# 1. Project Overview

## What the Project Does

AuditLend is a deterministic, idempotent loan application processing system that decides whether to approve, decline, or route applications to manual review. It preserves a complete compliance trail explaining every decision.

**Core functionality:**
- Receives loan applications via REST API with encrypted PII
- Asynchronously processes applications via Celery workers
- Fetches external data from three mock providers (credit bureau, bank analyzer, GST verifier)
- Computes a weighted risk score (0-100) using immutable rule sets
- Calculates calibrated confidence based on data reliability and risk-score boundary distance
- Routes low-confidence decisions to manual review
- Stores immutable audit logs for every step of processing

## Core Problem It Solves

Lending decisions must survive:
- Worker crashes and restarts (idempotency)
- Third-party service outages (fallbacks, circuit breakers)
- Regulatory scrutiny (immutable audit trails)
- Duplicate submissions (idempotency keys)
- Data quality degradation (confidence scoring)

## Key Features and Capabilities

| Feature | Implementation |
|---------|---------------|
| Idempotent intake | Redis fast-path + PostgreSQL durable fallback with payload hash verification |
| Encrypted PII storage | AES-256-GCM for user data, salted SHA-256 for PAN |
| Immutable audit logs | Append-only table with database trigger protection |
| Deterministic scoring | Immutable rule sets (dataclasses), no randomness in business logic |
| Calibrated confidence | Separates `data_reliability` (failure penalties) from `confidence` (includes boundary factor) |
| Manual review routing | Confidence threshold override (default 0.6) |
| Circuit breaker | Redis-backed state machine: CLOSED → OPEN → HALF_OPEN with single-probe lock |
| External data reuse | Worker retries fetch from DB instead of re-calling providers |
| Transactional outbox | Application + outbox message committed in single transaction |

---

# 2. High-Level Architecture

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                               CLIENT                                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ POST /api/v1/apply-loan
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          FastAPI API (port 8000)                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ Routes: /apply-loan, /status/{id}, /decision/{id}, /explanation │   │
│  │ Middleware: CORS, request logging, Prometheus instrumentation   │   │
│  │ Auth: API key validation (X-API-Key header)                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└──────┬──────────────────────────────┬──────────────────────────────────┘
       │                              │
       ▼                              ▼
┌──────────────┐              ┌─────────────────┐
│ PostgreSQL   │              │ Redis           │
│ - loan_apps  │              │ - idempotency   │
│ - idempotent │              │   cache         │
│ - outbox     │              │ - circuit state │
│ - external   │              │ - Celery broker  │
│ - audit_logs │              │   & results     │
└──────┬───────┘              └────────┬────────┘
       │                               │
       │                               │ async task dispatch
       ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Celery Worker (port 8004)                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ Outbox poller → claims PENDING apps atomically                 │   │
│  │ Fetches/reuses external data → computes decision → stores      │   │
│  │ Writes audit entries at every step                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└──────┬──────────────────────────────┬──────────────────────────────────┘
       │                              │                              │
       ▼                              ▼                              ▼
┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│ Credit Bureau │  │ Bank Analyzer  │  │ GST Verifier     │
│ Mock (8001)   │  │ Mock (8002)     │  │ Mock (8003)       │
└────────────────┘  └─────────────────┘  └──────────────────┘
```

## Component Interaction Flow

1. **API receives application**: Validates, encrypts PII, stores in PostgreSQL, writes outbox message, caches idempotency in Redis
2. **Outbox poller** (running in worker): Picks up PENDING messages, dispatches Celery tasks
3. **Celery task**: Atomically claims application, fetches external data (reusing if already exists), computes decision, writes audit entries, updates application status
4. **External services**: Called via retryable HTTP with circuit breaker protection
5. **Client queries**: Status, decision, and explanation endpoints read from PostgreSQL, explanation is built from audit trail (not recomputed)

---

# 3. Why This Architecture?

## Why This Architecture Was Chosen

| Decision | Rationale |
|----------|------------|
| **Synchronous API + async worker** | Loan processing involves multiple external calls that would block API threads. Offloading to Celery improves API responsiveness and allows independent scaling. |
| **PostgreSQL for all persistent state** | Single source of truth for audit trail (append-only requirement). Idempotency, applications, and external data all benefit from relational integrity and transactions. |
| **Redis for idempotency cache** | 24-hour TTL provides fast-path lookups avoiding DB round-trips. Falls back to PostgreSQL when Redis is unavailable. |
| **Transactional outbox** | Ensures application record and task dispatch are committed atomically. No lost tasks even if worker crashes between commit and dispatch. |
| **Immutable rule sets as dataclasses** | Frozen dataclasses prevent accidental modification. Version strings in output allow auditing which rules produced each decision. |
| **Circuit breaker on external services** | Prevents cascade failures when third-party services are down. Half-open state allows recovery testing. |

## Trade-offs

| Trade-off | Impact |
|-----------|--------|
| **Celery adds latency** | Decision not available immediately; requires polling status endpoint. Acceptable for loan processing where minutes matter, not seconds. |
| **PostgreSQL not optimal for audit queries** | Audit log queries for explanation builder do full table scans. Could use time-series DB or audit-specific indices. |
| **Redis circuit state is per-instance** | In multi-worker deployment, circuit state is shared via Redis (correct). But if Redis is down, circuit defaults to CLOSED (safe fallback). |
| **Encryption key management** | 64-char hex key must be rotated manually. No built-in key rotation mechanism. |

## When This Architecture Fails or Becomes Inefficient

- **High-throughput real-time decisioning**: Synchronous processing needed; Celery adds 1-5 second latency. Consider direct service calls or async workers with WebSocket notifications.
- **Multi-region deployment**: PostgreSQL cross-region replication adds latency. Circuit breaker state in Redis needs carefulhaoping.
- **Massive audit log queries**: Explanation endpoint reads audit trail linearly. With millions of applications, this becomes slow. Need audit log partitioning or pre-computed explanations.
- **True horizontal worker scaling**: Outbox poller uses `FOR UPDATE SKIP LOCKED`, which works but introduces task ordering non-determinism. Consider dedicated queue per priority.

---

# 4. Tech Stack Breakdown

## Core Technologies

| Component | Technology | Version/Notes |
|-----------|------------|---------------|
| API Framework | FastAPI | v2.0.0 |
| Worker | Celery | with Redis broker |
| Database | PostgreSQL | 15+ with UUID, JSONB, array types |
| Cache/Broker | Redis | Used for idempotency, circuit breaker, Celery |
| Encryption | cryptography (AES-GCM) | 256-bit key from env |
| Hashing | hashlib (SHA-256) | Salted PAN hash from env |
| Metrics | prometheus_client | Exposed at /metrics |
| Logging | structlog | JSON formatted |
| ORM | SQLAlchemy | 2.x with async support |
| Migrations | Alembic | Versioned migrations |
| Testing | pytest | with coverage gate at 85% |

## Why Each Was Chosen

- **FastAPI**: Native async support, automatic OpenAPI docs, easy dependency injection, Pydantic validation.
- **PostgreSQL**: JSONB for flexible schemas (failure_flags, external data), UUID for application IDs, constraint triggers for audit immutability.
- **Redis**: Single tool for three concerns (cache, broker, state). TTL-based expiration simplifies idempotency key management.
- **Celery**: Mature, supports retry with backoff, integrates with Redis, task routing capabilities.
- **structlog**: Structured logging essential for debugging distributed systems; JSON output works with any log aggregator.
- **cryptography library**: Standard Python crypto; AES-GCM provides authenticated encryption (detects tampering).

## Alternative Technologies Considered

| Alternative | Why Not Chosen |
|-------------|----------------|
| MongoDB | Audit append-only constraint more naturally enforced in RDBMS; JSONB sufficient for flexibility |
| Kafka | Overkill for task queue; Celery sufficient and simpler |
| RabbitMQ | More complex setup; Redis sufficient for this scale |
| gRPC | Not needed for internal service communication; REST more accessible |
| GraphQL | Overkill; simple REST API sufficient for loan intake |
| JWT for auth | API key sufficient for service-to-service; OAuth2 would be needed for end-user |

---

# 5. Folder & Code Structure Deep Dive

## Directory Structure

```
AuditLend/
├── api/                    # FastAPI application
│   ├── main.py            # App factory, middleware, exception handlers
│   ├── auth.py            # API key validation
│   ├── dependencies.py    # FastAPI dependency injection (DB session)
│   ├── routes/
│   │   ├── applications.py   # POST /apply-loan, GET /status
│   │   ├── decisions.py      # GET /decision
│   │   └── explanations.py   # GET /explanation
│   └── schemas/
│       ├── application.py    # Pydantic request/response models
│       ├── decision.py       # Decision response schema
│       └── explanation.py   # Explanation response schema
│
├── engine/                 # Pure business logic (no I/O, no side effects)
│   ├── scoring.py         # Weighted risk score computation (0-100)
│   ├── rule_sets.py      # Immutable RuleSet dataclass definitions
│   ├── rules.py          # Decision evaluation (APPROVE/DECLINE/NEEDS_REVIEW)
│   ├── confidence.py     # Data reliability + calibrated confidence
│   ├── decision.py       # Orchestration: extract → score → decide → confiden
│   └── explanation_builder.py  # Builds human-readable explanation from audit
│
├── services/              # External integrations and utilities
│   ├── base.py           # BaseExternalService with circuit breaker
│   ├── credit_bureau.py # Credit bureau client (fallback credit_score=600)
│   ├── bank_analyzer.py  # Bank statement analyzer client
│   ├── gst_verifier.py  # GST compliance verifier client
│   ├── crypto.py        # AES-256-GCM encryption, SHA-256 PAN hashing
│   ├── audit.py         # Append-only audit log writing
│   ├── metrics.py       # Prometheus metric definitions
│   ├── logging.py       # structlog setup
│   └── __init__.py      # FailureType enum, ServiceResult dataclass
│
├── worker/               # Celery worker
│   ├── celery_app.py    # Celery application configuration
│   ├── outbox_poller.py # Polls outbox table, dispatches tasks
│   └── tasks/
│       └── process_application.py  # Main task: claim → fetch → decide → store
│
├── models/               # SQLAlchemy ORM models
│   ├── application.py   # loan_applications table
│   ├── idempotency.py  # idempotency_records table
│   ├── external_data.py # external_data table (reused provider responses)
│   ├── outbox.py       # outbox table (transactional task dispatch)
│   ├── audit_log.py    # audit_logs table (append-only)
│   └── __init__.py
│
├── db/
│   ├── base.py         # SQLAlchemy declarative base
│   └── session.py     # Sync/async session factories
│
├── migrations/         # Alembic database migrations
│   └── versions/      # Migration files
│
├── mock_apis/          # Deterministic external service mocks
│   ├── credit_bureau.py
│   ├── bank_analyzer.py
│   ├── gst_verifier.py
│   └── run_all.py     # Combined mock server entry point
│
└── tests/
    ├── unit/          # Pure function tests (scoring, rules, confidence)
    ├── integration/   # DB + Redis required tests
    └── chaos/         # Idempotency, circuit breaker, worker crash tests
```

## Responsibility Matrix

| Module | Responsibility | Public API |
|--------|---------------|------------|
| `api/routes/applications.py` | HTTP intake, idempotency validation, PII encryption | `POST /apply-loan`, `GET /status/{id}` |
| `engine/scoring.py` | Compute weighted risk score from inputs | `compute_risk_score(credit_score, income_stability, dti, gst_compliant, failure_types)` |
| `engine/rules.py` | Evaluate decision rules in priority order | `evaluate(risk_score, dti, failure_types, gst_compliant)` |
| `engine/confidence.py` | Calculate data reliability and calibrated confidence | `compute_data_reliability()`, `compute_decision_confidence()` |
| `engine/decision.py` | Orchestrate full decision pipeline | `compute_decision(credit_result, bank_result, gst_result, user_data)` |
| `services/base.py` | HTTP calls with retry, circuit breaker | `BaseExternalService.call()` |
| `services/crypto.py` | Encrypt/decrypt PII, hash PAN | `PIIService.encrypt()`, `hash_pan()` |
| `services/audit.py` | Write audit entries, sanitize PII | `write_audit_entry()`, `audit_safe_features()` |
| `worker/tasks/process_application.py` | Claim, fetch, decide, store | `process_application(application_id)` |

## Connection Diagram

```
API routes           Engine                  Services                  Worker
    │                    │                        │                        │
    ├─ POST /apply       │                        │                        │
    │   ├─ crypto.encrypt()                    │                        │
    │   ├─ models/application                  │                        │
    │   ├─ models/outbox                       │                        │
    │   └─ redis cache                        │                        │
    │                    │                        │                        │
    │                    │ compute_decision() ◄───┼────────────────────────┤
    │                    │   ├─ scoring.compute_risk_score()               │
    │                    │   ├─ rules.evaluate()                          │
    │                    │   ├─ confidence.compute_data_reliability()     │
    │                    │   └─ confidence.compute_decision_confidence()│
    │                    │                        │                        │
    │                    │                        ├─ base.BaseExternalService.call()
    │                    │                        │   ├─ CreditBureauService.fetch()
    │                    │                        │   ├─ BankAnalyzerService.analyze()
    │                    │                        │   └─ GstVerifierService.verify()
    │                    │                        │        (circuit breaker, retries)
    │                    │                        │                        │
    │                    │                        ├─ audit.write_audit_entry()
    │                    │                        │        (immutable audit log)
    │                    │                        │                        │
    ├─ GET /decision ◄───┼────────────────────────┤                        │
    │   └─ audit_log SELECT                     │                        │
    │                    │                        │                        │
    ├─ GET /explanation─┬┴────────────────────────┤                        │
    │   └─ explanation_builder.build_from_audit()                        │
```

---

# 6. Core Workflows

## Workflow 1: Application Submission

```
Client                                    API                              PostgreSQL
 │                                          │                                   │
 │ POST /apply-loan                         │                                   │
 │ + Idempotency-Key: smoke-001             │                                   │
 │ + X-API-Key: dev-key-read-write         │                                   │
 │ + { user_data: {...}, failure_flags }   │                                   │
 │─────►                                    │                                   │
 │                                          │                                   │
 │           Check Redis idempotency cache  │                                   │
 │           Check PostgreSQL idempotency   │                                   │
 │           (both empty for new key)       │                                   │
 │                                          │                                   │
 │           pii_service.encrypt(user_data) │                                   │
 │           = (ciphertext, nonce)          │                                   │
 │                                          │                                   │
 │           hash_pan(pan)                  │                                   │
 │           = salted SHA-256               │                                   │
 │                                          │                                   │
 │           INSERT loan_applications       │──────►                            │
 │           INSERT outbox                  │──────► (transactional)            │
 │           INSERT idempotency_record      │──────►                            │
 │                                          │                                   │
 │           SETEX Redis idempotency cache  │                                   │
 │           (TTL 86400 seconds)            │                                   │
 │                                          │                                   │
 │  201 Created                             │                                   │
 │  { application_id: uuid, status: PENDING }◄────                             │
 │                                          │                                   │
```

**Key invariants**: 
- Idempotency key combined with request payload hash prevents duplicate creation
- Application + outbox in single transaction ensures no orphan outbox messages
- Raw PAN never stored; only encrypted blob + hash

## Workflow 2: Worker Processing

```
Worker                              DB                          External Services
 │                                    │                              │
 │ poll_outbox_once()                 │                              │
 │ SELECT PENDING outbox messages     │──────►                       │
 │   FOR UPDATE SKIP LOCKED          │                              │
 │                                    │                              │
 │ For each message:                  │                              │
 │   send_task(task_name, app_id)    │                              │
 │                                    │                              │
 │ process_application(app_id)       │                              │
 │                                    │                              │
 │ ┌─ Claim application               │                              │
 │ │ UPDATE loan_applications        │──────►                       │
 │ │   WHERE id=app_id                │                              │
 │ │   AND (status=PENDING            │                              │
 │ │        OR (status=PROCESSING     │                              │
 │ │            AND updated_at < stale))│                            │
 │ │ SET status=PROCESSING            │                              │
 │ │ RETURNING id                     │                              │
 │ │                                   │                              │
 │ └─ If claim fails:                 │                              │
 │    If terminal: return stored     │                              │
 │    If processing: return "claimed"│                              │
 │                                    │                              │
 │ ┌─ Fetch external data             │                              │
 │ │                                   │      ┌─ CreditBureauService │
 │ │ Check DB for existing results    │──────┼─ BankAnalyzerService │
 │ │ (re-use on retry)                │      └─ GstVerifierService │
 │ │                                   │                              │
 │ │ For each missing source:         │                              │
 │ │   call external service          │─────►│ HTTP GET               │
 │ │   (retry with backoff)           │      │                       │
 │ │   (circuit breaker checks)       │      │                       │
 │ │                                   │◄─────│ Response (or fallback)│
 │ │                                   │                              │
 │ │ Store in external_data table    │──────►                       │
 │ │ Write audit entry                │──────►                       │
 │ │                                   │                              │
 │ └─ Compute decision                │                              │
 │    decision = compute_decision()  │                              │
 │    risk_score, confidence, factors│                              │
 │                                    │                              │
 │ ┌─ Store results                   │                              │
 │ │ UPDATE loan_applications        │──────►                       │
 │ │   SET decision, confidence       │                              │
 │ │   SET status=(COMPLETED|MANUAL)  │                              │
 │ │                                   │                              │
 │ │ write_audit_entry(DECISION_CALC) │──────►                       │
 │ │ write_audit_entry(MANUAL_REVIEW) │──────► (if needed)           │
 │ │                                   │                              │
 │ └─ Return result dict              │                              │
 │                                    │                              │
```

**Idempotency mechanisms**:
1. Worker uses `FOR UPDATE` + stale lock detection to prevent duplicate processing
2. External data fetch checks DB first, reuses on retry
3. Terminal states (COMPLETED, MANUAL_REVIEW) are final; re-processing returns stored result

## Workflow 3: Explanation Generation

```
Client                              API                              DB
 │                                    │                                │
 │ GET /explanation/{application_id} │                                │
 │                                    │                                │
 │                              SELECT loan_applications              │
 │                              WHERE id = app_id                    │
 │                                    │──────►                        │
 │                              SELECT audit_logs                    │
 │                              WHERE application_id = app_id        │
 │                              ORDER BY created_at                  │
 │                                    │──────►                        │
 │                                    │                                │
 │            explanation_builder.build_explanation()                │
 │            (from audit trail, not recomputed)                     │
 │                                    │                                │
 │ Response:                          │                                │
 │ { decision, summary, factors[],   │                                │
 │   timeline: [{step, status, time}] }◄────                          │
 │                                    │                                │
```

**Critical**: Explanations are built from **audit trail**, not recomputed. This ensures the explanation reflects what actually happened (including fallbacks, failures) rather than what current code would produce.

---

# 7. Data Layer & State Management

## Database Schema

### `loan_applications` Table

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Primary key |
| idempotency_key | String(255) | Unique constraint |
| pan_hash | String(64) | Salted SHA-256 of PAN |
| encrypted_user_data | BYTEA | AES-256-GCM ciphertext |
| encryption_nonce | BYTEA | 12-byte nonce |
| status | String(20) | PENDING → PROCESSING → COMPLETED/MANUAL_REVIEW |
| decision | String(30) | APPROVE/DECLINE/NEEDS_REVIEW |
| confidence | NUMERIC(3,2) | 0.00 - 1.00 |
| failure_flags | JSONB | Injected failure modes for testing |
| created_at, updated_at | timestamptz | Audit timestamps |

**Indexes**: `idx_loan_status`, `idx_loan_idempotency`, `idx_loan_pan_hash`

### `audit_logs` Table

| Column | Type | Description |
|--------|------|-------------|
| id | BigInt (PK) | Auto-increment |
| application_id | UUID (FK) | References loan_applications |
| step | String(100) | PROCESSING_STARTED, *_FETCH, DECISION_CALCULATION, etc. |
| input_snapshot | JSONB | Sanitized input at this step |
| output_snapshot | JSONB | Sanitized output at this step |
| error_type | String(50) | FailureType if applicable |
| fallback_used | Boolean | True if fallback applied |
| fallback_reason | Text | Explanation of fallback |
| rule_version | String(20) | Which RuleSet used |
| actor | String(30) | "system" |
| created_at | timestamptz | When entry created |

**Immutability**: Database trigger blocks UPDATE/DELETE on this table.

**Indexes**: `idx_audit_app_step`

### `external_data` Table

| Column | Type | Description |
|--------|------|-------------|
| id | BigInt (PK) | Auto-increment |
| application_id | UUID (FK) | References loan_applications |
| source_type | String(30) | CREDIT_BUREAU, BANK_ANALYZER, GST_VERIFIER |
| request_params | JSONB | Request parameters (including fail_mode) |
| response_data | JSONB | Sanitized response data |
| failure_type | String(30) | FailureType if applicable |
| idempotency_key | String(255) | For deduplication |
| fetched_at | timestamptz | When fetched |

**Indexes**: `idx_external_data_app`, `uq_external_data_application_source` (unique)

### `idempotency_records` Table

| Column | Type | Description |
|--------|------|-------------|
| key | String(255) | Primary key (idempotency key) |
| application_id | UUID (FK) | References loan_applications |
| response | JSONB | Full response stored |
| created_at | timestamptz | When created |

### `outbox` Table

| Column | Type | Description |
|--------|------|-------------|
| id | BigInt (PK) | Auto-increment |
| task_name | String(255) | Celery task name |
| task_args | JSONB | Task arguments (application_id) |
| status | String(20) | PENDING → PROCESSED/FAILED |
| created_at | timestamptz | When created |
| processed_at | timestamptz | When dispatched |
| error_message | Text | Error if FAILED |

**Indexes**: `idx_outbox_status_created`

## Caching Strategy

| Cache | Key Pattern | TTL | Purpose |
|-------|-------------|-----|---------|
| Redis idempotency | `idempotent:{key}` | 86400s (1 day) | Fast-path duplicate detection |
| Redis circuit state | `circuit:{service}:state` | None (controlled) | CLOSED/OPEN/HALF_OPEN |
| Redis circuit failure count | `circuit:{service}:failure_count` | 60s window | Increment and expire |
| Redis half-open probe lock | `circuit:{service}:probe_lock` | 10s | Single-probe guarantee |

## State Machine for Application

```
                    ┌─────────┐
                    │ PENDING │
                    └────┬────┘
                         │ API creates
                         │ outbox message
                         ▼
┌──────────┐      ┌─────────────┐      ┌─────────────┐
│ COMPLETED│◄─────┤ PROCESSING  │─────►│ MANUAL_REVIEW│
└──────────┘      └─────────────┘      └──────────────┘
   (final)       (intermediate)            (final)
```

---

# 8. Key Design Patterns Used

## Pattern 1: Immutable Rule Sets (Strategy Pattern)

**Location**: `engine/rule_sets.py`

```python
@dataclass(frozen=True)
class RuleSet:
    version: str
    credit_weight: float = 40.0
    stability_weight: float = 20.0
    # ... more fields
```

**Why**: Frozen dataclass prevents accidental modification. Version string in output allows auditing. New rule sets are added as new dataclass instances, never mutated.

**Benefit**: Deterministic behavior, auditability, A/B testing capability (multiple RuleSets).

## Pattern 2: Transactional Outbox

**Location**: `api/routes/applications.py`, `models/outbox.py`

**Implementation**:
```python
# Single transaction
session.add(application)
session.add(OutboxMessage(task_name=..., task_args={...}))
session.commit()  # Both or neither
```

**Why**: Guarantees application + task dispatch atomicity. No lost tasks if crash between commit and dispatch.

## Pattern 3: Circuit Breaker (State Machine)

**Location**: `services/base.py`

**States**: CLOSED → OPEN → HALF_OPEN → (CLOSED on success, OPEN on failure)

**Key features**:
- Redis-backed (shared across workers)
- Failure count within window opens circuit
- Timeout transitions OPEN → HALF_OPEN
- Half-open uses `SET NX` for single-probe guarantee
- Non-retryable failures don't count against circuit

## Pattern 4: Idempotency with Dual Store

**Location**: `api/routes/applications.py`

**Fast path**: Redis (24-hour TTL)
**Durable path**: PostgreSQL (idempotency_records table)
**Validation**: SHA-256 hash of full request payload

**Why**: Redis is fast but can be lost (eviction, restart). PostgreSQL is durable but slower. Both must agree on payload hash to prevent response variation.

## Pattern 5: Immutable Audit Log with Sanitization

**Location**: `services/audit.py`

```python
def sanitize_audit_snapshot(snapshot):
    # Recursively redact PII keys
    if key in PII_KEYS:
        return _safe_value_for_key(key, value)
```

**Why**: 
- Append-only (trigger blocks UPDATE/DELETE)
- PII redacted before storage (banded, not raw)
- Built from sanitized inputs, not recomputed

## Pattern 6: Worker Claim Pattern

**Location**: `worker/tasks/process_application.py`

```python
# Atomic claim with stale processing recovery
UPDATE loan_applications
WHERE id = :app_id
AND (status = PENDING
     OR (status = PROCESSING AND updated_at < stale_before))
SET status = PROCESSING
RETURNING id
```

**Why**: Prevents duplicate processing. Stale processing recovery handles crashed workers.

## Pattern 7: Confidence Calibration

**Location**: `engine/confidence.py`

```python
confidence = data_reliability * boundary_distance_factor
```

**Why**: 
- `data_reliability` captures external data quality (failures, fallbacks)
- `boundary_distance_factor` captures how "safe" the decision is (e.g., risk_score 85 vs 55)
- Product ensures both concerns factor in

---

# 9. Performance & Scalability Considerations

## Current Bottlenecks

| Bottleneck | Location | Impact |
|------------|----------|--------|
| Synchronous external calls | services/base.py | Each provider call adds 50-500ms; sequential = 150-1500ms latency |
| Explanation audit trail scan | api/routes/explanations.py | O(n) scan of audit_logs where n = number of steps |
| Outbox polling | worker/outbox_poller.py | 1-second poll interval; could miss low-latency scenarios |
| JSON serialization on every request | api/routes/applications.py | encrypt() serializes, decrypt() parses |
| No query optimization | audit_log SELECT | Full scan without time-range predicate |

## Scalability Characteristics

| Dimension | Current Behavior | Limit |
|-----------|------------------|-------|
| API horizontal scaling | Stateless, load balancer friendly | Depends on DB connection pool |
| Worker horizontal scaling | Multiple workers consume same queue | Redis broker handles; ensure at-least-once |
| Database connections | Connection pool in API | PGBouncer recommended for >50 concurrent |
| Audit log growth | Append-only, no cleanup | Partition by time or archive after N days |

## Scaling Recommendations

1. **Connection pooling**: Add PGBouncer; increase `DATABASE_POOL_SIZE`
2. **Parallel external calls**: Use `asyncio.gather()` in worker (already done)
3. **Pre-computed explanations**: Store explanation JSONB on completion; read not rebuild
4. **Audit log partitioning**: By month/quarter for efficient pruning
5. **Redis cluster**: For higher throughput idempotency/caching

---

# 10. Weaknesses & Limitations

## Design Flaws

| Issue | Description | Risk |
|-------|-------------|------|
| No key rotation | Encryption key and PAN salt are static env vars | Key compromise requires full data re-encryption |
| No data expiration | Applications and audit logs retained forever | GDPR non-compliance; storage cost growth |
| CORS wildcard rejection | Explicit origins required | Developer friction in local testing |
| No rate limiting | API accepts unlimited requests | DoS vulnerability |
| Weak auth | Static API keys, no scopes enforced (partial) | Key compromise allows full access |

## Technical Debt

| Area | Description |
|------|-------------|
| Scorecard calibration | RULE_SET_V1 uses SME-derived weights, not empirically validated against defaults |
| Mock providers | Real credit bureaus require different data schemas; mock is test-only |
| Single-region | No multi-region deployment capability |
| No backups | No documented backup/restore procedure |
| No health check for DB | /health doesn't verify DB connectivity |

## Edge Cases That Break

| Edge Case | What Happens |
|-----------|--------------|
| Redis down at startup | API works (falls back to PostgreSQL idempotency); circuit defaults to CLOSED |
| PostgreSQL down at startup | RuntimeError; API refuses to start |
| Worker crashes mid-processing | Application stuck in PROCESSING; recovered by stale lock detection |
| All external services down | Fallbacks used; confidence low; MANUAL_REVIEW |
| Duplicate idempotency key with different payload | 409 Conflict (correct) |
| Very large bank_statement in input | Fits in JSONB, but memory intensive |

---

# 11. How to Improve This System

## Immediate Improvements

| Priority | Improvement | Effort | Impact |
|----------|-------------|--------|--------|
| High | Add rate limiting (SlowAPI) | 1 day | Prevents DoS |
| High | Add DB health check to /health | 1 hour | Operational visibility |
| Medium | Add data retention policy | 2 days | GDPR compliance |
| Medium | Add key rotation mechanism | 3 days | Security hardening |

## Architectural Improvements

| Improvement | Description | Trade-off |
|-------------|-------------|-----------|
| Pre-computed explanations | Store explanation JSONB on decision completion | Storage cost; eliminates O(n) rebuild |
| Time-partitioned audit logs | Partition by month; add index on created_at range | Migration complexity; easier pruning |
| Read replicas | Add PG read replica for status/decision queries | Replication lag risk |
| Async notification | WebSocket/push on decision completion | Client complexity |

## Alternative Architectures

| Alternative | When to Use |
|-------------|-------------|
| Event sourcing | If regulatory requires replaying every decision step exactly (current audit log is close) |
| CQRS | If read queries (status, explanation) become heavy vs writes |
| gRPC | If internal service-to-service calls become a bottleneck |
| Temporal workflows | If decision logic becomes more complex and needs long-running orchestrations |

## Refactoring Suggestions

1. **Extract decision engine into separate package**: Currently in `engine/`; could be standalone Python package with minimal dependencies
2. **Add type-safe rule set registry**: Current dict-based registry; could use Enum or Protocol
3. **Replace outbox with Celery results**: Current transactional outbox + Celery is redundant; could use Celery's built-in result backend with idempotency keys
4. **Add integration tests for circuit breaker**: Current chaos tests cover idempotency but not circuit state transitions under load

---

# 12. Learning Notes (For a Developer)

## Key Concepts to Study

### 1. Idempotency in Distributed Systems
- **Concept**: Same request multiple times produces same result once
- **Implementation**: Idempotency key + payload hash + dual-store (Redis fast, Postgres durable)
- **Lesson**: Never trust client-provided IDs alone; always combine with payload hash

### 2. Immutable Audit Trails
- **Concept**: Compliance requires non-repudiation of every decision step
- **Implementation**: Append-only table with trigger protection + PII sanitization
- **Lesson**: Audit logs are forensically valuable; sanitize before writing, never recompute

### 3. Calibrated Confidence
- **Concept**: Confidence != reliability; must include decision boundary distance
- **Implementation**: `confidence = data_reliability * boundary_factor`
- **Lesson**: Separate data quality from decision safety; both matter for trust

### 4. Circuit Breaker Pattern
- **Concept**: Fail fast to preserve system; probe to recover
- **Implementation**: State machine (CLOSED→OPEN→HALF_OPEN) in Redis with single-probe lock
- **Lesson**: Don't retry forever; open circuit early, test with single probe

### 5. Transactional Outbox
- **Concept**: Guarantee application + message atomicity without distributed transactions
- **Implementation**: Single DB transaction writes application + outbox message
- **Lesson**: Avoids distributed transactions; requires poller to dispatch messages

### 6. Deterministic Business Logic
- **Concept**: Same inputs → same outputs, always
- **Implementation**: No random(), no time.time(), frozen dataclass rule sets
- **Lesson**: Testable, replayable, auditable; essential for financial systems

### 7. PII Protection
- **Concept**: Encrypt at rest; hash for lookups; redact for logs
- **Implementation**: AES-256-GCM + salted SHA-256 + audit sanitization
- **Lesson**: Defense in depth; multiple layers of protection

## Skills Demonstrated by This Project

| Skill | Evidence |
|--------|-----------|
| FastAPI development | Routes, dependencies, middleware, auth |
| Async Python | Celery tasks, asyncio.gather in worker |
| SQLAlchemy ORM | Models, relationships, migrations |
| PostgreSQL features | JSONB, UUID, triggers, constraints |
| Redis usage | Cache, pub/sub, state (circuit breaker) |
| Security | Encryption, hashing, sanitization |
| Observability | Prometheus metrics, structured logging |
| Testing | Unit (pure functions), integration (DB), chaos (idempotency) |
| Distributed systems patterns | Idempotency, circuit breaker, outbox |

## How to Replicate or Build Something Similar

### Phase 1: Core Domain (1-2 weeks)
1. Define domain entities (Application, Decision, AuditLog)
2. Implement pure scoring engine (no external calls)
3. Write unit tests for scoring, rules, confidence
4. Create immutable rule set dataclass

### Phase 2: API Layer (1 week)
1. Set up FastAPI with SQLAlchemy
2. Implement application submission with encryption
3. Add idempotency (Redis + PostgreSQL)
4. Implement status/decision endpoints

### Phase 3: Worker Integration (1-2 weeks)
1. Set up Celery + Redis broker
2. Implement transactional outbox
3. Add external service clients with retry
4. Implement circuit breaker

### Phase 4: Resilience (1 week)
1. Add audit logging at every step
2. Implement fallback logic
3. Add confidence threshold override
4. Implement explanation builder from audit trail

### Phase 5: Observability (3-5 days)
1. Add Prometheus metrics
2. Configure structured logging
3. Add health checks
4. Write integration/chaos tests

## Prerequisites to Understanding This System

- FastAPI and Pydantic
- SQLAlchemy and PostgreSQL
- Redis data structures and patterns
- Celery task queues
- Circuit breaker pattern
- AES-GCM encryption
- REST API design
- pytest and test organization

---

*Generated: 2026-05-04*
*Project: AuditLend v2.0.0*
*Coverage: 87.24%*