# AuditLend

Auditable credit decision engine with deterministic failure simulation, idempotent intake, asynchronous processing, encrypted PII storage, immutable audit logs, calibrated decision confidence, and human-readable explanations.

This repository is a production-readiness reference implementation. It is built and tested end to end with local infrastructure, mock external providers, Docker Compose, PostgreSQL, Redis, FastAPI, and Celery. It is not wired to real credit bureaus or real lending portfolios, and its current risk score is governed and deterministic but not empirically calibrated on historical default data.

## Current Status

Last verified locally: **2026-04-29**

| Area | Status | Evidence |
| --- | --- | --- |
| Docker stack | PASS | `docker compose up --build -d`; API, worker, Redis, Postgres, mocks, and Flower started |
| Service health | PASS | API `/health` returned `200`; worker `/health` returned `200`; all core compose services reported healthy |
| Authentication | PASS | Protected status endpoint returned `401` without key and `404` with valid read key for a missing app |
| Metrics | PASS | `/metrics` returned Prometheus output with `auditlend_*` metrics |
| Full test suite | PASS | `124 passed`, `0 skipped` |
| Coverage gate | PASS | `87.24%`, above the configured `85%` threshold |
| Live end-to-end smoke | PASS | API intake -> outbox -> Celery worker -> mock services -> decision -> audit -> explanation |

Live smoke result from the final verification run:

```json
{
  "status": "COMPLETED",
  "decision": "APPROVE",
  "confidence": 0.7,
  "data_reliability": 1.0,
  "risk_score": 64.1,
  "rule_version": "RULE_SET_V1"
}
```

The explanation endpoint returned an audit-derived timeline:

```text
PROCESSING_STARTED -> CREDIT_BUREAU_FETCH -> GST_VERIFIER_FETCH -> BANK_ANALYZER_FETCH -> DECISION_CALCULATION
```

## What Is Actually Implemented

### API and Processing

- FastAPI application with authenticated loan application intake.
- Celery worker for asynchronous processing.
- Redis broker/result backend, idempotency cache, and circuit breaker state.
- PostgreSQL source of truth for applications, idempotency records, external data snapshots, outbox messages, and audit logs.
- Transactional outbox pattern so API writes and task delivery intent are committed together.
- Worker-side task claiming with atomic `UPDATE ... WHERE status=PENDING`.
- External data fetch reuse so worker retries do not repeat already-persisted provider calls.

### Decision Engine

- Weighted risk score in `engine/scoring.py`.
- Immutable rule set registry in `engine/rule_sets.py`.
- Decision rules in `engine/rules.py`.
- Orchestration in `engine/decision.py`.
- Separate fields for:
  - `risk_score`
  - `data_reliability`
  - calibrated `confidence`
- GST non-compliance gate that prevents automatic approval when GST mismatch is explicit.
- Manual review override when calibrated confidence falls below threshold.

### Security and Data Protection

- API key authentication on application, status, decision, and explanation routes.
- AES-256-GCM encryption for stored application PII.
- Salted SHA-256 PAN hash.
- Raw PAN is not stored in loan application rows.
- Audit snapshots are sanitized and band raw financial values before persistence.
- Explanation responses are derived from audit logs and do not expose raw PAN or names.

### Audit and Compliance Trail

- Append-only audit log writes in application code.
- Database trigger blocks `UPDATE` and `DELETE` against `audit_logs`.
- Audit entries include step, input/output snapshot, error type, fallback flag, rule version, actor, and timestamp where applicable.
- Explanation engine builds summaries and timelines from audit history, not from a fresh recomputation.

### Resilience and Observability

- Retry/backoff for retryable provider failures.
- Redis-backed circuit breaker with half-open single-probe lock.
- Per-provider failure modes.
- Configurable external API timeout.
- Worker health endpoint on port `8004`.
- Structured JSON logs.
- Prometheus metrics for applications, external calls, circuit breaker state, decision confidence, task duration, and task failures.

### Deterministic Mocks

Mock services live under `mock_apis/` and support deterministic success and failure modes:

- Credit bureau: `SUCCESS`, `TIMEOUT`, `STALE_DATA`, `SERVICE_DOWN`
- Bank analyzer: `SUCCESS`, `PARTIAL_DATA`, `FORMAT_ERROR`
- GST verifier: `SUCCESS`, `PAN_MISMATCH`, `NO_RECORD`

For identical inputs, mock responses are deterministic. Request IDs are input-derived, not random UUIDs. Stale data uses a fixed reference date.

## What This Project Does Not Claim

This is important. AuditLend is built end to end, but it is not a drop-in live lending system without additional institutional controls.

- The scorecard is deterministic and governed, but it is not empirically calibrated against a real repayment/default dataset.
- Mock APIs are deterministic test doubles, not real provider integrations.
- API key auth is suitable for this reference stack, but a real deployment should use OAuth2/OIDC, scoped service identities, mTLS, and centralized secret management.
- Docker Compose is a local/demo deployment target, not a production orchestrator.
- TLS/mTLS, managed key rotation, SIEM integration, data retention automation, and formal model risk governance are outside this repository.
- Containers currently run in a local developer-oriented configuration; hardening user privileges and image policies is a production deployment task.

## Architecture

```text
Client
  |
  | POST /api/v1/apply-loan
  v
FastAPI API
  | \
  |  \-- PostgreSQL
  |       - loan_applications
  |       - idempotency_records
  |       - outbox
  |       - external_data
  |       - audit_logs
  |
  \-- Redis
       - idempotency cache
       - Celery broker/result backend
       - circuit breaker state

Celery Worker
  |
  |-- polls outbox
  |-- atomically claims applications
  |-- fetches/reuses external data
  |-- computes decision
  |-- stores audit trail
  |
  |-- Credit Bureau Mock
  |-- Bank Analyzer Mock
  \-- GST Verifier Mock
```

## Repository Map

| Path | Purpose |
| --- | --- |
| `api/` | FastAPI app, auth, routes, schemas |
| `worker/` | Celery app, outbox poller, processing task |
| `engine/` | Scoring, rule sets, decision orchestration, explanation builder |
| `services/` | Provider clients, crypto, audit safety, metrics, logging |
| `models/` | SQLAlchemy models |
| `migrations/` | Alembic migrations |
| `mock_apis/` | Deterministic external-provider mocks |
| `tests/` | Unit, integration, and chaos tests |
| `docs/CALIBRATION.md` | Current scorecard calibration status and rule-set governance notes |

## Quick Start

Prerequisites:

- Docker Desktop or Docker Engine
- Docker Compose

This project requires real-looking local secrets. For local development, `docker-compose.override.yml` supplies dev-only values and is gitignored.

Start the stack:

```bash
docker compose up --build -d
```

Check service health:

```bash
curl http://localhost:8000/health
curl http://localhost:8004/health
docker compose ps
```

Expected API health response:

```json
{"status":"healthy","service":"auditlend-api","version":"2.0.0"}
```

Useful local endpoints:

| Service | URL |
| --- | --- |
| API | `http://localhost:8000` |
| Credit bureau mock | `http://localhost:8001` |
| Bank analyzer mock | `http://localhost:8002` |
| GST verifier mock | `http://localhost:8003` |
| Worker health | `http://localhost:8004/health` |
| Flower | `http://localhost:5555` |
| Metrics | `http://localhost:8000/metrics` |

## API Authentication

Protected routes require `X-API-Key`.

The local override defines:

```text
dev-key-read-write
dev-key-read-only
```

Examples:

```bash
curl -i http://localhost:8000/api/v1/status/00000000-0000-0000-0000-000000000000
```

Expected: `401`

```bash
curl -i \
  -H "X-API-Key: dev-key-read-only" \
  http://localhost:8000/api/v1/status/00000000-0000-0000-0000-000000000000
```

Expected: `404` because authentication passed and the application does not exist.

## End-to-End Smoke Test

Submit an application:

```bash
APP_ID=$(curl -s -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key-read-write" \
  -H "Idempotency-Key: smoke-001" \
  -d '{
    "idempotency_key": "smoke-001",
    "user_data": {
      "name": "Jane Doe",
      "pan": "ABCDE1234F",
      "monthly_income": 120000,
      "existing_emis": 25000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "SUCCESS",
      "bank_analyzer": "SUCCESS",
      "gst_verifier": "SUCCESS"
    }
  }' | python3 -c 'import json,sys; print(json.load(sys.stdin)["application_id"])')

echo "$APP_ID"
```

Check status:

```bash
curl -s \
  -H "X-API-Key: dev-key-read-only" \
  "http://localhost:8000/api/v1/status/$APP_ID"
```

Expected terminal shape:

```json
{
  "application_id": "uuid",
  "status": "COMPLETED",
  "updated_at": "timestamp"
}
```

Check decision:

```bash
curl -s \
  -H "X-API-Key: dev-key-read-only" \
  "http://localhost:8000/api/v1/decision/$APP_ID"
```

Expected shape:

```json
{
  "application_id": "uuid",
  "decision": "APPROVE",
  "confidence": 0.7,
  "data_reliability": 1.0,
  "risk_score": 64.1,
  "rule_version": "RULE_SET_V1"
}
```

Check explanation:

```bash
curl -s \
  -H "X-API-Key: dev-key-read-only" \
  "http://localhost:8000/api/v1/explanation/$APP_ID"
```

Expected shape:

```json
{
  "application_id": "uuid",
  "decision": "APPROVE",
  "summary": "Decision APPROVE was produced from verified data sources with confidence 0.70.",
  "timeline": [
    {"step": "PROCESSING_STARTED", "status": "PROCESSING"},
    {"step": "CREDIT_BUREAU_FETCH", "status": "SUCCESS"},
    {"step": "GST_VERIFIER_FETCH", "status": "SUCCESS"},
    {"step": "BANK_ANALYZER_FETCH", "status": "SUCCESS"},
    {"step": "DECISION_CALCULATION", "status": "APPROVE"}
  ],
  "rule_version": "RULE_SET_V1"
}
```

Replay the same request with the same idempotency key and payload. Expected: `200` and the same `application_id`.

Reuse the same idempotency key with a different payload. Expected: `409 Conflict`.

## Deterministic Failure Scenarios

All examples require `X-API-Key: dev-key-read-write` for submit and `X-API-Key: dev-key-read-only` for reads.

### Credit Bureau Timeout

Input:

```json
"failure_flags": {
  "credit_bureau": "TIMEOUT",
  "bank_analyzer": "SUCCESS",
  "gst_verifier": "SUCCESS"
}
```

Expected behavior:

- Credit provider retries and falls back to conservative credit score `600`.
- Data reliability is reduced.
- Calibrated confidence can force `NEEDS_REVIEW`.
- Audit log includes `CREDIT_BUREAU_FETCH` with `TIMEOUT` and fallback information.

### Partial Bank Data

Input:

```json
"failure_flags": {
  "credit_bureau": "SUCCESS",
  "bank_analyzer": "PARTIAL_DATA",
  "gst_verifier": "SUCCESS"
}
```

Expected behavior:

- Missing income stability is filled with neutral `0.5`.
- Data reliability is reduced.
- Decision may still approve if the risk score and confidence remain sufficient.
- Explanation marks the degraded bank data path.

### Total External Data Meltdown

Input:

```json
"failure_flags": {
  "credit_bureau": "SERVICE_DOWN",
  "bank_analyzer": "FORMAT_ERROR",
  "gst_verifier": "NO_RECORD"
}
```

Expected behavior:

- Conservative fallbacks are applied.
- Data reliability drops sharply.
- Application routes to manual review.
- Audit timeline records each failing source.

### GST PAN Mismatch

Input:

```json
"failure_flags": {
  "credit_bureau": "SUCCESS",
  "bank_analyzer": "SUCCESS",
  "gst_verifier": "PAN_MISMATCH"
}
```

Expected behavior:

- GST compliance is explicitly false.
- Effective risk score is capped below automatic approval.
- Application routes to review unless another decline rule applies.

## API Reference

### `POST /api/v1/apply-loan`

Creates a loan application and records an outbox message for asynchronous processing.

Headers:

```text
Content-Type: application/json
X-API-Key: dev-key-read-write
Idempotency-Key: unique-logical-request-key
```

Request:

```json
{
  "idempotency_key": "req-001",
  "user_data": {
    "name": "Jane Doe",
    "pan": "ABCDE1234F",
    "monthly_income": 120000,
    "existing_emis": 25000,
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

| Code | Meaning |
| --- | --- |
| `201` | New application accepted |
| `200` | Same idempotency key and same payload replayed |
| `400` | Validation error |
| `401` | Missing or invalid API key |
| `403` | API key lacks required scope |
| `409` | Same idempotency key reused with a different payload |

### `GET /api/v1/status/{application_id}`

Requires read scope.

```json
{
  "application_id": "uuid",
  "status": "PENDING|PROCESSING|COMPLETED|MANUAL_REVIEW",
  "updated_at": "timestamp"
}
```

### `GET /api/v1/decision/{application_id}`

Requires read scope.

If complete:

```json
{
  "application_id": "uuid",
  "decision": "APPROVE|DECLINE|NEEDS_REVIEW",
  "confidence": 0.7,
  "data_reliability": 1.0,
  "risk_score": 64.1,
  "factors": ["risk_score (computed) = 64.10"],
  "rule_version": "RULE_SET_V1"
}
```

If still processing, the endpoint returns `202`.

### `GET /api/v1/explanation/{application_id}`

Requires read scope.

```json
{
  "application_id": "uuid",
  "decision": "APPROVE",
  "summary": "Human-readable explanation",
  "factors": [
    {"name": "Risk Score", "value": "64.10", "status": "computed"}
  ],
  "timeline": [
    {"step": "DECISION_CALCULATION", "status": "APPROVE", "timestamp": "timestamp"}
  ],
  "rule_version": "RULE_SET_V1",
  "generated_at": "timestamp"
}
```

### `GET /metrics`

No API key required in this local stack.

Prometheus series include:

- `auditlend_applications_total`
- `auditlend_external_api_requests_total`
- `auditlend_external_api_latency_seconds`
- `auditlend_circuit_breaker_state`
- `auditlend_decision_confidence`
- `auditlend_task_duration_seconds`
- `auditlend_task_failures_total`

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

## Configuration

Production secrets are not committed. Local dev-only values can live in `docker-compose.override.yml`, which is ignored by git.

| Variable | Purpose | Compose value |
| --- | --- | --- |
| `DATABASE_URL` | Sync SQLAlchemy/Postgres URL | `postgresql://auditlend:auditlend@postgres:5432/auditlend` |
| `ASYNC_DATABASE_URL` | Async SQLAlchemy/Postgres URL | `postgresql+asyncpg://auditlend:auditlend@postgres:5432/auditlend` |
| `AUDITLEND_ASYNC_DB_POOL` | Optional async DB pool mode; `null` is used by multi-event-loop tests only | `pooled` |
| `REDIS_URL` | Celery, idempotency cache, circuit breaker state | `redis://redis:6379/0` |
| `IDEMPOTENCY_CACHE_TTL_SECONDS` | Redis idempotency replay TTL | `86400` |
| `CREDIT_BUREAU_URL` | Credit mock base URL | `http://credit-bureau:8001` |
| `BANK_ANALYZER_URL` | Bank mock base URL | `http://bank-analyzer:8002` |
| `GST_VERIFIER_URL` | GST mock base URL | `http://gst-verifier:8003` |
| `CONFIDENCE_THRESHOLD` | Manual review confidence threshold | `0.6` |
| `PII_ENCRYPTION_KEY` | Required 64-character hex AES-256-GCM key | `${PII_ENCRYPTION_KEY}` |
| `PAN_HASH_SALT` | Required per-environment PAN hash salt | `${PAN_HASH_SALT}` |
| `API_KEYS` | Comma-separated API keys with optional scopes | `${API_KEYS}` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated trusted browser origins; wildcard rejected | `http://localhost:3000,http://localhost:8000` |
| `CIRCUIT_BREAKER_THRESHOLD` | Failures before opening circuit | `5` |
| `CIRCUIT_BREAKER_WINDOW_SECONDS` | Circuit failure counting window | `60` |
| `CIRCUIT_BREAKER_TIMEOUT_SECONDS` | Open circuit cooldown | `120` |
| `CIRCUIT_BREAKER_PROBE_LOCK_SECONDS` | Half-open single-probe lock TTL | `10` |
| `MAX_RETRIES` | Per-service retry count | `3` |
| `RETRY_BACKOFF_BASE_SECONDS` | Exponential backoff base | `2` |
| `EXTERNAL_API_TIMEOUT_SECONDS` | External adapter HTTP timeout | `30.0` |
| `TASK_TIMEOUT_SECONDS` | Worker task watchdog | `60` |
| `PROCESSING_LOCK_TIMEOUT_SECONDS` | Stale processing reclaim age | `300` |
| `OUTBOX_POLL_INTERVAL_SECONDS` | Worker outbox poll interval | `1.0` |
| `WORKER_HEALTH_PORT` | Worker health server port | `8004` |
| `LOG_LEVEL` | Runtime logging level | `INFO` |

## Testing

Install dependencies locally:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run the full verified test command:

```bash
.venv/bin/python -m pytest tests/ -v --cov=. --cov-fail-under=85 -rs
```

Final verified result:

```text
124 passed
0 skipped
Required test coverage of 85% reached
Total coverage: 87.24%
```

Run only unit tests:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Run integration and chaos tests with live Postgres/Redis:

```bash
docker compose up -d postgres redis credit-bureau bank-analyzer gst-verifier
.venv/bin/python -m pytest tests/integration tests/chaos -q
```

## Database and Data Safety Checks

Confirm encrypted application storage:

```bash
docker compose exec postgres psql -U auditlend -d auditlend \
  -c "SELECT pan_hash, encrypted_user_data IS NOT NULL AS has_ciphertext, encryption_nonce IS NOT NULL AS has_nonce FROM loan_applications LIMIT 5;"
```

Confirm audit log immutability:

```bash
docker compose exec postgres psql -U auditlend -d auditlend \
  -c "UPDATE audit_logs SET step = 'TEST' WHERE id = 1;"
```

Expected: PostgreSQL rejects the update with the append-only trigger.

## CI

GitHub Actions workflow:

```text
.github/workflows/ci.yaml
```

The workflow provisions Postgres and Redis, runs migrations, sets required crypto/auth env vars, runs tests with coverage, and fails if tests are skipped or coverage falls below the configured threshold.

## Rule Governance

Current active rule set:

```text
RULE_SET_V1
```

Rule sets are immutable dataclasses in `engine/rule_sets.py`. Changing weights or thresholds should create a new rule set version and update `docs/CALIBRATION.md`.

Current calibration status:

- `RULE_SET_V1` uses SME-derived heuristic weights.
- It is deterministic and test-covered.
- It still needs empirical validation against historical repayment/default data before live lending use.

## Operational Notes

- The worker must register `worker.tasks.process_application.process_application`; this is verified in Docker logs during final testing.
- The outbox poller starts when the Celery worker is ready.
- API and worker images set `PYTHONPATH=/app` so imports are stable inside containers.
- `docker-compose.yml` does not run API with `--reload`; dev reload belongs in `docker-compose.dev.yml`.
- The local stack intentionally keeps infrastructure simple. Production deployment should move secrets, TLS, identity, logging retention, container hardening, and network policy into the target platform.

## Project Principles

- Determinism beats hidden randomness.
- Idempotency is part of correctness.
- Audit logs must be useful and PII-safe.
- Risk score, data reliability, and confidence are separate concepts.
- Fallback data should reduce confidence and route ambiguous cases to review.
- The explanation endpoint must explain what actually happened, using the audit trail.
- The README should describe the system as it is, not as a sales page.
