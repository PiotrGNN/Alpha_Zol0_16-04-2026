from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON_PATH = ROOT / "analysis" / "maker_engine_smoke.json"
DEFAULT_MD_PATH = ROOT / "analysis" / "maker_engine_smoke.md"


@dataclass(frozen=True)
class MakerEngineConfig:
    enabled: bool = False
    post_only: bool = True
    maker_timeout_sec: float = 3.0
    fallback_to_market: bool = True


@dataclass(frozen=True)
class MakerIntent:
    symbol: str
    side: str
    quantity: float
    limit_price: float


class MakerEngine:
    def __init__(self, config: MakerEngineConfig | None = None) -> None:
        self.config = config or MakerEngineConfig()

    def execute(
        self,
        intent: MakerIntent,
        place_limit_order: Callable[[MakerIntent, bool], dict[str, Any]],
        cancel_order: Callable[[str], dict[str, Any]],
        place_market_order: Callable[[MakerIntent], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        metrics = {
            "maker_fill_probability": 0.0,
            "maker_fill_count": 0,
            "maker_timeout_count": 0,
            "maker_cancel_count": 0,
            "fallback_market_count": 0,
            "fallback_market_rate": 0.0,
            "maker_to_taker_transition_cost": 0.0,
        }
        if not self.config.enabled:
            return {
                "enabled": False,
                "path": "disabled_default",
                "post_only": bool(self.config.post_only),
                "runtime_decision_unchanged": True,
                "metrics": metrics,
            }

        order_result = place_limit_order(intent, self.config.post_only)
        order_id = str(order_result.get("order_id") or "")
        if bool(order_result.get("filled")):
            metrics["maker_fill_probability"] = 1.0
            metrics["maker_fill_count"] = 1
            return {
                "enabled": True,
                "path": "maker_fill",
                "post_only": bool(self.config.post_only),
                "timeout_sec": float(self.config.maker_timeout_sec),
                "metrics": metrics,
            }

        metrics["maker_timeout_count"] = 1
        if order_id:
            cancel_order(order_id)
            metrics["maker_cancel_count"] = 1

        if self.config.fallback_to_market and place_market_order is not None:
            market_result = place_market_order(intent)
            metrics["fallback_market_count"] = 1
            metrics["fallback_market_rate"] = 1.0
            metrics["maker_to_taker_transition_cost"] = float(
                market_result.get("estimated_extra_cost") or 0.0
            )
            return {
                "enabled": True,
                "path": "maker_timeout_then_market",
                "post_only": bool(self.config.post_only),
                "timeout_sec": float(self.config.maker_timeout_sec),
                "metrics": metrics,
            }

        return {
            "enabled": True,
            "path": "maker_timeout_no_fallback",
            "post_only": bool(self.config.post_only),
            "timeout_sec": float(self.config.maker_timeout_sec),
            "metrics": metrics,
        }


def write_maker_engine_smoke_artifacts(
    json_path: Path = DEFAULT_JSON_PATH,
    md_path: Path = DEFAULT_MD_PATH,
) -> dict[str, str]:
    disabled_engine = MakerEngine(MakerEngineConfig(enabled=False))
    disabled_result = disabled_engine.execute(
        intent=MakerIntent("ETHUSDTM", "buy", 0.01, 2000.0),
        place_limit_order=lambda intent, post_only: {"order_id": "dry-run"},
        cancel_order=lambda order_id: {"cancelled": True, "order_id": order_id},
        place_market_order=lambda intent: {"estimated_extra_cost": 0.0},
    )

    enabled_engine = MakerEngine(
        MakerEngineConfig(enabled=True, post_only=True, maker_timeout_sec=3.0)
    )
    enabled_result = enabled_engine.execute(
        intent=MakerIntent("ETHUSDTM", "buy", 0.01, 2000.0),
        place_limit_order=lambda intent, post_only: {
            "order_id": "maker-001",
            "filled": False,
        },
        cancel_order=lambda order_id: {"cancelled": True, "order_id": order_id},
        place_market_order=lambda intent: {"estimated_extra_cost": 0.75},
    )

    payload = {
        "runtime_behavior_neutral": True,
        "default_config": asdict(MakerEngineConfig()),
        "disabled_default_smoke": disabled_result,
        "mock_timeout_fallback_smoke": enabled_result,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_lines = [
        "MAKER_ENGINE_SMOKE",
        "",
        "DEFAULT_BEHAVIOR",
        f"enabled: {disabled_result.get('enabled')}",
        f"path: {disabled_result.get('path')}",
        "",
        "MOCK_TIMEOUT_FALLBACK",
        f"path: {enabled_result.get('path')}",
        (
            "maker_to_taker_transition_cost: "
            f"{enabled_result.get('metrics', {}).get('maker_to_taker_transition_cost')}"
        ),
        "",
        "RUNTIME_BEHAVIOR_NEUTRAL",
        "True",
        (
            "Maker engine remains disabled by default and does not alter "
            "runtime admission behavior."
        ),
        "",
    ]
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=str(DEFAULT_JSON_PATH))
    parser.add_argument("--md", default=str(DEFAULT_MD_PATH))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(
        json.dumps(
            write_maker_engine_smoke_artifacts(
                json_path=Path(args.json),
                md_path=Path(args.md),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
