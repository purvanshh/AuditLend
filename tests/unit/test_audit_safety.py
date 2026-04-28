from services.audit import audit_safe_features, sanitize_audit_snapshot


def test_audit_snapshot_contains_no_pii() -> None:
    user_data = {
        "name": "Jane Doe",
        "pan": "ABCDE1234F",
        "monthly_income": 150000,
        "existing_emis": 20000,
        "loan_amount": 500000,
        "tenure_months": 36,
        "bank_statement": [{"date": "2026-01-01", "amount": 5000}],
    }

    features = audit_safe_features(user_data, risk_score_breakdown={})

    assert "Jane" not in str(features)
    assert "ABCDE" not in str(features)
    assert 150000 not in features.values()
    assert 500000 not in features.values()
    assert 20000 not in features.values()
    assert features["income_band"] == "1L-2L"
    assert features["loan_amount_band"] == "5L-10L"
    assert features["has_bank_statement"] is True
    assert "2026-01-01" not in str(features)


def test_sanitize_audit_snapshot_recursively_redacts_sensitive_fields() -> None:
    snapshot = {
        "user_data": {
            "name": "Jane Doe",
            "pan": "ABCDE1234F",
            "monthly_income": 150000,
            "existing_emis": 20000,
            "loan_amount": 500000,
            "bank_statement": [{"date": "2026-01-01", "amount": 5000}],
        },
        "nested": {"pan_hash": "abc123"},
        "bank_output": {"monthly_inflow": 120000, "average_balance": 450000},
    }

    sanitized = sanitize_audit_snapshot(snapshot)
    text = str(sanitized)

    assert "Jane Doe" not in text
    assert "ABCDE1234F" not in text
    assert "150000" not in text
    assert "20000" not in text
    assert "500000" not in text
    assert "120000" not in text
    assert "450000" not in text
    assert "2026-01-01" not in text
    assert "abc123" not in text
    assert sanitized["user_data"]["monthly_income"] == "1L-2L"
    assert sanitized["user_data"]["loan_amount"] == "5L-10L"
