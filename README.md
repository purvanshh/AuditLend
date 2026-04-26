# AuditLend: Production-Grade Credit Decision Engine

Every decision, explained. Every failure, handled. Every step, audited.

AuditLend is a deterministic credit decision engine built around idempotent intake, typed external-data failures, confidence degradation, immutable audit logs, and human-readable explanations.

## Quick Start

```bash
docker compose up --build
```

The API runs at `http://localhost:8000`; mock services run on ports `8001`, `8002`, and `8003`.

```bash
curl http://localhost:8000/health
```

## Architecture

```text
Client -> FastAPI -> PostgreSQL
             |
             v
           Redis -> Celery Worker -> Credit Bureau Mock
                                | -> Bank Analyzer Mock
                                | -> GST Verifier Mock
                                v
                         Audit + Decision + Explanation
```

## Submit An Application

```bash
curl -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-001" \
  -d '{
    "idempotency_key": "demo-001",
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
  }'
```

Replay the same request with the same idempotency key to receive the same `application_id`.

## Deterministic Failure Demo

```bash
curl -X POST http://localhost:8000/api/v1/apply-loan \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-credit-timeout" \
  -d '{
    "idempotency_key": "demo-credit-timeout",
    "user_data": {
      "name": "Jane Doe",
      "pan": "ABCDE1234F",
      "monthly_income": 120000,
      "existing_emis": 25000,
      "loan_amount": 500000,
      "tenure_months": 36
    },
    "failure_flags": {
      "credit_bureau": "TIMEOUT",
      "bank_analyzer": "PARTIAL_DATA",
      "gst_verifier": "SUCCESS"
    }
  }'
```

Then poll:

```bash
curl http://localhost:8000/api/v1/status/<application_id>
curl http://localhost:8000/api/v1/decision/<application_id>
curl http://localhost:8000/api/v1/explanation/<application_id>
```

## Core Endpoints

- `POST /api/v1/apply-loan`
- `GET /api/v1/status/{application_id}`
- `GET /api/v1/decision/{application_id}`
- `GET /api/v1/explanation/{application_id}`

## Tests

```bash
.venv/bin/pytest tests/unit -q
```

Full integration and chaos tests require PostgreSQL, Redis, and the Docker Compose stack.
