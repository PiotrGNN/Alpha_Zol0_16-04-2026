from concurrent.futures import ThreadPoolExecutor

from paid_beta.billing_lifecycle import store_event_once
from paid_beta.database import SessionLocal
from paid_beta.models import WebhookEvent


def _store(event):
    db = SessionLocal()
    try:
        stored = store_event_once(db, event)
        if stored is None:
            db.rollback()
            return False
        stored.processed = True
        db.commit()
        return True
    finally:
        db.close()


def test_concurrent_webhook_delivery_is_idempotent():
    event = {
        "id": "evt_concurrent_replay",
        "type": "checkout.session.completed",
        "data": {"object": {}},
    }
    cleanup = SessionLocal()
    try:
        cleanup.query(WebhookEvent).filter(
            WebhookEvent.provider_event_id == event["id"]
        ).delete(synchronize_session=False)
        cleanup.commit()
    finally:
        cleanup.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_store, [event, event]))

    assert sorted(results) == [False, True]

    verification = SessionLocal()
    try:
        assert (
            verification.query(WebhookEvent)
            .filter(WebhookEvent.provider_event_id == event["id"])
            .count()
            == 1
        )
    finally:
        verification.close()
