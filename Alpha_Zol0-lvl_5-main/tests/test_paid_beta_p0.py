import importlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


@contextmanager
def _environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PAID_BETA_ENV", "test")
    monkeypatch.setenv("PAID_BETA_TOKEN_SECRET", "test-secret-that-is-at-least-32-characters")
    monkeypatch.setenv("PAID_BETA_DATABASE_URL", f"sqlite:///{tmp_path / 'paid_beta_p0.db'}")
    monkeypatch.setenv("PAID_BETA_EXPOSE_PASSWORD_RESET_TOKEN", "1")
    monkeypatch.setenv("PAID_BETA_ADMIN_BOOTSTRAP_SECRET", "bootstrap-token-that-is-at-least-32-characters")
    monkeypatch.setenv("STRIPE_PRICE_STARTER", "price_test_starter")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_test_pro")
    monkeypatch.setenv("STRIPE_PRICE_REPORT", "price_test_report")

    import paid_beta.config as config
    import paid_beta.database as database
    import paid_beta.models as models
    import paid_beta.analytics as analytics
    import paid_beta.audit as audit
    import paid_beta.entitlements as entitlements
    import paid_beta.dependencies as dependencies
    import paid_beta.middleware as middleware
    import paid_beta.mailer as mailer
    import paid_beta.session as session
    import paid_beta.password_reset as password_reset
    import paid_beta.billing as billing
    import paid_beta.resources as resources
    import paid_beta.app as app_module

    for module in (
        config,
        database,
        models,
        analytics,
        audit,
        entitlements,
        dependencies,
        middleware,
        mailer,
        session,
        password_reset,
        billing,
        resources,
        app_module,
    ):
        importlib.reload(module)

    with TestClient(app_module.app) as client:
        yield client, database, models, billing


def _register(client, email):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _add_subscription(database, models, email, plan, status="active"):
    db = database.SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).one()
        item = models.Subscription(
            user_id=user.id,
            plan_code=plan,
            provider="test",
            provider_subscription_id=f"sub_{email}_{plan}",
            status=status,
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(item)
        db.commit()
        return user.id
    finally:
        db.close()


def test_entitlement_matrix(monkeypatch, tmp_path):
    with _environment(monkeypatch, tmp_path) as (client, database, models, _):
        free_token = _register(client, "free@example.com")
        starter_token = _register(client, "starter@example.com")
        pro_token = _register(client, "pro@example.com")
        _add_subscription(database, models, "starter@example.com", "starter")
        _add_subscription(database, models, "pro@example.com", "pro")

        assert client.get("/resources/signals", headers=_headers(free_token)).status_code == 403
        assert client.get("/resources/artifacts/strategy-backtest-evidence", headers=_headers(starter_token)).status_code == 403
        assert client.post(
            "/resources/alerts",
            headers=_headers(starter_token),
            json={"name": "BTC move", "symbol": "BTCUSDTM", "condition": {"move_pct": 1}},
        ).status_code == 403

        assert client.get("/resources/artifacts/paper-market-weekly", headers=_headers(starter_token)).status_code == 200
        assert client.get("/resources/artifacts/strategy-backtest-evidence", headers=_headers(pro_token)).status_code == 200
        assert client.post(
            "/resources/alerts",
            headers=_headers(pro_token),
            json={"name": "BTC move", "symbol": "BTCUSDTM", "condition": {"move_pct": 1}},
        ).status_code == 201
        assert client.get("/resources/export/artifacts", headers=_headers(pro_token)).status_code == 200


def test_canceled_and_past_due_subscriptions_lose_access(monkeypatch, tmp_path):
    with _environment(monkeypatch, tmp_path) as (client, database, models, _):
        token = _register(client, "billing@example.com")
        user_id = _add_subscription(database, models, "billing@example.com", "pro")
        assert client.get("/resources/artifacts/strategy-backtest-evidence", headers=_headers(token)).status_code == 200

        db = database.SessionLocal()
        try:
            sub = db.query(models.Subscription).filter(models.Subscription.user_id == user_id).one()
            sub.status = "past_due"
            db.commit()
        finally:
            db.close()
        assert client.get("/resources/artifacts/strategy-backtest-evidence", headers=_headers(token)).status_code == 403

        db = database.SessionLocal()
        try:
            sub = db.query(models.Subscription).filter(models.Subscription.user_id == user_id).one()
            sub.status = "canceled"
            db.commit()
        finally:
            db.close()
        assert client.get("/resources/signals", headers=_headers(token)).status_code == 403


def test_logout_and_password_reset_revoke_old_sessions(monkeypatch, tmp_path):
    with _environment(monkeypatch, tmp_path) as (client, _, _, _):
        token = _register(client, "session@example.com")
        assert client.get("/auth/me", headers=_headers(token)).status_code == 200
        assert client.post("/auth/logout", headers=_headers(token)).status_code == 204
        assert client.get("/auth/me", headers=_headers(token)).status_code == 401

        login = client.post(
            "/auth/login",
            json={"email": "session@example.com", "password": "correct-horse-battery"},
        )
        current_token = login.json()["access_token"]
        requested = client.post(
            "/auth/password-reset/request", json={"email": "session@example.com"}
        )
        reset_token = requested.json()["reset_token"]
        confirmed = client.post(
            "/auth/password-reset/confirm",
            json={"token": reset_token, "new_password": "new-correct-horse-battery"},
        )
        assert confirmed.status_code == 200
        assert client.get("/auth/me", headers=_headers(current_token)).status_code == 401
        assert client.post(
            "/auth/login",
            json={"email": "session@example.com", "password": "correct-horse-battery"},
        ).status_code == 401
        assert client.post(
            "/auth/login",
            json={"email": "session@example.com", "password": "new-correct-horse-battery"},
        ).status_code == 200


class _FakeSession:
    id = "cs_report_123"
    url = "https://checkout.example.test/session"
    status = "open"
    payment_status = "unpaid"
    payment_intent = "pi_report_123"


class _FakeStripe:
    class checkout:
        class Session:
            @staticmethod
            def create(**kwargs):
                assert kwargs["metadata"]["artifact_id"]
                return _FakeSession()

    class billing_portal:
        class Session:
            @staticmethod
            def create(**kwargs):
                return type("Portal", (), {"url": "https://billing.example.test/portal"})()

    class Webhook:
        event = None

        @classmethod
        def construct_event(cls, payload, signature, secret):
            assert signature == "test-signature"
            return cls.event


def test_one_time_report_is_artifact_scoped_and_refund_revokes(monkeypatch, tmp_path):
    with _environment(monkeypatch, tmp_path) as (client, database, models, billing):
        monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe)
        token = _register(client, "report@example.com")
        headers = _headers(token)

        assert client.get("/resources/artifacts/single-research-report", headers=headers).status_code == 403
        assert client.get("/resources/artifacts/strategy-backtest-evidence", headers=headers).status_code == 403

        checkout = client.post(
            "/billing/checkout",
            headers=headers,
            json={"product_code": "report", "artifact_slug": "single-research-report"},
        )
        assert checkout.status_code == 200
        user_id = client.get("/auth/me", headers=headers).json()["id"]

        db = database.SessionLocal()
        try:
            artifact = db.query(models.ProductArtifact).filter(models.ProductArtifact.slug == "single-research-report").one()
            artifact_id = artifact.id
        finally:
            db.close()

        _FakeStripe.Webhook.event = {
            "id": "evt_report_paid",
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_report_123",
                "payment_status": "paid",
                "payment_intent": "pi_report_123",
                "metadata": {
                    "user_id": str(user_id),
                    "product_code": "report",
                    "artifact_id": str(artifact_id),
                    "artifact_slug": "single-research-report",
                },
            }},
        }
        paid = client.post("/billing/webhook", content=b"{}", headers={"Stripe-Signature": "test-signature"})
        assert paid.status_code == 200
        assert client.get("/resources/artifacts/single-research-report", headers=headers).status_code == 200
        assert client.get("/resources/artifacts/strategy-backtest-evidence", headers=headers).status_code == 403

        duplicate = client.post("/billing/webhook", content=b"{}", headers={"Stripe-Signature": "test-signature"})
        assert duplicate.json() == {"ok": True, "duplicate": True}

        _FakeStripe.Webhook.event = {
            "id": "evt_report_refund",
            "type": "refund.created",
            "data": {"object": {"payment_intent": "pi_report_123", "metadata": {}}},
        }
        refunded = client.post("/billing/webhook", content=b"{}", headers={"Stripe-Signature": "test-signature"})
        assert refunded.status_code == 200
        assert client.get("/resources/artifacts/single-research-report", headers=headers).status_code == 403


def test_missing_payment_status_never_grants_report(monkeypatch, tmp_path):
    with _environment(monkeypatch, tmp_path) as (client, database, models, billing):
        monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe)
        token = _register(client, "unpaid@example.com")
        headers = _headers(token)
        client.post(
            "/billing/checkout",
            headers=headers,
            json={"product_code": "report", "artifact_slug": "single-research-report"},
        )
        user_id = client.get("/auth/me", headers=headers).json()["id"]
        db = database.SessionLocal()
        try:
            artifact_id = db.query(models.ProductArtifact).filter(models.ProductArtifact.slug == "single-research-report").one().id
        finally:
            db.close()
        _FakeStripe.Webhook.event = {
            "id": "evt_report_missing_status",
            "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_report_123",
                "payment_intent": "pi_report_123",
                "metadata": {"user_id": str(user_id), "product_code": "report", "artifact_id": str(artifact_id)},
            }},
        }
        assert client.post("/billing/webhook", content=b"{}", headers={"Stripe-Signature": "test-signature"}).status_code == 200
        assert client.get("/resources/artifacts/single-research-report", headers=headers).status_code == 403
