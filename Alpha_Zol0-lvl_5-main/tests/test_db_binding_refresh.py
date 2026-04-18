import logging
import importlib
import sqlite3
from pathlib import Path


def _count_rows(db_path: Path, event_name: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM logs WHERE event = ?",
            (event_name,),
        ).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def test_db_utils_rebinds_to_reloaded_db_models(monkeypatch, tmp_path):
    db_path_one = tmp_path / "db_one.db"
    db_path_two = tmp_path / "db_two.db"

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path_one.as_posix()}")

    import core.db_models as db_models
    import core.db_utils as db_utils

    importlib.reload(db_models)
    importlib.reload(db_utils)
    db_models.init_db()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path_two.as_posix()}")
    importlib.reload(db_models)
    db_models.init_db()

    assert db_utils.save_log_to_db(
        "integrity_event",
        {"marker": "current_db"},
    ) is True
    assert _count_rows(db_path_one, "integrity_event") == 0
    assert _count_rows(db_path_two, "integrity_event") == 1


def test_save_log_to_db_emits_reason_code_when_breadcrumb_readback_missing(
    monkeypatch, caplog
):
    import core.db_utils as dbu

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeSession:
        def add(self, *args, **kwargs):
            return None

        def commit(self):
            return None

        def query(self, *args, **kwargs):
            return FakeQuery()

        def close(self):
            return None

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setattr(dbu, "DATABASE_URL", "postgresql://unit-test")
    monkeypatch.setattr(dbu, "SessionLocal", lambda: FakeSession())
    caplog.set_level(logging.WARNING)

    ok = dbu.save_log_to_db(
        "canonical_explicit_post_promotion_post_invoke_emit_attempt_enter",
        {"marker": "breadcrumb"},
    )

    assert ok is True
    assert any(
        "reason_code=canonical_post_promotion_readback_missing" in record.message
        for record in caplog.records
    )


def test_save_log_to_db_emits_reason_code_when_breadcrumb_readback_errors(
    monkeypatch, caplog
):
    import core.db_utils as dbu

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            raise RuntimeError("readback failed")

    class FakeSession:
        def add(self, *args, **kwargs):
            return None

        def commit(self):
            return None

        def query(self, *args, **kwargs):
            return FakeQuery()

        def close(self):
            return None

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setattr(dbu, "DATABASE_URL", "postgresql://unit-test")
    monkeypatch.setattr(dbu, "SessionLocal", lambda: FakeSession())
    caplog.set_level(logging.WARNING)

    ok = dbu.save_log_to_db(
        "canonical_explicit_post_promotion_post_invoke_emit_attempt_enter",
        {"marker": "breadcrumb"},
    )

    assert ok is True
    assert any(
        "reason_code=canonical_post_promotion_readback_error" in record.message
        for record in caplog.records
    )
