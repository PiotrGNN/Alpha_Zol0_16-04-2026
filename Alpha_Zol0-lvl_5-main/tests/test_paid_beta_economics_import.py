from scripts.import_paid_beta_economics_period import validate_payload


def _payload():
    return {
        "period_start": "2026-06-01",
        "period_end": "2026-06-07",
        "source": "stripe-staging-week-2026-23",
        "currency": "PLN",
        "gross_revenue": 1000.0,
        "payment_fees": 30.0,
        "refunds": 0.0,
        "hosting_cost": 40.0,
        "support_cost": 50.0,
        "acquisition_spend": 100.0,
        "other_variable_cost": 10.0,
        "active_customers": 20,
        "new_customers": 5,
        "churned_customers": 1,
        "activated_customers": 4,
        "checkout_started": 10,
        "checkout_completed": 8,
        "failed_payments": 2,
        "recovered_payments": 1,
        "support_minutes": 200,
    }


def test_valid_weekly_payload_passes():
    assert validate_payload(_payload()) == []


def test_invalid_period_and_inconsistent_counts_are_rejected():
    payload = _payload()
    payload["period_end"] = "2026-06-08"
    payload["checkout_completed"] = 11
    payload["activated_customers"] = 6
    payload["recovered_payments"] = 3

    errors = validate_payload(payload)

    assert "period must contain exactly 7 calendar days" in errors
    assert "checkout_completed exceeds checkout_started" in errors
    assert "activated_customers exceeds new_customers" in errors
    assert "recovered_payments exceeds failed_payments" in errors


def test_missing_or_negative_values_are_rejected():
    payload = _payload()
    del payload["refunds"]
    assert validate_payload(payload)[0].startswith("missing fields:")

    payload = _payload()
    payload["hosting_cost"] = -1
    assert "hosting_cost must be a non-negative number" in validate_payload(payload)
