from test_paid_beta_p0 import (
    _environment,
    _headers,
    _register,
)


class _Session:
    def __init__(self, session_id, url, *, payment_intent=None):
        self.id = session_id
        self.url = url
        self.status = "open"
        self.payment_status = "unpaid"
        self.payment_intent = payment_intent


class _RehearsalStripe:
    checkout_calls = []

    class checkout:
        class Session:
            @staticmethod
            def create(**kwargs):
                _RehearsalStripe.checkout_calls.append(kwargs)
                product = kwargs["metadata"]["product_code"]
                if product == "pro":
                    return _Session("cs_pro_rehearsal", "https://checkout.example.test/pro")
                return _Session(
                    "cs_report_rehearsal",
                    "https://checkout.example.test/report",
                    payment_intent="pi_report_rehearsal",
                )

    class billing_portal:
        class Session:
            @staticmethod
            def create(**kwargs):
                assert kwargs["customer"] == "cus_rehearsal"
                return type(
                    "Portal",
                    (),
                    {"url": "https://billing.example.test/portal"},
                )()

    class Webhook:
        event = None

        @classmethod
        def construct_event(cls, payload, signature, secret):
            assert signature == "test-signature"
            return cls.event


def _send_webhook(client, event):
    _RehearsalStripe.Webhook.event = event
    response = client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "test-signature"},
    )
    assert response.status_code == 200, response.text
    return response


def test_complete_closed_beta_lifecycle(monkeypatch, tmp_path):
    with _environment(monkeypatch, tmp_path) as (client, database, models, billing):
        monkeypatch.setattr(billing, "_stripe", lambda: _RehearsalStripe)
        _RehearsalStripe.checkout_calls.clear()

        signup_token = _register(client, "rehearsal@example.com")
        signup_headers = _headers(signup_token)
        assert client.get("/auth/me", headers=signup_headers).status_code == 200

        login = client.post(
            "/auth/login",
            json={
                "email": "rehearsal@example.com",
                "password": "correct-horse-battery",
            },
        )
        assert login.status_code == 200
        headers = _headers(login.json()["access_token"])
        user_id = client.get("/auth/me", headers=headers).json()["id"]

        pro_checkout = client.post(
            "/billing/checkout",
            headers=headers,
            json={"product_code": "pro"},
        )
        assert pro_checkout.status_code == 200
        assert pro_checkout.json()["session_id"] == "cs_pro_rehearsal"

        _send_webhook(
            client,
            {
                "id": "evt_pro_paid_rehearsal",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_pro_rehearsal",
                        "customer": "cus_rehearsal",
                        "subscription": "sub_pro_rehearsal",
                        "payment_status": "paid",
                        "metadata": {
                            "user_id": str(user_id),
                            "product_code": "pro",
                        },
                    }
                },
            },
        )

        assert client.get(
            "/resources/artifacts/strategy-backtest-evidence",
            headers=headers,
        ).status_code == 200
        assert client.post(
            "/resources/alerts",
            headers=headers,
            json={
                "name": "Rehearsal BTC alert",
                "symbol": "BTCUSDTM",
                "condition": {"move_pct": 1},
            },
        ).status_code == 201

        portal = client.post("/billing/portal", headers=headers)
        assert portal.status_code == 200
        assert portal.json()["portal_url"].startswith("https://")

        _send_webhook(
            client,
            {
                "id": "evt_pro_canceled_rehearsal",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_pro_rehearsal",
                        "customer": "cus_rehearsal",
                        "metadata": {
                            "user_id": str(user_id),
                            "product_code": "pro",
                        },
                    }
                },
            },
        )
        assert client.get(
            "/resources/artifacts/strategy-backtest-evidence",
            headers=headers,
        ).status_code == 403

        report_checkout = client.post(
            "/billing/checkout",
            headers=headers,
            json={
                "product_code": "report",
                "artifact_slug": "single-research-report",
            },
        )
        assert report_checkout.status_code == 200

        db = database.SessionLocal()
        try:
            artifact_id = (
                db.query(models.ProductArtifact)
                .filter(models.ProductArtifact.slug == "single-research-report")
                .one()
                .id
            )
        finally:
            db.close()

        _send_webhook(
            client,
            {
                "id": "evt_report_paid_rehearsal",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_report_rehearsal",
                        "payment_status": "paid",
                        "payment_intent": "pi_report_rehearsal",
                        "metadata": {
                            "user_id": str(user_id),
                            "product_code": "report",
                            "artifact_id": str(artifact_id),
                            "artifact_slug": "single-research-report",
                        },
                    }
                },
            },
        )
        assert client.get(
            "/resources/artifacts/single-research-report",
            headers=headers,
        ).status_code == 200

        _send_webhook(
            client,
            {
                "id": "evt_report_refund_rehearsal",
                "type": "refund.created",
                "data": {
                    "object": {
                        "payment_intent": "pi_report_rehearsal",
                        "metadata": {},
                    }
                },
            },
        )
        assert client.get(
            "/resources/artifacts/single-research-report",
            headers=headers,
        ).status_code == 403

        assert [
            call["metadata"]["product_code"]
            for call in _RehearsalStripe.checkout_calls
        ] == ["pro", "report"]
