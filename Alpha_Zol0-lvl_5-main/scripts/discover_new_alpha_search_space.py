from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"

if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))

from core.kucoin_futures_client import KucoinFuturesClient, is_futures_symbol
from core.runtime_v2.contracts import QuoteTick
from core.runtime_v2.decision_engine import DecisionEngineV2
from core.runtime_v2.feature_engine import FeatureEngine
from core.runtime_v2.risk_engine import ContractSpec, RiskEngineV2
from core.runtime_v2.strategy_stack import StrategyStack


DEFAULT_NEW_ALPHA_SYMBOLS = [
    "ETHUSDTM",
    "BNBUSDTM",
    "ADAUSDTM",
    "DOGEUSDTM",
    "LINKUSDTM",
    "TRXUSDTM",
    "DOTUSDTM",
    "AVAXUSDTM",
]

ALLOWED_CLASSIFICATIONS = {
    "NEW_ALPHA_CANDIDATE_FOUND_FOR_PAPER_VALIDATION",
    "NO_NEW_ALPHA_CANDIDATE_FOUND",
    "BLOCKED_BY_DATA_QUALITY",
    "BLOCKED_BY_INSUFFICIENT_OBSERVATIONS",
    "BLOCKED_BY_SCOPE_RISK",
}


class _StaticSpecResolver:
    def get(self, symbol: str) -> ContractSpec:
        return ContractSpec(
            symbol=str(symbol or "").strip().upper(),
            multiplier=1.0,
            lot_size=1.0,
            min_size=1.0,
            max_size=None,
        )


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out


def _parse_symbols(raw: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for token in str(raw or "").split(","):
        symbol = str(token or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _tick_from_candle(
    *,
    symbol: str,
    candle: dict[str, Any],
    spread_bps: float,
) -> QuoteTick | None:
    close = _safe_float(candle.get("close"))
    timestamp = _safe_float(candle.get("timestamp"))
    if close is None or close <= 0.0 or timestamp is None:
        return None
    half_spread_ratio = max(0.0, float(spread_bps)) / 20_000.0
    bid = close * (1.0 - half_spread_ratio)
    ask = close * (1.0 + half_spread_ratio)
    return QuoteTick(
        symbol=str(symbol or "").strip().upper(),
        ts_ms=int(timestamp),
        bid=float(bid),
        ask=float(ask),
        mid=float(close),
        spread_abs=float(ask - bid),
        spread_bps=float(spread_bps),
        best_bid_size=None,
        best_ask_size=None,
        raw={"source": "kucoin_public_kline", "candle": candle},
    )


def _candidate_key(row: dict[str, Any]) -> str:
    return "{symbol}:{strategy}:{side}".format(
        symbol=row.get("symbol"),
        strategy=row.get("strategy"),
        side=row.get("side"),
    )


def classify_research_universe(
    *,
    histories: dict[str, list[dict[str, Any]]],
    min_expected_net_usdt: float = 0.08,
    free_equity_usdt: float = 1000.0,
    spread_bps: float = 1.0,
    use_static_contract_specs: bool = True,
) -> dict[str, Any]:
    invalid_symbols = [
        symbol for symbol in histories if not is_futures_symbol(str(symbol).upper())
    ]
    if invalid_symbols:
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "classification": "BLOCKED_BY_SCOPE_RISK",
            "reason": "non_kucoin_futures_symbol_in_scope",
            "invalid_symbols": sorted(invalid_symbols),
            "selected_hypothesis": None,
            "candidate_rank": [],
        }

    strategy_stack = StrategyStack()
    decision_engine = DecisionEngineV2()
    risk_engine = RiskEngineV2()
    risk_engine.entry_min_net_usdt = float(min_expected_net_usdt)
    if use_static_contract_specs:
        risk_engine.spec_resolver = _StaticSpecResolver()

    malformed_candle_count = 0
    insufficient_symbols: list[str] = []
    evaluated_symbols: set[str] = set()
    rejected_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    for symbol, candles in sorted(histories.items()):
        symbol_key = str(symbol or "").strip().upper()
        ordered_candles = sorted(
            list(candles or []),
            key=lambda row: float(row.get("timestamp") or 0.0),
        )
        if len(ordered_candles) < 4:
            insufficient_symbols.append(symbol_key)
            continue
        feature_engine = FeatureEngine(history_size=max(4, len(ordered_candles) + 1))
        last_candidates = []
        last_reason = ""
        for candle in ordered_candles:
            tick = _tick_from_candle(
                symbol=symbol_key,
                candle=candle,
                spread_bps=spread_bps,
            )
            if tick is None:
                malformed_candle_count += 1
                continue
            feature = feature_engine.ingest(tick)
            signals = strategy_stack.evaluate(feature)
            candidates, selected, reason = decision_engine.evaluate(
                quote=tick,
                feature=feature,
                signals=signals,
            )
            last_candidates = candidates
            last_reason = reason
            if selected is None:
                continue
            plan = risk_engine.build_order_plan(
                candidate=selected,
                free_equity_usdt=free_equity_usdt,
                open_positions_count=0,
            )
            row = {
                "symbol": selected.symbol,
                "strategy": selected.strategy,
                "side": selected.side,
                "source": "fresh_kucoin_public_klines_research",
                "decision_reason": reason,
                "risk_reason": plan.reason_code,
                "accepted": bool(plan.accepted),
                "expected_net_after_full_cost": float(
                    plan.expected_net_after_full_cost
                ),
                "final_notional_usdt": float(plan.final_notional_usdt),
                "expected_net_after_cost": float(selected.expected_net_after_cost),
                "probability_of_profit": float(selected.probability_of_profit),
                "confidence": float(selected.confidence),
                "expected_move": float(selected.expected_move),
                "sample_count": int(feature.sample_count),
                "profile_span_sec": float(feature.profile_span_sec),
            }
            if (
                plan.accepted
                and row["expected_net_after_full_cost"] >= float(min_expected_net_usdt)
            ):
                candidate_rows.append(row)
            else:
                rejected_rows.append(row)
        if last_candidates or last_reason:
            evaluated_symbols.add(symbol_key)
            for candidate in last_candidates:
                rejected_rows.append(
                    {
                        "symbol": candidate.symbol,
                        "strategy": candidate.strategy,
                        "side": candidate.side,
                        "source": "fresh_kucoin_public_klines_research",
                        "decision_reason": last_reason,
                        "risk_reason": None,
                        "accepted": False,
                        "expected_net_after_full_cost": None,
                        "final_notional_usdt": None,
                        "expected_net_after_cost": float(
                            candidate.expected_net_after_cost
                        ),
                        "probability_of_profit": float(candidate.probability_of_profit),
                        "confidence": float(candidate.confidence),
                        "expected_move": float(candidate.expected_move),
                        "sample_count": None,
                        "profile_span_sec": None,
                    }
                )

    candidate_rows.sort(
        key=lambda row: (
            float(row["expected_net_after_full_cost"]),
            float(row["probability_of_profit"]),
            float(row["confidence"]),
        ),
        reverse=True,
    )
    selected_hypothesis = candidate_rows[0] if candidate_rows else None
    if selected_hypothesis is not None:
        classification = "NEW_ALPHA_CANDIDATE_FOUND_FOR_PAPER_VALIDATION"
    elif not histories or malformed_candle_count > 0 and not evaluated_symbols:
        classification = "BLOCKED_BY_DATA_QUALITY"
    elif not evaluated_symbols and insufficient_symbols:
        classification = "BLOCKED_BY_INSUFFICIENT_OBSERVATIONS"
    else:
        classification = "NO_NEW_ALPHA_CANDIDATE_FOUND"

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "scope": {
            "kucoin_only": True,
            "paper_only": True,
            "live": 0,
            "use_mock": 0,
            "source": "kucoin_public_futures_klines",
            "min_expected_net_usdt": float(min_expected_net_usdt),
            "free_equity_usdt": float(free_equity_usdt),
            "spread_bps": float(spread_bps),
            "use_static_contract_specs": bool(use_static_contract_specs),
        },
        "evaluated_symbol_count": len(evaluated_symbols),
        "insufficient_observation_symbols": sorted(insufficient_symbols),
        "malformed_candle_count": int(malformed_candle_count),
        "selected_hypothesis": selected_hypothesis,
        "candidate_rank": [
            {**row, "candidate_key": _candidate_key(row)}
            for row in candidate_rows[:25]
        ],
        "rejected_top": [
            {**row, "candidate_key": _candidate_key(row)}
            for row in sorted(
                rejected_rows,
                key=lambda item: (
                    float(item.get("expected_net_after_cost") or 0.0),
                    float(item.get("probability_of_profit") or 0.0),
                ),
                reverse=True,
            )[:25]
        ],
    }


def fetch_histories(
    *,
    symbols: list[str],
    interval: str,
    limit: int,
    client: KucoinFuturesClient | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    futures_client = client or KucoinFuturesClient()
    histories: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            histories[symbol] = futures_client.get_klines(
                symbol,
                interval,
                limit=limit,
            )
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
    return histories, errors


def render_markdown(report: dict[str, Any]) -> str:
    scope = report.get("scope") or {}
    lines = [
        "# New Alpha Search Space Research",
        "",
        f"- generated_at_utc: `{report.get('generated_at_utc')}`",
        f"- classification: `{report.get('classification')}`",
        f"- min_expected_net_usdt: `{scope.get('min_expected_net_usdt')}`",
        f"- evaluated_symbol_count: `{report.get('evaluated_symbol_count')}`",
        f"- malformed_candle_count: `{report.get('malformed_candle_count')}`",
        f"- selected_hypothesis: `{_candidate_key(report.get('selected_hypothesis') or {}) if report.get('selected_hypothesis') else None}`",
        "",
        "## Candidate Rank",
        "| rank | candidate | expected_net | notional | probability | confidence | decision | risk |",
        "|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for index, row in enumerate(report.get("candidate_rank") or [], start=1):
        lines.append(
            "| {rank} | {candidate} | {expected} | {notional} | {prob} | {conf} | {decision} | {risk} |".format(
                rank=index,
                candidate=row.get("candidate_key"),
                expected=row.get("expected_net_after_full_cost"),
                notional=row.get("final_notional_usdt"),
                prob=row.get("probability_of_profit"),
                conf=row.get("confidence"),
                decision=row.get("decision_reason"),
                risk=row.get("risk_reason"),
            )
        )
    lines.extend(
        [
            "",
            "## Rejected Top",
            "| rank | candidate | expected_ratio | probability | decision | risk |",
            "|---:|---|---:|---:|---|---|",
        ]
    )
    for index, row in enumerate(report.get("rejected_top") or [], start=1):
        lines.append(
            "| {rank} | {candidate} | {ratio} | {prob} | {decision} | {risk} |".format(
                rank=index,
                candidate=row.get("candidate_key"),
                ratio=row.get("expected_net_after_cost"),
                prob=row.get("probability_of_profit"),
                decision=row.get("decision_reason"),
                risk=row.get("risk_reason"),
            )
        )
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only fresh KuCoin futures alpha search-space discovery"
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_NEW_ALPHA_SYMBOLS),
        help="Comma-separated KuCoin futures symbols.",
    )
    parser.add_argument("--interval", default="1min")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--min-expected-net-usdt", type=float, default=0.08)
    parser.add_argument("--free-equity-usdt", type=float, default=1000.0)
    parser.add_argument("--spread-bps", type=float, default=1.0)
    parser.add_argument(
        "--use-static-contract-specs",
        type=int,
        default=0,
        help="Use static contract specs for deterministic offline-style research.",
    )
    parser.add_argument(
        "--output-json",
        default=str(ANALYSIS_DIR / "new_alpha_research_validation_current.json"),
    )
    parser.add_argument(
        "--output-md",
        default=str(ANALYSIS_DIR / "new_alpha_research_validation_current.md"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = _parse_symbols(args.symbols)
    if not symbols:
        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "classification": "BLOCKED_BY_SCOPE_RISK",
            "reason": "empty_symbol_scope",
            "selected_hypothesis": None,
            "candidate_rank": [],
        }
    else:
        histories, errors = fetch_histories(
            symbols=symbols,
            interval=args.interval,
            limit=max(1, int(args.limit)),
        )
        report = classify_research_universe(
            histories=histories,
            min_expected_net_usdt=float(args.min_expected_net_usdt),
            free_equity_usdt=float(args.free_equity_usdt),
            spread_bps=float(args.spread_bps),
            use_static_contract_specs=bool(args.use_static_contract_specs),
        )
        report["fetch_errors"] = errors
    if str(report.get("classification")) not in ALLOWED_CLASSIFICATIONS:
        raise RuntimeError(f"invalid classification: {report.get('classification')}")

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"classification": report["classification"], "output_json": str(output_json), "output_md": str(output_md)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
