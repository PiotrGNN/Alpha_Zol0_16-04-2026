import importlib

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("PAID_BETA_TOKEN_SECRET", "test-secret-that-is-at-least-32-characters")
    monkeypatch.setenv("PAID_BETA_DATABASE_URL", f"sqlite:///{tmp_path / 'paid_beta.db'}")
    import paid_beta.config as config
    import paid_beta.database as database
    import paid_beta.models as models
    import paid_beta.analytics as analytics
    import paid_beta.dependencies as dependencies
    import paid_beta.billing as billing
    import paid_beta.app as app_module

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(models)
    importlib.reload(analytics)
    importlib.reload(dependencies)
    importlib.reload(billing)
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_health_and_status_do_not_expose_live_trading(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["public_live_trading"] is False
        assert client.get("/start-live").status_code == 404


def test_register_login_and_protected_me(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        register = client.post("/auth/register", json={"email": "user@example.com", "password": "correct-horse-battery"})
        assert register.status_code == 201
        token = register.json()["access_token"]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == "user@example.com"
        login = client.post("/auth/login", json={"email": "user@example.com", "password": "correct-horse-battery"})
        assert login.status_code == 200


def test_admin_endpoints_are_role_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("PAID_BETA_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    with _client(monkeypatch, tmp_path) as client:
        user = client.post("/auth/register", json={"email": "user@example.com", "password": "correct-horse-battery"}).json()
        denied = client.get("/internal/funnel", headers={"Authorization": f"Bearer {user['access_token']}"})
        assert denied.status_code == 403
        admin = client.post("/auth/register", json={"email": "admin@example.com", "password": "correct-horse-battery"}).json()
        allowed = client.get("/internal/funnel", headers={"Authorization": f"Bearer {admin['access_token']}"})
        assert allowed.status_code == 200


class _FakeSession:
    id = "cs_test_123"
    url = "https://checkout.example.test/session"
    status = "open"


class _FakeStripe:
    class checkout:
        class Session:
            @staticmethod
            def create(**kwargs):
                assert kwargs["mode"] in {"subscription", "payment"}
                assert kwargs["metadata"]["user_id"]
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
            assert secret == ""
            return cls.event


def test_checkout_session_and_idempotent_webhook(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        import paid_beta.billing as billing

        monkeypatch.setattr(billing, "_stripe", lambda: _FakeStripe)
        register = client.post(
            "/auth/register",
            json={"email": "buyer@example.com", "password": "correct-horse-battery"},
        )
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        checkout = client.post(
            "/billing/checkout",
            json={"product_code": "pro"},
            headers=headers,
        )
        assert checkout.status_code == 200
        assert checkout.json()["session_id"] == "cs_test_123"

        user_id = client.get("/auth/me", headers=headers).json()["id"]
        _FakeStripe.Webhook.event = {
            "id": "evt_test_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "customer": "cus_test_123",
                    "subscription": "sub_test_123",
                    "metadata": {"user_id": str(user_id), "product_code": "pro"},
                }
            },
        }
        webhook = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "test-signature"},
        )
        assert webhook.status_code == 200
        assert webhook.json() == {"ok": True, "duplicate": False}
        assert client.get("/auth/me", headers=headers).json()["active_plan"] == "pro"

        duplicate = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "test-signature"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json() == {"ok": True, "duplicate": True}
