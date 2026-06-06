from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class SchemaError(RuntimeError):
    """Raised when required schema/columns are missing."""


@dataclass(frozen=True)
class ColumnMap:
    symbol: str
    strategy: str
    side: str
    pnl: str
    mode: str | None
    live: str | None
    use_mock: str | None
    seed: str | None
    fallback: str | None
    force_open: str | None
    diagnostic: str | None


@dataclass
class RowEval:
    symbol: str
    strategy: str
    side: str
    pnl: float | None
    rejected_reasons: list[str]


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    txt = str(value).strip().lower()
    return txt in {"1", "true", "yes", "y", "on"}


def _resolve_paths(db_paths: Iterable[str], db_globs: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for raw in db_paths:
        p = Path(raw)
        if p.exists() and p.is_file():
            out.append(p)
        else:
            raise FileNotFoundError(f"db path not found: {raw}")
    for pattern in db_globs:
        hits = [p for p in Path().glob(pattern) if p.is_file()]
        if not hits:
            raise FileNotFoundError(f"db glob matched no files: {pattern}")
        out.extend(hits)
    unique = sorted({p.resolve() for p in out})
    if not unique:
        raise FileNotFoundError("no db inputs resolved")
    return unique


def _columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    return {str(r[1]).strip() for r in cur.execute(f"PRAGMA table_info({table})")}


def _pick(columns: set[str], names: list[str]) -> str | None:
    for n in names:
        if n in columns:
            return n
    return None


def _build_column_map(columns: set[str]) -> ColumnMap:
    symbol = _pick(columns, ["symbol"])
    strategy = _pick(columns, ["strategy", "strategy_name"])
    side = _pick(columns, ["side"])
    pnl = _pick(columns, ["net_pnl", "realized_pnl", "pnl"])
    if not all([symbol, strategy, side, pnl]):
        raise SchemaError(
            "closed_trades missing required columns: "
            "needs symbol,strategy/strategy_name,side,"
            "net_pnl/realized_pnl/pnl"
        )
    return ColumnMap(
        symbol=symbol,
        strategy=strategy,
        side=side,
        pnl=pnl,
        mode=_pick(columns, ["mode", "runtime_mode", "paper_runtime_mode"]),
        live=_pick(columns, ["live", "is_live", "live_mode"]),
        use_mock=_pick(columns, ["use_mock", "is_mock"]),
        seed=_pick(columns, ["is_seed", "seed_trade", "seed_enabled"]),
        fallback=_pick(
            columns,
            [
                "is_fallback",
                "fallback_open",
                "fallback_used",
                "paper_auto_open_fallback",
                "alpha_whitelist_fallback_used",
            ],
        ),
        force_open=_pick(
            columns,
            [
                "is_force_open",
                "force_open",
                "diagnostic_force_open",
                "paper_auto_open_forced",
            ],
        ),
        diagnostic=_pick(
            columns,
            ["is_diagnostic", "diagnostic_open", "diagnostic_run"],
        ),
    )


def _evaluate_row(row: sqlite3.Row, cm: ColumnMap) -> RowEval:
    symbol = str(row[cm.symbol]).strip().upper()
    strategy = str(row[cm.strategy]).strip()
    side = str(row[cm.side]).strip().lower()
    pnl = float(row[cm.pnl] or 0.0)

    reasons: list[str] = []
    if cm.mode is not None and str(row[cm.mode]).strip().lower() != "paper":
        reasons.append("non_paper_mode")
    if cm.live is not None and _coerce_bool(row[cm.live]):
        reasons.append("live_mode")
    if cm.use_mock is not None and _coerce_bool(row[cm.use_mock]):
        reasons.append("mock_data")
    if cm.seed is not None and _coerce_bool(row[cm.seed]):
        reasons.append("seed_trade")
    if cm.fallback is not None and _coerce_bool(row[cm.fallback]):
        reasons.append("fallback_open")
    if cm.force_open is not None and _coerce_bool(row[cm.force_open]):
        reasons.append("force_open")
    if cm.diagnostic is not None and _coerce_bool(row[cm.diagnostic]):
        reasons.append("diagnostic_open")

    return RowEval(
        symbol=symbol,
        strategy=strategy,
        side=side,
        pnl=pnl,
        rejected_reasons=reasons,
    )


_LOGS_SUMMARY_CLOSE_EVENTS = frozenset(
    {
        "post_close_summary_payload_built",
        "post_close_summary_emit_done",
    }
)

_LOGS_POSITION_CLOSE_EVENT = "position_close"

_PROVENANCE_REJECT_KEYS = {
    "seed_trade": ["is_seed", "seed_trade", "seed_open", "seed_enabled"],
    "fallback_open": [
        "is_fallback",
        "fallback_open",
        "fallback_used",
        "alpha_whitelist_fallback_used",
        "paper_auto_open_fallback",
    ],
    "force_open": [
        "is_force_open",
        "force_open",
        "diagnostic_force_open",
        "paper_auto_open_forced",
    ],
    "diagnostic_open": ["is_diagnostic", "diagnostic_open", "diagnostic_run"],
    "live_mode": ["live", "is_live"],
    "mock_data": ["use_mock", "is_mock"],
}


def _provenance_reasons_from_payload(payload: dict) -> list[str]:
    reasons: list[str] = []
    for reason, keys in _PROVENANCE_REJECT_KEYS.items():
        for k in keys:
            if k in payload and _coerce_bool(payload[k]):
                reasons.append(reason)
                break
    return reasons


def _profit_factor(pnls: list[float]) -> float | str:
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss_abs = abs(sum(p for p in pnls if p < 0))
    if gross_loss_abs == 0 and gross_profit > 0:
        return "Infinity"
    if gross_loss_abs > 0:
        return gross_profit / gross_loss_abs
    return 0.0


def _append_group(
    grouped: list[dict],
    symbol: str,
    strategy: str,
    side: str,
    pnls: list[float] | None,
    trade_count: int,
    economics_available: bool,
) -> None:
    if economics_available and pnls is not None:
        wins = sum(1 for p in pnls if p > 0)
        grouped.append(
            {
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "trade_count": trade_count,
                "economics_available": True,
                "winrate": (wins / trade_count) if trade_count else 0.0,
                "net_pnl": sum(pnls),
                "expectancy": (sum(pnls) / trade_count) if trade_count else 0.0,
                "profit_factor": _profit_factor(pnls),
            }
        )
        return
    grouped.append(
        {
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
            "trade_count": trade_count,
            "economics_available": False,
            "winrate": None,
            "net_pnl": None,
            "expectancy": None,
            "profit_factor": None,
        }
    )


def _collect_from_closed_trades(
    cur: sqlite3.Cursor,
    db: Path,
    schema_by_db: dict,
    groups: dict[tuple[str, str, str], list[float]],
    rejected_reason_counts: Counter,
) -> tuple[int, int, int]:
    cols = _columns(cur, "closed_trades")
    cm = _build_column_map(cols)
    schema_by_db[str(db)] = {
        "source_schema": "closed_trades",
        "table": "closed_trades",
        "columns": sorted(cols),
        "column_map": cm.__dict__,
        "economics_available": True,
    }
    rows = cur.execute("select * from closed_trades").fetchall()
    scanned = 0
    rejected = 0
    for row in rows:
        scanned += 1
        ev = _evaluate_row(row, cm)
        if ev.rejected_reasons:
            rejected += 1
            for r in ev.rejected_reasons:
                rejected_reason_counts[r] += 1
            continue
        groups[(ev.symbol, ev.strategy, ev.side)].append(ev.pnl)
    return scanned, rejected, 0


def _collect_from_position_close_logs(
    cur: sqlite3.Cursor,
    db: Path,
    schema_by_db: dict,
    groups_pnl: dict[tuple[str, str, str], list[float]],
    groups_count: Counter[tuple[str, str, str]],
    rejected_reason_counts: Counter,
) -> tuple[int, int, int]:
    rows = cur.execute(
        "select id, event, details from logs where event=? order by id",
        (_LOGS_POSITION_CLOSE_EVENT,),
    ).fetchall()
    if not rows:
        return 0, 0, 0

    schema_by_db[str(db)] = {
        "source_schema": "logs",
        "table": "logs",
        "supported_events": [_LOGS_POSITION_CLOSE_EVENT],
        "canonical_close_source": True,
        "economics_available": True,
        "dedup_key": "trade_id",
    }

    seen_trade_ids: set[str] = set()
    scanned = 0
    rejected = 0
    duplicates = 0
    economics_seen = False

    for _rid, _ev, details_raw in rows:
        scanned += 1
        try:
            payload = json.loads(details_raw) if isinstance(details_raw, str) else {}
        except (ValueError, TypeError):
            payload = {}

        trade_id = str(payload.get("trade_id") or "").strip()
        if not trade_id:
            rejected += 1
            rejected_reason_counts["missing_trade_id"] += 1
            continue
        if trade_id in seen_trade_ids:
            duplicates += 1
            rejected_reason_counts["duplicate_trade_id"] += 1
            continue

        symbol = str(payload.get("symbol") or "").strip().upper()
        strategy = str(
            payload.get("strategy") or payload.get("main_strategy") or ""
        ).strip()
        side = str(payload.get("side") or "").strip().lower()
        if not (symbol and strategy and side):
            rejected += 1
            rejected_reason_counts["missing_identity_fields"] += 1
            continue

        reasons = _provenance_reasons_from_payload(payload)
        if reasons:
            rejected += 1
            for r in reasons:
                rejected_reason_counts[r] += 1
            continue

        seen_trade_ids.add(trade_id)
        pnl_raw = payload.get("realized_net")
        if pnl_raw is None:
            pnl_raw = payload.get("realized_pnl")
        if pnl_raw is None:
            groups_count[(symbol, strategy, side)] += 1
            continue
        economics_seen = True
        groups_pnl[(symbol, strategy, side)].append(float(pnl_raw or 0.0))

    schema_by_db[str(db)]["economics_available"] = economics_seen
    return scanned, rejected, duplicates


def _collect_from_logs_summary(
    cur: sqlite3.Cursor,
    db: Path,
    schema_by_db: dict,
    groups_no_pnl: Counter[tuple[str, str, str]],
    rejected_reason_counts: Counter,
) -> tuple[int, int, int]:
    supported = sorted(_LOGS_SUMMARY_CLOSE_EVENTS)
    placeholders = ",".join("?" for _ in supported)
    rows = cur.execute(
        f"select id, event, details from logs where event in ({placeholders})",
        supported,
    ).fetchall()
    if not rows:
        raise SchemaError(
            f"{db}: NO_SUPPORTED_CLOSE_EVENTS — "
            f"logs table contains no supported close events "
            f"({_LOGS_POSITION_CLOSE_EVENT}, {', '.join(supported)})"
        )
    schema_by_db[str(db)] = {
        "source_schema": "logs_summary_noncanonical",
        "table": "logs",
        "supported_events": supported,
        "canonical_close_source": False,
        "economics_available": False,
    }
    scanned = 0
    rejected = 0
    for _rid, _ev, details_raw in rows:
        scanned += 1
        try:
            payload = json.loads(details_raw) if isinstance(details_raw, str) else {}
        except (ValueError, TypeError):
            payload = {}
        symbol = str(payload.get("symbol") or "").strip().upper()
        strategy = str(payload.get("strategy") or "").strip()
        side = str(payload.get("side") or "").strip().lower()
        if not (symbol and strategy and side):
            rejected += 1
            rejected_reason_counts["missing_identity_fields"] += 1
            continue
        reasons = _provenance_reasons_from_payload(payload)
        if reasons:
            rejected += 1
            for r in reasons:
                rejected_reason_counts[r] += 1
            continue
        groups_no_pnl[(symbol, strategy, side)] += 1
    return scanned, rejected, 0


def collect_natural_trades(db_files: list[Path]) -> dict:
    groups_pnl: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    groups_count: Counter[tuple[str, str, str]] = Counter()
    rejected_reason_counts: Counter[str] = Counter()
    rejected_rows = 0
    scanned_rows = 0
    duplicate_rows = 0
    schema_by_db: dict[str, dict] = {}

    for db in db_files:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        tables = {
            r[0]
            for r in cur.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        if "closed_trades" in tables:
            s, r, d = _collect_from_closed_trades(
                cur, db, schema_by_db, groups_pnl, rejected_reason_counts
            )
        elif "logs" in tables:
            s, r, d = _collect_from_position_close_logs(
                cur,
                db,
                schema_by_db,
                groups_pnl,
                groups_count,
                rejected_reason_counts,
            )
            if s == 0:
                s, r, d = _collect_from_logs_summary(
                    cur, db, schema_by_db, groups_count, rejected_reason_counts
                )
        else:
            con.close()
            raise SchemaError(
                f"{db}: unsupported schema — needs 'closed_trades' or 'logs' table"
            )
        con.close()
        scanned_rows += s
        rejected_rows += r
        duplicate_rows += d

    economics_available = bool(groups_pnl) or not bool(groups_count)
    canonical_close_source = all(
        bool((meta or {}).get("canonical_close_source", True))
        for meta in schema_by_db.values()
    )

    grouped = []
    for (symbol, strategy, side), pnls in sorted(groups_pnl.items()):
        _append_group(grouped, symbol, strategy, side, pnls, len(pnls), True)
    for (symbol, strategy, side), trade_count in sorted(groups_count.items()):
        _append_group(grouped, symbol, strategy, side, None, trade_count, False)

    natural_rows = (
        sum(len(v) for v in groups_pnl.values()) + groups_count.total()
    )

    return {
        "status": "ok",
        "db_files": [str(p) for p in db_files],
        "schema_by_db": schema_by_db,
        "canonical_close_source": canonical_close_source,
        "economics_available": economics_available or bool(groups_pnl),
        "totals": {
            "scanned_closed_rows": scanned_rows,
            "natural_closed_rows": natural_rows,
            "duplicate_rows": duplicate_rows,
            "rejected_rows": rejected_rows,
            "rejected_reason_counts": dict(sorted(rejected_reason_counts.items())),
            "group_count": len(grouped),
        },
        "groups": grouped,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect natural KuCoin PAPER closed trades from sqlite DB files."
    )
    p.add_argument(
        "--db",
        action="append",
        default=[],
        help="Explicit sqlite DB path. Repeatable.",
    )
    p.add_argument(
        "--glob",
        action="append",
        default=[],
        help="Glob pattern for sqlite DB files. Repeatable.",
    )
    p.add_argument("--output-json", required=True, help="Output JSON report path.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        db_files = _resolve_paths(args.db, args.glob)
        report = collect_natural_trades(db_files)
    except (OSError, sqlite3.Error, SchemaError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"NATURAL_TRADE_REPORT_JSON={out}")
    print(f"NATURAL_TRADE_GROUP_COUNT={report['totals']['group_count']}")
    print(f"NATURAL_TRADE_ROW_COUNT={report['totals']['natural_closed_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
