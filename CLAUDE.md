# AuditLend Agent Guide

## Project Identity

AuditLend is a deterministic, idempotent, audit-grade credit decision engine. Its purpose is not only to decide whether a loan should be approved, declined, or routed to manual review, but to preserve a complete compliance trail explaining why that decision happened.

The core thesis: lending decisions must survive retries, worker crashes, third-party outages, and regulatory scrutiny.

## Architecture Summary

```text
Client
  |
  v
FastAPI API
  |-- POST /api/v1/apply-loan
  |-- GET  /api/v1/status/{application_id}
  |-- GET  /api/v1/decision/{application_id}
  |-- GET  /api/v1/explanation/{application_id}
  |
  | writes applications and idempotency records
  v
PostgreSQL <------------------------------+
  ^                                       |
  | stores audit logs, external data,     |
  | decisions, idempotency records        |
  |                                       |
Redis broker/cache                        |
  |                                       |
  v                                       |
Celery Worker ----------------------------+
  |
  | calls resilient service clients
  v
Credit Bureau Mock  Bank Analyzer Mock  GST Verifier Mock
```

## Invariants: Never Violate

- Never add `random()` to business logic. Business outputs must be deterministic from inputs.
- Never update or delete `audit_logs` rows. The audit trail is append only.
- Never skip the idempotency check before creating or processing an application.
- Never let duplicate worker delivery create duplicate decisions for a terminal application.
- Never throw or persist unclassified external-service failures. Use `FailureType`.
- Never silently drop fallback usage. If fallback is used, audit it.
- Never hardcode environment-specific URLs, thresholds, retry counts, secrets, or service endpoints.
- Never store raw PAN in audit snapshots. Redact it before audit output.
- Never make confidence degradation implicit. Penalties belong in `engine/confidence.py` and tests.

## Files You Can Modify Freely

- `api/routes/*`
- `api/schemas/*`
- `engine/*`, when adding a new rule version or explanation behavior
- `tests/*`
- `README.md`
- `mock_apis/*`, when adding deterministic test scenarios

## Files Requiring Explicit Care

- `models/audit_log.py`: audit semantics are compliance-sensitive.
- `migrations/versions/*`: never rewrite an existing migration after it has been shared; add a new one.
- `services/base.py`: retry and circuit-breaker behavior affects all integrations.
- `worker/tasks/process_application.py`: idempotency and worker recovery live here.
- `engine/confidence.py`: changing penalties changes decision confidence for every future application.

## How To Add A New Rule

1. Add a new rule version constant or branch; do not mutate historical semantics without an intentional version bump.
2. Keep the rule function pure: no I/O, time, network, database, Redis, or randomness.
3. Add factor strings that explain the input value and source.
4. Add unit tests for normal cases, boundary values, null/default behavior, and confidence interaction.
5. Confirm `rule_version` appears in the decision output and audit log.

## How To Add A New Data Source

1. Add deterministic mock behavior under `mock_apis/`.
2. Add a typed `FailureType` if the failure mode is new.
3. Add a service client extending `BaseExternalService`.
4. Define retryability explicitly. Data quality failures are usually not retryable.
5. Define fallback behavior and confidence penalties.
6. Store an `ExternalData` snapshot and audit entry for the new source.
7. Extend explanation templates so borrowers and reviewers can understand the new factor.
8. Add unit tests for success, retryable failure, non-retryable failure, fallback, and circuit behavior.

## How To Run Tests

```bash
.venv/bin/pytest tests/unit -q
```

Integration and chaos tests require PostgreSQL and Redis. With Docker running:

```bash
docker compose up --build
```

Then, in another shell:

```bash
.venv/bin/pytest tests/integration -q
.venv/bin/pytest tests/chaos -q
```

To verify engine coverage:

```bash
.venv/bin/pytest tests/unit/test_confidence.py tests/unit/test_rules.py tests/unit/test_decision_engine.py -q --cov=engine --cov-report=term-missing
```

## Common Pitfalls

- Treating Celery task IDs as exactly-once guarantees. They are not enough; use database state.
- Letting a stuck `PROCESSING` application block worker redelivery. Terminal states are idempotent; `PROCESSING` must be recoverable.
- Confusing `NEEDS_REVIEW` decision with API status. API status should be `MANUAL_REVIEW`.
- Returning different payloads for the same idempotency key. Replays must be byte-for-byte equivalent at the contract level.
- Using current time in mock success data where determinism matters. Request IDs may be random; business data must not be.
- Adding fallback values without confidence penalties.
- Writing explanations from current business logic instead of from the audit trail. Explanations must reflect what happened at decision time.
- Catching bare exceptions in service clients and losing failure classification.
