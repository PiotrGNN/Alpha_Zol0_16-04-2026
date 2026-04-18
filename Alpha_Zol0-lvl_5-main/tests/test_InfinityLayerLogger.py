import logging

from core.InfinityLayerLogger import InfinityLayerLogger


def test_infinity_layer_logger():
    logger = InfinityLayerLogger()
    logger.log("start", {"info": "init"})
    logger.log("decision", {"action": "buy"})
    logs = logger.get_logs()
    assert len(logs) == 2
    assert logs[0]["event"] == "start"
    assert logs[1]["details"]["action"] == "buy"
    decision_logs = logger.get_logs("decision")
    assert len(decision_logs) == 1
    assert decision_logs[0]["event"] == "decision"
    summary = logger.summary()
    assert summary["total"] == 2
    assert "start" in summary["events"]
    assert "decision" in summary["events"]


def test_sqlite_handoff_microstage_skip_reason_is_event_specific(
    monkeypatch, caplog
):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    caplog.set_level(logging.INFO)

    logger = InfinityLayerLogger()
    logger.log("handoff_child_loop_enter", {"info": "init"})

    assert any(
        "sqlite_handoff_microstage_skip:handoff_child_loop_enter" in record.message
        for record in caplog.records
    )


def test_sqlite_handoff_microstage_skip_reason_trims_database_url_whitespace(
    monkeypatch, caplog
):
    import core.db_utils as db_utils

    called = []

    def fake_save_log_to_db(*args, **kwargs):
        called.append((args, kwargs))
        return True

    sentinel_event = "handoff_child_loop_enter"
    monkeypatch.setenv("DATABASE_URL", "  sqlite:///./test.db  ")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setattr(db_utils, "save_log_to_db", fake_save_log_to_db)
    caplog.set_level(logging.INFO)

    logger = InfinityLayerLogger()
    logger.log(sentinel_event, {"info": "init"})

    assert called == []
    assert any(
        (
            "sqlite_handoff_microstage_skip:"
            f"{sentinel_event}"
        )
        in record.message
        for record in caplog.records
    )


def test_close_window_overlap_skip_reason_is_event_specific(
    monkeypatch, caplog, tmp_path
):
    sentinel_path = tmp_path / "close_window_sentinel.txt"
    sentinel_path.write_text("1", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv(
        "CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL",
        str(sentinel_path),
    )
    caplog.set_level(logging.INFO)

    logger = InfinityLayerLogger()
    logger.log("post_close_summary_pre_assembly", {"info": "init"})

    assert any(
        (
            "controlled_kpi_close_enqueue_window_overlap:"
            "post_close_summary_pre_assembly"
        )
        in record.message
        for record in caplog.records
    )


def test_log_accepts_dict_event_payload_and_normalizes_event_name(monkeypatch):
    import core.db_utils as db_utils

    persisted = []

    def fake_save_log_to_db(*, event, details):
        persisted.append((event, details))
        return True

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setattr(db_utils, "save_log_to_db", fake_save_log_to_db)

    logger = InfinityLayerLogger()
    logger.log({"event": "dict_payload_event", "value": 7})

    logs = logger.get_logs()
    assert logs[0]["event"] == "dict_payload_event"
    assert logs[0]["details"]["value"] == 7
    assert persisted
    assert persisted[0][0] == "dict_payload_event"


def test_log_serialize_failure_emits_critical_path_exception_with_fallback_warning(
    monkeypatch, caplog
):
    import core.db_utils as db_utils

    calls = {"n": 0}

    def fake_save_log_to_db(*, event, details):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("persist-down")
        return True

    class BadDict(dict):
        def items(self):
            raise TypeError("bad-keys")

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("INFINITY_LOGGER_APPEND_INTERNAL_EVENTS", "1")
    monkeypatch.setattr(db_utils, "save_log_to_db", fake_save_log_to_db)
    caplog.set_level(logging.WARNING)

    logger = InfinityLayerLogger()
    logger.log("serialize_fail", BadDict({"k": "v"}))

    critical = logger.get_logs("critical_path_exception")
    assert critical
    assert critical[0]["details"]["stage"] == "logger.serialize"
    assert any("fallback persist failed stage=logger.serialize" in r.message for r in caplog.records)


def test_log_persist_false_records_internal_critical_path_event(monkeypatch, caplog):
    import core.db_utils as db_utils

    calls = {"n": 0}

    def fake_save_log_to_db(*, event, details):
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        raise RuntimeError("fallback-persist-failed")

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("INFINITY_LOGGER_APPEND_INTERNAL_EVENTS", "1")
    monkeypatch.setattr(db_utils, "save_log_to_db", fake_save_log_to_db)
    caplog.set_level(logging.WARNING)

    logger = InfinityLayerLogger()
    logger.log("persist_false", {"correlation_id": "cid-1"})

    critical = logger.get_logs("critical_path_exception")
    assert critical
    assert critical[-1]["details"]["exception_class"] == "PersistenceReturnedFalse"
    assert any("fallback persist failed stage=logger.persist_false" in r.message for r in caplog.records)


def test_log_persist_exception_records_critical_path_and_fallback_warning(
    monkeypatch, caplog
):
    import core.db_utils as db_utils

    calls = {"n": 0}

    def fake_save_log_to_db(*, event, details):
        calls["n"] += 1
        raise RuntimeError(f"persist-exc-{calls['n']}")

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("INFINITY_LOGGER_APPEND_INTERNAL_EVENTS", "1")
    monkeypatch.setattr(db_utils, "save_log_to_db", fake_save_log_to_db)
    caplog.set_level(logging.WARNING)

    logger = InfinityLayerLogger()
    logger.log("persist_exception", {"correlation_id": "cid-2"})

    critical = logger.get_logs("critical_path_exception")
    assert critical
    assert critical[-1]["details"]["stage"] == "logger.persist"
    assert any(
        "fallback persist failed stage=logger.persist_exception" in r.message
        for r in caplog.records
    )


def test_log_sqlite_skip_records_internal_skip_event_when_enabled(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("INFINITY_LOGGER_APPEND_INTERNAL_EVENTS", "1")

    logger = InfinityLayerLogger()
    logger.log("handoff_child_loop_enter", {"correlation_id": "cid-skip"})

    skipped = logger.get_logs("sqlite_persist_skip")
    assert skipped
    assert skipped[-1]["details"]["skip_reason"] == (
        "sqlite_handoff_microstage_skip:handoff_child_loop_enter"
    )
