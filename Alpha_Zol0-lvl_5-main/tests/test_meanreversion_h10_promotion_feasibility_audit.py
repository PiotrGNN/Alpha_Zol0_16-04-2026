from __future__ import annotations

import json
from pathlib import Path

from scripts.meanreversion_h10_promotion_feasibility_audit import (
    CLASS_ALREADY_REACHABLE,
    CLASS_CONTAMINATED,
    CLASS_NO_OPERATING_POINT,
    CLASS_PATCH_REQUIRED,
    audit_promotion_feasibility,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_operating_point(
    path: Path,
    *,
    classification: str = "PROFITABILITY_OPERATING_POINT_CANDIDATE_FOUND",
    candidate_key: str = "BTCUSDTM:MEANREVERSION:sell:h10",
) -> None:
    _write_json(
        path,
        {
            "classification": classification,
            "summary": {
                "clean_event_count": 52,
                "contaminated_event_count": 0,
                "passing_bucket_count": 1,
                "position_open_count": 0,
            },
            "best_operating_point": {
                "candidate_key": candidate_key,
                "symbol": "BTCUSDTM",
                "canonical_strategy": "MEANREVERSION",
                "side": "sell",
                "horizon_ticks": 10,
                "sample_count": 32,
                "win_rate": 0.65625,
                "payoff_ratio": 1.22,
                "expectancy_per_signal": 0.00043,
                "cost_to_gross_ratio": 0.18,
                "passes_operating_point": True,
            },
            "profitability_claim": False,
        },
    )


def _write_blocker(
    path: Path,
    *,
    classification: str = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_ENTRY_EDGE_FILTER",
    position_open_count: int = 0,
    contaminated_event_count: int = 0,
) -> None:
    _write_json(
        path,
        {
            "classification": classification,
            "summary": {
                "position_open_count": position_open_count,
                "contaminated_event_count": contaminated_event_count,
            },
            "target_reason_counts": {"entry_edge_filtered": 42, "allow": 3},
        },
    )


def _write_strategy(path: Path, *, formula: str = "abs(ret_3) * 0.65", horizon: int = 3) -> None:
    path.write_text(
        f'''
class MeanReversionV2:
    def evaluate(self, feature):
        trend = float(feature.ret_3)
        expected_move = {formula}
        return StrategySignal(metadata={{
            "signal_horizon_ticks": {horizon},
            "expected_move_formula": "{formula}",
        }})
''',
        encoding="utf-8",
    )


def test_patch_required_when_h10_operating_point_is_blocked_by_ret3_strategy_formula(tmp_path: Path) -> None:
    operating_path = tmp_path / "operating.json"
    blocker_path = tmp_path / "blockers.json"
    strategy_path = tmp_path / "strategy_stack.py"
    _write_operating_point(operating_path)
    _write_blocker(blocker_path)
    _write_strategy(strategy_path)

    report = audit_promotion_feasibility(operating_path, blocker_path, strategy_path)

    assert report["classification"] == CLASS_PATCH_REQUIRED
    assert report["selected_operating_point"]["candidate_key"] == "BTCUSDTM:MEANREVERSION:sell:h10"
    assert report["strategy_source"]["meanreversion_formula"] == "abs(ret_3) * 0.65"
    assert report["decision"]["patch_strategy"] is True
    assert report["profitability_claim"] is False


def test_no_operating_point_blocks_promotion_patch(tmp_path: Path) -> None:
    operating_path = tmp_path / "operating.json"
    blocker_path = tmp_path / "blockers.json"
    strategy_path = tmp_path / "strategy_stack.py"
    _write_operating_point(operating_path, classification="PROFITABILITY_OPERATING_POINT_NOT_FOUND_SIGNALS_TOO_WEAK")
    _write_blocker(blocker_path)
    _write_strategy(strategy_path)

    report = audit_promotion_feasibility(operating_path, blocker_path, strategy_path)

    assert report["classification"] == CLASS_NO_OPERATING_POINT
    assert report["decision"]["patch_strategy"] is False


def test_contamination_overrides_patch_recommendation(tmp_path: Path) -> None:
    operating_path = tmp_path / "operating.json"
    blocker_path = tmp_path / "blockers.json"
    strategy_path = tmp_path / "strategy_stack.py"
    _write_operating_point(operating_path)
    _write_blocker(blocker_path, contaminated_event_count=1)
    _write_strategy(strategy_path)

    report = audit_promotion_feasibility(operating_path, blocker_path, strategy_path)

    assert report["classification"] == CLASS_CONTAMINATED
    assert report["decision"]["patch_strategy"] is False


def test_existing_position_open_means_already_runtime_reachable(tmp_path: Path) -> None:
    operating_path = tmp_path / "operating.json"
    blocker_path = tmp_path / "blockers.json"
    strategy_path = tmp_path / "strategy_stack.py"
    _write_operating_point(operating_path)
    _write_blocker(blocker_path, position_open_count=2)
    _write_strategy(strategy_path)

    report = audit_promotion_feasibility(operating_path, blocker_path, strategy_path)

    assert report["classification"] == CLASS_ALREADY_REACHABLE
    assert report["decision"]["patch_strategy"] is False
