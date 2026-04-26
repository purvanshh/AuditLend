from datetime import UTC, datetime
from typing import Any

from models.audit_log import AuditLog


def build_explanation(audit_entries: list[AuditLog], decision_output: dict[str, Any]) -> dict[str, Any]:
    """
    Constructs a human-readable explanation from the raw audit trail.
    Templates handle successful, degraded, and manual review decisions.
    """
    decision = decision_output.get("decision")
    confidence = decision_output.get("confidence")
    rule_version = decision_output.get("rule_version")
    factors = _factor_objects(decision_output.get("factors", []))
    timeline = [_timeline_entry(entry) for entry in audit_entries]
    summary = _summary(decision, confidence, audit_entries, decision_output)

    return {
        "decision": decision,
        "summary": summary,
        "factors": factors,
        "timeline": timeline,
        "rule_version": rule_version,
        "generated_at": datetime.now(UTC),
    }


def _summary(
    decision: str | None,
    confidence: float | None,
    audit_entries: list[AuditLog],
    decision_output: dict[str, Any],
) -> str:
    degraded_steps = [
        entry
        for entry in audit_entries
        if entry.error_type is not None or entry.fallback_used
    ]
    threshold_reason = any(
        "Confidence below threshold" in str(factor)
        for factor in decision_output.get("factors", [])
    )

    if decision == "NEEDS_REVIEW" and threshold_reason:
        causes = _degradation_sentence(degraded_steps)
        confidence_text = _confidence_text(confidence)
        return (
            f"The system had insufficient reliable data to make an automatic decision. "
            f"{causes} Confidence {confidence_text} is below the required threshold, "
            "so this application has been sent for manual review."
        )

    if degraded_steps:
        causes = _degradation_sentence(degraded_steps)
        return f"Decision {decision} was produced with degraded data quality. {causes} Confidence is {_confidence_text(confidence)}."

    return f"Decision {decision} was produced from verified data sources with confidence {_confidence_text(confidence)}."


def _degradation_sentence(entries: list[AuditLog]) -> str:
    if not entries:
        return "No external data degradation was recorded."

    parts = []
    for entry in entries:
        label = entry.step.replace("_FETCH", "").replace("_", " ").title()
        status = entry.error_type or "fallback"
        parts.append(f"{label}: {status}")
    return "Data quality issues recorded: " + "; ".join(parts) + "."


def _factor_objects(factors: list[str]) -> list[dict[str, str]]:
    objects: list[dict[str, str]] = []
    for factor in factors:
        if " = " not in factor:
            continue
        name_source, value = factor.split(" = ", 1)
        if "(" in name_source and ")" in name_source:
            name = name_source.split("(", 1)[0].strip().replace("_", " ").title()
            status = name_source.split("(", 1)[1].split(")", 1)[0]
        else:
            name = name_source.replace("_", " ").title()
            status = "derived"
        objects.append({"name": name, "value": value, "status": status})
    return objects


def _timeline_entry(entry: AuditLog) -> dict[str, Any]:
    status = entry.error_type
    if status is None and entry.output_snapshot:
        status = str(entry.output_snapshot.get("decision") or entry.output_snapshot.get("status") or "SUCCESS")
    return {
        "step": entry.step,
        "status": status or "SUCCESS",
        "timestamp": entry.created_at,
    }


def _confidence_text(confidence: float | None) -> str:
    return "unknown" if confidence is None else f"{confidence:.2f}"
