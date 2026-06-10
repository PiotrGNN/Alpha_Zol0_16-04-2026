# ✅ Audited by Copilot AI — 2025-07-29
# Changes: Added PAPER-only profitability discovery ranking for natural KuCoin closed trades.

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


EDGE_FOUND = "EDGE_FOUND"
EDGE_NOT_FOUND = "EDGE_NOT_FOUND"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

DEFAULT_MIN_TRADES = 10
DEFAULT_MIN_PROFIT_FACTOR = 1.15
DEFAULT_MIN_EXPECTANCY = 0.0
DEFAULT_MAX_NEVER_GREEN_SHARE = 0.20
DEFAULT_MAX_PROTECTIVE_EXIT_SHARE = 0.60


@dataclass(frozen=True)
class Trade:
    symbol: str
    strategy: str
    side: str
    net_pnl: float
    paper: bool = True
    exchange: str = "KuCoin"
    natural: bool = True
    assisted: bool = False
    contaminated: bool = False
    unknown: bool = False
    exit_reason: str = ""
    mfe: float | None = None
    split: str = "is"


@dataclass
class ProfileSummary:
    symbol: str
    strategy: str
    side: str
    trade_count: int
    net_pnl: float
    expectancy: float
    profit_factor: float
    win_rate: float
    oos_profit_factor: float | None
    never_green_share: float
    protective_exit_share: float
    blockers: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.symbol}:{self.strategy}:{self.side}"

    @property
    def accepted(self) -> bool:
        return not self.blockers


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "paper", "natural"}:
        return True
    if text in {"0", "false", "no", "n", "live", "synthetic"}:
        return False
    return default


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def _first(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def trade_from_mapping(row: dict[str, Any]) -> Trade:
    symbol = str(_first(row, "symbol", "contract", "instrument", default="UNKNOWN")).strip()
    strategy = str(_first(row, "strategy", "strategy_name", "entry_strategy", default="UNKNOWN")).strip()
    side = str(_first(row, "side", "direction", "position_side", default="UNKNOWN")).strip().lower()
    net_pnl = _to_float(_first(row, "net_pnl", "net_pnl_usdt", "realized_pnl", "pnl", default=0.0))
    paper = _to_bool(_first(row, "paper", "paper_only", "is_paper", default=True), True)
    exchange = str(_first(row, "exchange", "venue", default="KuCoin")).strip()
    natural = _to_bool(_first(row, "natural", "is_natural", "natural_trade", default=True), True)
    assisted = _to_bool(_first(row, "assisted", "is_assisted", "forced", "force_open", default=False), False)
    contaminated = _to_bool(_first(row, "contaminated", "is_contaminated", default=False), False)
    unknown = _to_bool(_first(row, "unknown", "is_unknown", default=False), False)
    exit_reason = str(_first(row, "exit_reason", "close_reason", "reason", default="")).strip().lower()
    mfe_raw = _first(row, "mfe", "mfe_usdt", "max_favorable_excursion", default=None)
    mfe = None if mfe_raw in (None, "") else _to_float(mfe_raw, 0.0)
    split = str(_first(row, "split", "dataset", "fold", default="is")).strip().lower()
    return Trade(
        symbol=symbol,
        strategy=strategy,
        side=side,
        net_pnl=net_pnl,
        paper=paper,
        exchange=exchange,
        natural=natural,
        assisted=assisted,
        contaminated=contaminated,
        unknown=unknown,
        exit_reason=exit_reason,
        mfe=mfe,
        split=split,
    )


def load_trades(path: str | Path) -> list[Trade]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open(newline="", encoding="utf-8") as handle:
            return [trade_from_mapping(row) for row in csv.DictReader(handle)]
    if suffix == ".json":
        data = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            rows = data.get("natural_trades") or data.get("closed_trades") or data.get("trades") or []
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        return [trade_from_mapping(row) for row in rows if isinstance(row, dict)]
    raise ValueError(f"Unsupported trade export: {source}")


def _profit_factor(values: Iterable[float]) -> float:
    vals = list(values)
    gross_profit = sum(v for v in vals if v > 0)
    gross_loss = abs(sum(v for v in vals if v < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _summarize_profile(
    trades: list[Trade],
    *,
    min_trades: int,
    min_profit_factor: float,
    min_expectancy: float,
    max_never_green_share: float,
    max_protective_exit_share: float,
) -> ProfileSummary:
    first = trades[0]
    values = [t.net_pnl for t in trades]
    wins = [v for v in values if v > 0]
    oos_values = [t.net_pnl for t in trades if t.split in {"oos", "out_of_sample", "validation"}]
    never_green = [t for t in trades if t.mfe is not None and t.mfe <= 0]
    protective = [t for t in trades if t.exit_reason == "protective_exit"]
    trade_count = len(trades)
    net_pnl = sum(values)
    expectancy = net_pnl / trade_count if trade_count else 0.0
    pf = _profit_factor(values)
    oos_pf = _profit_factor(oos_values) if oos_values else None
    summary = ProfileSummary(
        symbol=first.symbol,
        strategy=first.strategy,
        side=first.side,
        trade_count=trade_count,
        net_pnl=net_pnl,
        expectancy=expectancy,
        profit_factor=pf,
        win_rate=len(wins) / trade_count if trade_count else 0.0,
        oos_profit_factor=oos_pf,
        never_green_share=len(never_green) / trade_count if trade_count else 0.0,
        protective_exit_share=len(protective) / trade_count if trade_count else 0.0,
    )
    if trade_count < min_trades:
        summary.blockers.append("INSUFFICIENT_PROFILE_TRADES")
    if expectancy <= min_expectancy:
        summary.blockers.append("EXPECTANCY_NOT_POSITIVE")
    if pf < min_profit_factor:
        summary.blockers.append("PROFIT_FACTOR_BELOW_MIN")
    if summary.never_green_share > max_never_green_share:
        summary.blockers.append("NEVER_GREEN_SHARE_TOO_HIGH")
    if summary.protective_exit_share > max_protective_exit_share:
        summary.blockers.append("PROTECTIVE_EXIT_SHARE_TOO_HIGH")
    return summary


def discover_profitability(
    trades: Iterable[Trade],
    *,
    min_trades: int = DEFAULT_MIN_TRADES,
    min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR,
    min_expectancy: float = DEFAULT_MIN_EXPECTANCY,
    max_never_green_share: float = DEFAULT_MAX_NEVER_GREEN_SHARE,
    max_protective_exit_share: float = DEFAULT_MAX_PROTECTIVE_EXIT_SHARE,
    top_n: int = 10,
) -> dict[str, Any]:
    rejected_input: list[dict[str, Any]] = []
    clean: list[Trade] = []
    for trade in trades:
        blockers = []
        if trade.exchange.strip().lower() != "kucoin":
            blockers.append("NON_KUCOIN_EXCHANGE")
        if not trade.paper:
            blockers.append("NON_PAPER_TRADE")
        if not trade.natural:
            blockers.append("NON_NATURAL_TRADE")
        if trade.assisted:
            blockers.append("ASSISTED_TRADE")
        if trade.contaminated:
            blockers.append("CONTAMINATED_TRADE")
        if trade.unknown:
            blockers.append("UNKNOWN_TRADE_STATUS")
        if blockers:
            rejected_input.append({"symbol": trade.symbol, "strategy": trade.strategy, "side": trade.side, "blockers": blockers})
        else:
            clean.append(trade)

    grouped: dict[tuple[str, str, str], list[Trade]] = {}
    for trade in clean:
        grouped.setdefault((trade.symbol, trade.strategy, trade.side), []).append(trade)

    profiles = [
        _summarize_profile(
            rows,
            min_trades=min_trades,
            min_profit_factor=min_profit_factor,
            min_expectancy=min_expectancy,
            max_never_green_share=max_never_green_share,
            max_protective_exit_share=max_protective_exit_share,
        )
        for rows in grouped.values()
    ]
    profiles.sort(key=lambda p: (p.accepted, p.expectancy, p.profit_factor, p.net_pnl), reverse=True)
    accepted = [p for p in profiles if p.accepted]
    verdict = EDGE_FOUND if accepted else (INSUFFICIENT_DATA if not profiles else EDGE_NOT_FOUND)
    return {
        "verdict": verdict,
        "top_profiles": [p.__dict__ | {"key": p.key, "accepted": p.accepted} for p in profiles[:top_n]],
        "strongest_candidate": (accepted[0].__dict__ | {"key": accepted[0].key, "accepted": True}) if accepted else None,
        "blockers_per_rejected_profile": {p.key: p.blockers for p in profiles if p.blockers},
        "rejected_input_trades": rejected_input,
        "accepted_count": len(accepted),
        "profile_count": len(profiles),
        "clean_trade_count": len(clean),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Rank KuCoin PAPER natural closed-trade profitability profiles.")
    parser.add_argument("trade_export", help="CSV or JSON export with natural closed trades")
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)
    result = discover_profitability(load_trades(args.trade_export), min_trades=args.min_trades, top_n=args.top_n)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
