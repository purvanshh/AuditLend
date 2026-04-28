# AuditLend - The Auditable Credit Decision Engine

Every decision, explained. Every failure, handled. Every step, audited.

AuditLend is a production-grade reference implementation of a credit decision engine. It processes loan applications asynchronously, handles deterministic external-data failures, computes a weighted risk score, separates data reliability from calibrated decision confidence, protects PII at rest, stores immutable audit logs, exposes Prometheus metrics, and returns borrower- or reviewer-friendly explanations for every decision.

## Quick Start

Prerequisites:

- Docker
- Docker Compose

Start the full stack:

```bash
docker compose up --build
```

The stack exposes:

- API: `http://localhost:8000`
- Credit bureau mock: `http://localhost:8001`
- Bank analyzer mock: `http://localhost:8002`
- GST verifier mock: `http://localhost:8003`
- Flower: `http://localhost:5555`

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"healthy","service":"auditlend-api","version":"2.0.0"}
```

## Architecture

```text
+---------+
| Client  |
+----+----+
     | POST /api/v1/apply-loan
     v
+---------+      idempotency + app state      +------------+
| FastAPI |----------------------------------->| PostgreSQL |
|   API   |<-----------------------------------| source     |
+----+----+                                    | truth      |
     | enqueue                                 +-----+------+
     v                                               ^
+---------+      fetch external data                 | audit,
| Redis   |----->+-----------------+-----------------+ snapshots,
| broker  |      | Celery Worker   |                 | decisions
+---------+      +--------+--------+
                          |
             +------------+-------------+
             v            v             v
      Credit Bureau  Bank Analyzer  GST Verifier
          Mock           Mock           Mock
```

## Failure Walkthrough

All scenarios use deterministic failure flags. Re-running the same request with the same idempotency key returns the same application ID. Reusing the same idempotency key with a different payload returns `409 Conflict`.

The examples below use `jq` for readability. If you do not have it, remove the `| jq` pieces.

### Helper: Poll A Decision

After any `POST /apply-loan`, save the returned `application_id`:

```bash
APP_ID="<application_id>"
```

Then poll:

```bash
curl -s "http://localhost:8000/api/v1/status/$APP_ID" | jq
curl -s "http://localhost:8000/api/v1/decision/$APP_ID" | jq
curl -s "http://localhost:8000/api/v1/explanation/$APP_ID" | jq
```

### Scenario 1: Everything Works

This PAN is intentionally chosen because the mock services deterministically return a strong profile for it.

```bash
APP_ID=$(curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-green-001" \
  -d '{
    "idempotency_key": "demo-green-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "AAAAA1111F",
      "monthly_income": 150000,
      "existing_emis": 20000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "SUCCESS",
      "bank_analyzer": "SUCCESS",
      "gst_verifier": "SUCCESS"
    }
  }' | jq -r '.application_id')

echo "$APP_ID"
```

Expected apply response shape:

```json
{
  "application_id": "generated-uuid",
  "status": "PENDING",
  "message": "Application received and queued for processing"
}
```

Poll until the status is terminal:

```bash
curl -s "http://localhost:8000/api/v1/status/$APP_ID" | jq
```

Expected final status:

```json
{
  "application_id": "generated-uuid",
  "status": "COMPLETED",
  "updated_at": "timestamp"
}
```

Get the decision:

```bash
curl -s "http://localhost:8000/api/v1/decision/$APP_ID" | jq
```

Expected decision characteristics:

```json
{
  "decision": "APPROVE",
  "risk_score": 88.35,
  "confidence": 1.0,
  "data_reliability": 1.0,
  "rule_version": "RULE_SET_V1"
}
```

Get the explanation:

```bash
curl -s "http://localhost:8000/api/v1/explanation/$APP_ID" | jq
```

Expected explanation characteristics:

```json
{
  "decision": "APPROVE",
  "summary": "Decision APPROVE was produced from verified data sources with confidence 1.00.",
  "rule_version": "RULE_SET_V1"
}
```

Replay the same request:

```bash
curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-green-001" \
  -d '{
    "idempotency_key": "demo-green-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "AAAAA1111F",
      "monthly_income": 150000,
      "existing_emis": 20000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "SUCCESS",
      "bank_analyzer": "SUCCESS",
      "gst_verifier": "SUCCESS"
    }
  }' | jq
```

Expected: HTTP `200` with the same `application_id`.

### Scenario 2: Credit Bureau Down

This scenario uses `TIMEOUT`. The worker retries and then uses conservative fallback credit score `600`. It can take close to a minute because the timeout path is intentionally real enough to exercise retry/backoff behavior.

```bash
APP_ID=$(curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-credit-timeout-001" \
  -d '{
    "idempotency_key": "demo-credit-timeout-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "AAAAA1111F",
      "monthly_income": 150000,
      "existing_emis": 20000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "TIMEOUT",
      "bank_analyzer": "SUCCESS",
      "gst_verifier": "SUCCESS"
    }
  }' | jq -r '.application_id')
```

After processing:

```bash
curl -s "http://localhost:8000/api/v1/decision/$APP_ID" | jq
```

Expected decision characteristics:

```json
{
  "decision": "NEEDS_REVIEW",
  "risk_score": 72.46,
  "confidence": 0.54,
  "data_reliability": 0.6,
  "factors": [
    "risk_score (computed) = 72.46",
    "credit_component (fallback) = 26.67/40.00 (credit_score=600)",
    "Confidence below threshold - routed to manual review"
  ],
  "rule_version": "RULE_SET_V1"
}
```

Why: `TIMEOUT` plus fallback credit lowers `data_reliability` to `0.60`. The risk score is still numerically approvable, but calibrated confidence applies the boundary-distance factor and falls to `0.54`, forcing manual review.

Audit trace:

```bash
docker compose exec postgres psql -U auditlend -d auditlend \
  -c "SELECT step, error_type, fallback_used, fallback_reason FROM audit_logs WHERE application_id = '$APP_ID' ORDER BY id;"
```

Expected audit characteristics:

```text
CREDIT_BUREAU_FETCH | TIMEOUT | t | TIMEOUT
DECISION_CALCULATION | null | f | null
MANUAL_REVIEW_ROUTING | null | f | null
```

### Scenario 3: Partial Bank Data

This scenario simulates incomplete bank analysis. The bank mock omits `income_stability`; the engine fills it with neutral `0.5` and applies a confidence penalty.

```bash
APP_ID=$(curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-bank-partial-001" \
  -d '{
    "idempotency_key": "demo-bank-partial-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "AAAAA1111F",
      "monthly_income": 150000,
      "existing_emis": 20000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "SUCCESS",
      "bank_analyzer": "PARTIAL_DATA",
      "gst_verifier": "SUCCESS"
    }
  }' | jq -r '.application_id')
```

Decision:

```bash
curl -s "http://localhost:8000/api/v1/decision/$APP_ID" | jq
```

Expected decision characteristics:

```json
{
  "decision": "APPROVE",
  "risk_score": 77.9,
  "confidence": 0.72,
  "data_reliability": 0.8,
  "factors": [
    "income_stability_component (default) = 10.00/20.00 (income_stability=0.50)"
  ]
}
```

Explanation:

```bash
curl -s "http://localhost:8000/api/v1/explanation/$APP_ID" | jq
```

Expected explanation characteristics:

```json
{
  "summary": "Decision APPROVE was produced with degraded data quality...",
  "factors": [
    {
      "name": "Income Stability",
      "value": "0.5",
      "status": "partial"
    }
  ]
}
```

### Scenario 4: Total Data Meltdown

This scenario combines three degraded sources. The engine should force manual review due to confidence below `0.6`.

```bash
APP_ID=$(curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-meltdown-001" \
  -d '{
    "idempotency_key": "demo-meltdown-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "AAAAA1111F",
      "monthly_income": 150000,
      "existing_emis": 20000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "SERVICE_DOWN",
      "bank_analyzer": "FORMAT_ERROR",
      "gst_verifier": "NO_RECORD"
    }
  }' | jq -r '.application_id')
```

Decision:

```bash
curl -s "http://localhost:8000/api/v1/decision/$APP_ID" | jq
```

Expected decision characteristics:

```json
{
  "decision": "NEEDS_REVIEW",
  "risk_score": 36.46,
  "confidence": 0.1,
  "data_reliability": 0.2,
  "factors": [
    "risk_score (computed) = 36.46",
    "credit_component (fallback) = 26.67/40.00 (credit_score=600)",
    "gst_gate (applied) = risk_score capped at 36.46",
    "Confidence below threshold - routed to manual review"
  ]
}
```

Explanation:

```bash
curl -s "http://localhost:8000/api/v1/explanation/$APP_ID" | jq
```

Expected explanation characteristics:

```json
{
  "decision": "NEEDS_REVIEW",
  "summary": "The system had insufficient reliable data to make an automatic decision...",
  "timeline": [
    {"step": "CREDIT_BUREAU_FETCH", "status": "SERVICE_DOWN"},
    {"step": "BANK_ANALYZER_FETCH", "status": "FORMAT_ERROR"},
    {"step": "GST_VERIFIER_FETCH", "status": "NO_RECORD"},
    {"step": "DECISION_CALCULATION", "status": "NEEDS_REVIEW"},
    {"step": "MANUAL_REVIEW_OVERRIDE", "status": "NEEDS_REVIEW"}
  ]
}
```

### Scenario 5: GST Non-Compliance Blocks Approval

Even with excellent credit, explicit GST non-compliance is a gating factor. The engine caps the effective risk score at `54`, preventing automatic approval and routing the application to review unless another decline rule applies.

```bash
APP_ID=$(curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-gst-mismatch-001" \
  -d '{
    "idempotency_key": "demo-gst-mismatch-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "AAAAA1111F",
      "monthly_income": 150000,
      "existing_emis": 10000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "SUCCESS",
      "bank_analyzer": "SUCCESS",
      "gst_verifier": "PAN_MISMATCH"
    }
  }' | jq -r '.application_id')
```

Expected decision characteristics:

```json
{
  "decision": "NEEDS_REVIEW",
  "factors": [
    "gst_component (non_compliant) = 0.00/15.00",
    "gst_gate (applied) = risk_score capped at 54.00"
  ]
}
```

## API Reference

### `POST /api/v1/apply-loan`

Creates a loan application and enqueues asynchronous processing.

Headers:

- `Content-Type: application/json`
- `Idempotency-Key: <unique logical request key>`

Request body:

```json
{
  "idempotency_key": "req-001",
  "user_data": {
    "name": "Jane Doe",
    "pan": "AAAAA1111F",
    "monthly_income": 150000,
    "existing_emis": 20000,
    "loan_amount": 500000,
    "tenure_months": 36,
    "bank_statement": []
  },
  "failure_flags": {
    "credit_bureau": "SUCCESS",
    "bank_analyzer": "SUCCESS",
    "gst_verifier": "SUCCESS"
  }
}
```

Responses:

- `201`: new application accepted
- `200`: same idempotency key and same payload replayed
- `400`: validation error
- `409`: same idempotency key reused with different payload

### `GET /api/v1/status/{application_id}`

Returns:

```json
{
  "application_id": "uuid",
  "status": "PENDING|PROCESSING|COMPLETED|MANUAL_REVIEW",
  "updated_at": "timestamp"
}
```

### `GET /api/v1/decision/{application_id}`

If processing:

```json
{
  "status": "PROCESSING",
  "message": "Decision not yet available"
}
```

If complete:

```json
{
  "application_id": "uuid",
  "decision": "APPROVE|DECLINE|NEEDS_REVIEW",
  "confidence": 1.0,
  "data_reliability": 1.0,
  "risk_score": 88.35,
  "factors": ["risk_score (computed) = 88.35"],
  "rule_version": "RULE_SET_V1"
}
```

### `GET /api/v1/explanation/{application_id}`

Returns:

```json
{
  "application_id": "uuid",
  "decision": "NEEDS_REVIEW",
  "summary": "Human-readable explanation",
  "factors": [
    {"name": "Credit Score", "value": "600", "status": "fallback"}
  ],
  "timeline": [
    {"step": "CREDIT_BUREAU_FETCH", "status": "TIMEOUT", "timestamp": "timestamp"}
  ],
  "rule_version": "RULE_SET_V1",
  "generated_at": "timestamp"
}
```

### `GET /metrics`

Exposes Prometheus metrics, including:

- `auditlend_applications_total`
- `auditlend_external_api_requests_total`
- `auditlend_external_api_latency_seconds`
- `auditlend_circuit_breaker_state`
- `auditlend_decision_confidence`

### Error Format

Errors use Problem Details style:

```json
{
  "type": "https://api.auditlend.local/errors/validation",
  "title": "Validation Error",
  "detail": "monthly_income must be positive",
  "instance": "/api/v1/apply-loan"
}
```

## Mock API Reference

Credit bureau:

```bash
curl "http://localhost:8001/credit-score?pan=AAAAA1111F&fail_mode=SUCCESS"
curl "http://localhost:8001/credit-score?pan=AAAAA1111F&fail_mode=STALE_DATA"
curl "http://localhost:8001/credit-score?pan=AAAAA1111F&fail_mode=SERVICE_DOWN"
```

Bank analyzer:

```bash
curl -X POST "http://localhost:8002/analyze?fail_mode=PARTIAL_DATA" \
  -H "Content-Type: application/json" \
  -d '{"pan":"AAAAA1111F","bank_statement":[]}'
```

GST verifier:

```bash
curl "http://localhost:8003/verify-gst?pan=AAAAA1111F&fail_mode=NO_RECORD"
```

## Configuration

| Variable | Purpose | Default in Compose |
| --- | --- | --- |
| `DATABASE_URL` | Sync SQLAlchemy/Postgres URL for workers and migrations | `postgresql://auditlend:auditlend@postgres:5432/auditlend` |
| `ASYNC_DATABASE_URL` | Async SQLAlchemy/Postgres URL for FastAPI | `postgresql+asyncpg://auditlend:auditlend@postgres:5432/auditlend` |
| `REDIS_URL` | Celery broker/result backend and circuit state | `redis://redis:6379/0` |
| `IDEMPOTENCY_CACHE_TTL_SECONDS` | Redis idempotency replay cache TTL | `86400` |
| `CREDIT_BUREAU_URL` | Credit bureau service base URL | `http://credit-bureau:8001` |
| `BANK_ANALYZER_URL` | Bank analyzer service base URL | `http://bank-analyzer:8002` |
| `GST_VERIFIER_URL` | GST verifier service base URL | `http://gst-verifier:8003` |
| `CONFIDENCE_THRESHOLD` | Below this value, force manual review | `0.6` |
| `RULE_SET_VERSION` | Active rule version recorded in audit logs | `RULE_SET_V1` |
| `PII_ENCRYPTION_KEY` | Hex-encoded AES-GCM key for encrypted user data | dev-only zero key |
| `PAN_HASH_SALT` | Salt used for SHA-256 PAN hashing | `auditlend-dev-salt` |
| `CIRCUIT_BREAKER_THRESHOLD` | Failures before opening service circuit | `5` |
| `CIRCUIT_BREAKER_WINDOW_SECONDS` | Failure counting window | `60` |
| `CIRCUIT_BREAKER_TIMEOUT_SECONDS` | Open circuit cooldown | `120` |
| `MAX_RETRIES` | Per-service retry count | `3` |
| `RETRY_BACKOFF_BASE_SECONDS` | Exponential backoff base | `2` |
| `TASK_TIMEOUT_SECONDS` | Worker processing watchdog | `60` |
| `PROCESSING_LOCK_TIMEOUT_SECONDS` | Age after which stuck PROCESSING apps can be reclaimed | `300` |
| `LOG_LEVEL` | Runtime logging level | `INFO` |

## Testing

Install dependencies locally:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run unit tests:

```bash
.venv/bin/pytest tests/unit -q
```

Run all tests:

```bash
.venv/bin/pytest tests/ -q
```

PostgreSQL-backed integration and chaos tests auto-skip when no database is available. To enable them, run the Docker stack or provide:

```bash
export AUDITLEND_TEST_DATABASE_URL=postgresql://auditlend:auditlend@localhost:5432/auditlend
export AUDITLEND_TEST_ASYNC_DATABASE_URL=postgresql+asyncpg://auditlend:auditlend@localhost:5432/auditlend
export AUDITLEND_TEST_REDIS_URL=redis://localhost:6379/0
```

Then:

```bash
.venv/bin/pytest tests/integration -q
.venv/bin/pytest tests/chaos -q
```

Engine coverage:

```bash
.venv/bin/pytest tests/unit/test_scoring.py tests/unit/test_confidence.py tests/unit/test_confidence_calibrated.py tests/unit/test_rules.py tests/unit/test_decision_engine.py \
  -q --cov=engine --cov-report=term-missing
```

## Project Philosophy

AuditLend is built around a few non-negotiable ideas:

- Determinism beats cleverness. Business outputs must be replayable from inputs.
- Idempotency is part of correctness, not an API nicety.
- Risk score, data reliability, and calibrated confidence are distinct values.
- Every fallback must lower data reliability.
- Raw PAN is never stored in plaintext; application PII is AES-GCM encrypted at rest.
- Every important step must write an audit entry with input, output, failure type, fallback usage, and rule version.
- The explanation endpoint must read from the audit trail, not from whatever the current code thinks would happen today.
- External failures are named states, not surprises.
- A stuck worker should be recoverable. A duplicate terminal decision should be impossible.

This makes the system slower to fake and harder to hand-wave, which is exactly why it is useful.
