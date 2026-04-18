# InfinityLayerLogger.py – logowanie zdarzeń, decyzji, statusów dla warstwy ∞

import logging
import os
import threading
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)
_SQLITE_LOG_PERSIST_LOCK = threading.RLock()
_SQLITE_PAPER_HANDOFF_MICROSTAGE_EVENTS = {
    "handoff_child_mailbox_observed",
    "handoff_child_mailbox_dequeue_enter",
    "handoff_child_dispatch_enter",
    "handoff_child_dispatch_accept_for_processing",
    "handoff_child_loop_enter",
    "handoff_child_callback_enter",
    "post_promotion_force_cycle_accept_path_enter",
    "handoff_pre_decision_return",
    "post_promotion_force_cycle_enqueue_enter",
    "post_promotion_force_cycle_enqueue_completed",
    "post_promotion_force_cycle_enqueue_return",
    "post_promotion_force_cycle_enqueue_skip",
    "post_promotion_force_cycle_enqueue_skip_reason",
    "post_promotion_force_cycle_accept_path_return",
    "handoff_decision_emit_prelude_enter",
    "post_promotion_force_cycle_handoff_decision",
    "handoff_decision_emit_call_done",
    "handoff_decision_emit_prelude_exit",
}
_SQLITE_CLOSE_WINDOW_OVERLAP_EVENTS = {
    "ensemble_signals",
    "pre_entry_candidate_rejection_trace",
    "entry_live_edge_eval",
    "side_guard_block",
    "diagnostic_gate_trace",
    "tf_trend_entry_soft_score",
    "tf_trend_entry_eval",
    "entry_runtime_degrade_shadow_policy",
    "post_close_summary_pre_assembly",
    "post_close_summary_assembly_enter",
    "post_close_summary_payload_built",
    "post_close_summary_emit_attempt",
    "entry_gate_decision_summary",
    "post_close_summary_emit_done",
    "risk_decision",
}


def _serialize_sqlite_logger_writes() -> bool:
    database_url = str(os.getenv("DATABASE_URL", "sqlite:///./zol0.db") or "").strip()
    return database_url.startswith("sqlite") and os.environ.get("LIVE", "0") != "1"


def _skip_sqlite_handoff_microstage_persist(event_name: str) -> bool:
    return (
        _serialize_sqlite_logger_writes()
        and isinstance(event_name, str)
        and event_name in _SQLITE_PAPER_HANDOFF_MICROSTAGE_EVENTS
    )


def _sqlite_enqueue_window_sentinel_path() -> Path | None:
    raw_path = str(
        os.getenv("CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL", "") or ""
    ).strip()
    if not raw_path:
        return None
    try:
        return Path(raw_path)
    except Exception:
        return None


def _skip_sqlite_close_window_overlap_persist(
    event_name: str,
) -> tuple[bool, str | None]:
    if (
        not _serialize_sqlite_logger_writes()
        or not isinstance(event_name, str)
        or event_name not in _SQLITE_CLOSE_WINDOW_OVERLAP_EVENTS
    ):
        return False, None
    sentinel_path = _sqlite_enqueue_window_sentinel_path()
    if sentinel_path is None or not sentinel_path.exists():
        return False, None
    return True, f"controlled_kpi_close_enqueue_window_overlap:{event_name}"


def _append_internal_memory_events_enabled() -> bool:
    return os.environ.get("INFINITY_LOGGER_APPEND_INTERNAL_EVENTS", "0") == "1"


class InfinityLayerLogger:
    def __init__(self):
        # In-memory store for quick tests and runtime inspection
        self.logs = []

    def log(self, event: str, details: Dict = None):
        append_internal_events = _append_internal_memory_events_enabled()
        if details is None and isinstance(event, dict):
            payload_event = event.get("event")
            details = dict(event)
            event = str(payload_event or "paper_runtime")
        # Append to in-memory logs for tests
        entry = {"event": event, "details": details or {}}
        self.logs.append(entry)
        # Also persist log to the DB
        from core.db_utils import save_log_to_db
        import json

        def _persist(event_name: str, payload_text: str):
            if _skip_sqlite_handoff_microstage_persist(event_name):
                return True, f"sqlite_handoff_microstage_skip:{event_name}"
            skip_close_window, skip_reason = _skip_sqlite_close_window_overlap_persist(
                event_name
            )
            if skip_close_window:
                return True, skip_reason
            if _serialize_sqlite_logger_writes():
                with _SQLITE_LOG_PERSIST_LOCK:
                    return save_log_to_db(event=event_name, details=payload_text), None
            return save_log_to_db(event=event_name, details=payload_text), None

        payload = details or {}
        correlation_id = None
        if isinstance(payload, dict):
            correlation_id = payload.get("correlation_id")
        serialized_details = None
        persistence_skip_reason = None
        try:
            serialized_details = json.dumps(payload, default=str)
        except Exception as exc:
            fail_payload = {
                "event": "critical_path_exception",
                "stage": "logger.serialize",
                "exception_class": type(exc).__name__,
                "exception_message": str(exc),
                "correlation_id": correlation_id,
            }
            if append_internal_events:
                self.logs.append(
                    {"event": "critical_path_exception", "details": fail_payload}
                )
            try:
                _persist(
                    "critical_path_exception",
                    json.dumps(fail_payload, default=str),
                )
            except Exception as persist_exc:
                logging.warning(
                    (
                        "InfinityLayerLogger: critical-path fallback "
                        "persist failed stage=logger.serialize error=%s"
                    ),
                    persist_exc,
                )
            logging.error(
                (
                    "InfinityLayerLogger: failed to serialize event=%s "
                    "stage=logger.serialize correlation_id=%s error=%s"
                ),
                event,
                correlation_id,
                exc,
            )
        if serialized_details is not None:
            try:
                persisted, skip_reason = _persist(event, serialized_details)
                persistence_skip_reason = skip_reason
                if skip_reason is not None:
                    skip_payload = {
                        "event": "sqlite_persist_skip",
                        "skipped_event": str(event),
                        "skip_reason": str(skip_reason),
                        "correlation_id": correlation_id,
                    }
                    if append_internal_events:
                        self.logs.append(
                            {"event": "sqlite_persist_skip", "details": skip_payload}
                        )
                    logging.info(
                        (
                            "InfinityLayerLogger: sqlite persist skipped event=%s "
                            "reason=%s correlation_id=%s"
                        ),
                        event,
                        skip_reason,
                        correlation_id,
                    )
                if not persisted:
                    fail_payload = {
                        "event": "critical_path_exception",
                        "stage": "logger.persist",
                        "exception_class": "PersistenceReturnedFalse",
                        "exception_message": "save_log_to_db returned False",
                        "correlation_id": correlation_id,
                    }
                    if append_internal_events:
                        self.logs.append(
                            {
                                "event": "critical_path_exception",
                                "details": fail_payload,
                            }
                        )
                    try:
                        _persist(
                            "critical_path_exception",
                            json.dumps(fail_payload, default=str),
                        )
                    except Exception as persist_exc:
                        logging.warning(
                            (
                                "InfinityLayerLogger: critical-path fallback "
                                "persist failed stage=logger.persist_false "
                                "error=%s"
                            ),
                            persist_exc,
                        )
                    logging.error(
                        (
                            "InfinityLayerLogger: DB persistence returned False "
                            "for event=%s stage=logger.persist "
                            "correlation_id=%s"
                        ),
                        event,
                        correlation_id,
                    )
            except Exception as exc:
                fail_payload = {
                    "event": "critical_path_exception",
                    "stage": "logger.persist",
                    "exception_class": type(exc).__name__,
                    "exception_message": str(exc),
                    "correlation_id": correlation_id,
                }
                if append_internal_events:
                    self.logs.append(
                        {"event": "critical_path_exception", "details": fail_payload}
                    )
                try:
                    _persist(
                        "critical_path_exception",
                        json.dumps(fail_payload, default=str),
                    )
                except Exception as persist_exc:
                    logging.warning(
                        (
                            "InfinityLayerLogger: critical-path fallback "
                            "persist failed "
                            "stage=logger.persist_exception error=%s"
                        ),
                        persist_exc,
                    )
                logging.error(
                    (
                        "InfinityLayerLogger: failed to save event=%s "
                        "stage=logger.persist correlation_id=%s error=%s"
                    ),
                    event,
                    correlation_id,
                    exc,
                )
        logging.info(
            "InfinityLayerLogger: logged event=%s persistence=%s details=%s",
            event,
            "skipped" if persistence_skip_reason is not None else "db",
            details,
        )

    def get_logs(self, event: str = None):
        if event:
            return [log for log in self.logs if log["event"] == event]
        return self.logs

    def summary(self):
        return {
            "total": len(self.logs),
            "events": list(set(log["event"] for log in self.logs)),
        }
