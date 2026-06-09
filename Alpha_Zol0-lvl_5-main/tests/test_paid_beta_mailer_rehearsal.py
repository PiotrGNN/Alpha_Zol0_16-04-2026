import importlib

import pytest


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args = None
        self.message = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


def _reload_mailer(monkeypatch, *, environment="test", configured=True):
    monkeypatch.setenv("PAID_BETA_ENV", environment)
    monkeypatch.setenv(
        "PAID_BETA_TOKEN_SECRET",
        "test-secret-that-is-at-least-32-characters",
    )
    if configured:
        monkeypatch.setenv("PAID_BETA_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("PAID_BETA_SMTP_PORT", "587")
        monkeypatch.setenv("PAID_BETA_SMTP_USERNAME", "smtp-user")
        monkeypatch.setenv("PAID_BETA_SMTP_PASSWORD", "smtp-password")
        monkeypatch.setenv("PAID_BETA_SMTP_FROM", "no-reply@example.test")
        monkeypatch.setenv("PAID_BETA_SMTP_STARTTLS", "1")
    else:
        for name in (
            "PAID_BETA_SMTP_HOST",
            "PAID_BETA_SMTP_USERNAME",
            "PAID_BETA_SMTP_PASSWORD",
            "PAID_BETA_SMTP_FROM",
        ):
            monkeypatch.delenv(name, raising=False)

    import paid_beta.config as config
    import paid_beta.mailer as mailer

    importlib.reload(config)
    importlib.reload(mailer)
    return mailer


def test_password_reset_uses_starttls_auth_and_expected_message(monkeypatch):
    mailer = _reload_mailer(monkeypatch)
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    reset_url = "https://beta.example.test/reset?token=redacted-fixture"
    mailer.send_password_reset(
        email="user@example.test",
        reset_url=reset_url,
    )

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == (
        "smtp.example.test",
        587,
        15,
    )
    assert smtp.starttls_called is True
    assert smtp.login_args == ("smtp-user", "smtp-password")
    assert smtp.message["From"] == "no-reply@example.test"
    assert smtp.message["To"] == "user@example.test"
    assert smtp.message["Subject"] == "ZoL0 Analytics password reset"
    assert reset_url in smtp.message.get_content()


def test_production_missing_smtp_configuration_fails_closed(monkeypatch):
    mailer = _reload_mailer(
        monkeypatch,
        environment="production",
        configured=False,
    )

    with pytest.raises(
        RuntimeError,
        match="password reset email delivery is not configured",
    ):
        mailer.send_password_reset(
            email="user@example.test",
            reset_url="https://beta.example.test/reset",
        )
