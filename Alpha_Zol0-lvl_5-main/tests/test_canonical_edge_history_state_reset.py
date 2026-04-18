"""
P3-5  reset_canonical_edge_history_state() — verifies all global state is cleared.
"""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "canonical_edge_history_linkage.py"


def _load_fresh_module():
    """Load a fresh instance of the module (un-cached) to avoid state bleed."""
    mod_name = f"canonical_edge_history_linkage_{id(object())}"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reset_clears_edge_history_state():
    """
    After populating canonical_edge_history_state, reset must clear it
    so that len(canonical_edge_history_state) == 0.
    """
    module = _load_fresh_module()

    # Populate state by accessing a nested key (defaultdict creates it)
    _ = module.canonical_edge_history_state["BTCUSDTM"]
    assert len(module.canonical_edge_history_state) == 1

    module.reset_canonical_edge_history_state()

    assert len(module.canonical_edge_history_state) == 0, (
        "canonical_edge_history_state must be empty after reset"
    )


def test_reset_clears_unresolved_pool():
    """After appending to canonical_unresolved_pool, reset must clear it."""
    module = _load_fresh_module()

    module.canonical_unresolved_pool.append({"symbol": "BTCUSDTM"})
    module.canonical_unresolved_pool.append({"symbol": "ETHUSDTM"})
    assert len(module.canonical_unresolved_pool) == 2

    module.reset_canonical_edge_history_state()

    assert len(module.canonical_unresolved_pool) == 0, (
        "canonical_unresolved_pool must be empty after reset"
    )


def test_reset_zeroes_promotion_count():
    """canonical_promotion_count must be 0 after reset even if incremented."""
    module = _load_fresh_module()

    # Simulate promotion_count being incremented
    module.canonical_promotion_count = 7
    module.reset_canonical_edge_history_state()

    assert module.canonical_promotion_count == 0, (
        "canonical_promotion_count must be 0 after reset"
    )


def test_reset_zeroes_trace_seq():
    """canonical_trace_seq must be 0 after reset; next call must return 1."""
    module = _load_fresh_module()

    # Advance the trace seq
    seq1 = module.next_canonical_trace_seq()
    seq2 = module.next_canonical_trace_seq()
    assert seq1 == 1
    assert seq2 == 2

    module.reset_canonical_edge_history_state()

    assert module.canonical_trace_seq == 0, (
        "canonical_trace_seq must be 0 immediately after reset"
    )
    # Next call must return 1 (incrementing from 0)
    next_seq = module.next_canonical_trace_seq()
    assert next_seq == 1, (
        f"After reset, first next_canonical_trace_seq() must be 1, got {next_seq}"
    )


def test_reset_is_idempotent():
    """Calling reset twice must leave state empty (no errors, no duplicate)."""
    module = _load_fresh_module()

    module.canonical_edge_history_state["ETHUSDTM"]["TF"]["buy"]["count"] = 3
    module.canonical_unresolved_pool.append({"x": 1})
    module.canonical_promotion_count = 5
    module.next_canonical_trace_seq()

    module.reset_canonical_edge_history_state()
    module.reset_canonical_edge_history_state()  # second call must not raise

    assert len(module.canonical_edge_history_state) == 0
    assert len(module.canonical_unresolved_pool) == 0
    assert module.canonical_promotion_count == 0
    assert module.canonical_trace_seq == 0
