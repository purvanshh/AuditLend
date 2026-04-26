# AuditLend: Production-Grade Credit Decision Engine (CDE v2)

This repository contains the implementation of a production‑ready credit decision engine designed to replace brittle, non‑deterministic loan origination systems. The engine is built from the ground up to survive real‑world failure, produce auditable decisions, and degrade gracefully when data quality falters.

## Key Features

- **Failure‑first design**: All error states are explicit, request‑triggerable, and reproducible for deterministic testing and chaos engineering.
- **Confidence scoring**: The system evaluates its confidence in data and automatically routes low‑confidence cases (e.g., when forced to use fallback data) to human review.
- **Compliance‑grade audit trail**: Every decision is fully traceable to its raw inputs, fallback usage, and rule version, fulfilling regulatory requirements (e.g., GDPR, FCRA).
- **Idempotency by construction**: Built to prevent duplicate processing or duplicate loan creations, even under concurrent retries or network partitions.
- **Explainability**: Capable of generating human-readable explanations citing the factors that influenced the outcome.

## Architecture

- **FastAPI**: API layer handling application intake, idempotency verification, and explanation endpoints.
- **Celery Workers**: Handles asynchronous job processing for data fetching and executing the decision computation.
- **PostgreSQL**: Primary, durable source of truth for applications, external data snapshots, audit logs, and idempotency records.
- **Redis**: Fast cache for idempotency mappings and message broker/result backend for Celery.
- **Mock API Services**: Flask/FastAPI containers simulating external data sources (Credit Bureau, Bank Analyzer, GST Verifier) with deterministic failure injection capabilities.

## Getting Started

### Prerequisites
- Docker and Docker Compose

### Running Locally

The entire system is designed to be deployed via Docker Compose for local development and demonstration.

```bash
# Start all services (FastAPI, Celery, Redis, Postgres, and Mock APIs)
docker-compose up --build
```

### Mock API Services

The external data layers are deterministic simulators controlled by request parameters (e.g., `?fail_mode=TIMEOUT`). You can use these to thoroughly test retry behaviors, circuit breaking, and confidence degradation scenarios.

## Core API Endpoints

- `POST /api/v1/apply-loan`: Submit an application (requires `Idempotency-Key`).
- `GET /api/v1/status/{application_id}`: Poll for processing status.
- `GET /api/v1/decision/{application_id}`: Get the final automated decision (APPROVE, DECLINE, MANUAL_REVIEW) along with confidence scoring.
- `GET /api/v1/explanation/{application_id}`: Construct a human-readable narrative from the audit trail for compliance and borrower transparency.

## Testing & Quality

The system emphasizes resilience and compliance testing:
- **Idempotency chaos testing**: Proving no duplicate decisions under concurrent request storms.
- **Worker crash recovery**: Verifying applications complete correctly even if workers die mid-task.
- **Deterministic failures**: Testing fallback scenarios and circuit breakers against simulated external API outages.

## License

All rights reserved.
