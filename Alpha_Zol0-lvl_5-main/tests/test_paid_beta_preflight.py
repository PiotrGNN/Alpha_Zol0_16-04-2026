from scripts.paid_beta_preflight import structural_checks


def _valid_env():
    return {
        "PAID_BETA_ENV": "production",
        "PAID_BETA_DATABASE_URL": "postgresql://user:password@db.example.test/paid_beta",
        "PAID_BETA_TOKEN_SECRET": "x" * 32,
        "PAID_BETA_APP_URL": "https://beta.example.test",
        "PAID_BETA_CORS_ORIGINS": "https://beta.example.test",
        "PAID_BETA_EXPOSE_PASSWORD_RESET_TOKEN": "0",
        "PAID_BETA_ALLOW_ADMIN_BOOTSTRAP": "0",
        "STRIPE_SECRET_KEY": "sk_test_placeholder",
        "STRIPE_WEBHOOK_SECRET": "whsec_placeholder",
        "STRIPE_PRICE_STARTER": "price_starter",
        "STRIPE_PRICE_PRO": "price_pro",
        "STRIPE_PRICE_REPORT": "price_report",
        "PAID_BETA_SMTP_HOST": "smtp.example.test",
        "PAID_BETA_SMTP_FROM": "no-reply@example.test",
        "PAID_BETA_TERMS_APPROVED": "1",
        "PAID_BETA_PRIVACY_APPROVED": "1",
        "PAID_BETA_REFUNDS_APPROVED": "1",
        "PAID_BETA_RISK_DISCLOSURE_APPROVED": "1",
    }


def test_structural_preflight_passes_complete_test_mode_configuration():
    checks = structural_checks(_valid_env())
    assert checks
    assert all(check.passed for check in checks)
    assert all("placeholder" not in check.detail for check in checks)


def test_structural_preflight_blocks_live_key_and_unapproved_legal_flags():
    env = _valid_env()
    env["STRIPE_SECRET_KEY"] = "sk_live_do_not_use"
    env["PAID_BETA_TERMS_APPROVED"] = "0"

    checks = {check.name: check for check in structural_checks(env)}

    assert checks["stripe_test_mode"].passed is False
    assert checks["legal:PAID_BETA_TERMS_APPROVED"].passed is False


def test_structural_preflight_never_returns_secret_values():
    env = _valid_env()
    secret = env["PAID_BETA_TOKEN_SECRET"]
    stripe_key = env["STRIPE_SECRET_KEY"]
    rendered = repr(structural_checks(env))
    assert secret not in rendered
    assert stripe_key not in rendered
