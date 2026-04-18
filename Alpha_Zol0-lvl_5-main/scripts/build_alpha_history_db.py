import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]


def _parse_json_payload(raw):
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            obj2 = json.loads(obj)
            return obj2 if isinstance(obj2, dict) else {}
        except Exception:
            return {}
    return {}


def _to_float(value):
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _extract_cost_components(details, pos, pnl):
    decompose = {}
    if isinstance(details.get("pnl_decompose"), dict):
        decompose = details.get("pnl_decompose")
    elif isinstance(pos.get("pnl_decompose"), dict):
        decompose = pos.get("pnl_decompose")

    fee_total = _to_float(decompose.get("fee_total"))
    if fee_total is None:
        fee_total = _to_float(details.get("fee_total"))
    if fee_total is None:
        fee_total = _to_float(pos.get("fee_total"))
    if fee_total is None:
        fee_total = _to_float(details.get("fee_cost"))
    if fee_total is None:
        fee_total = _to_float(pos.get("fee_cost"))

    funding_total = _to_float(decompose.get("funding_total"))
    if funding_total is None:
        funding_total = _to_float(details.get("funding_cost"))
    if funding_total is None:
        funding_total = _to_float(pos.get("funding_cost"))

    gross_pnl = _to_float(decompose.get("gross_fill_pnl_model"))
    if gross_pnl is None:
        gross_pnl = _to_float(decompose.get("gross_pnl"))
    if gross_pnl is None:
        gross_pnl = _to_float(decompose.get("gross"))
    if gross_pnl is None and (fee_total is not None or funding_total is not None):
        gross_pnl = float(pnl) + float(fee_total or 0.0) + float(funding_total or 0.0)
    if gross_pnl is None:
        gross_pnl = float(pnl)

    return {
        "gross_pnl": float(gross_pnl),
        "fee_total": float(fee_total or 0.0),
        "funding_total": float(funding_total or 0.0),
    }


def _parse_csv_set(raw):
    out = set()
    for token in str(raw or "").split(","):
        val = str(token or "").strip().lower()
        if val:
            out.add(val)
    return out


def _normalize_close_row(ts_raw, details_raw, exclude_strategies=None):
    details = _parse_json_payload(details_raw)
    if not isinstance(details, dict):
        return None
    pos = details.get("position") if isinstance(details.get("position"), dict) else {}

    symbol = details.get("symbol") or pos.get("symbol")
    strategy = details.get("strategy") or pos.get("strategy") or "Universal"
    side = str(pos.get("side") or details.get("side") or "").strip().lower()
    if side in ("long",):
        side = "buy"
    elif side in ("short",):
        side = "sell"

    entry_price = _to_float(pos.get("entry_price"))
    close_price = _to_float(details.get("close_price"))
    if close_price is None:
        close_price = _to_float(pos.get("close_price"))
    amount = _to_float(pos.get("amount"))

    pnl = _to_float(details.get("realized_pnl"))
    if pnl is None:
        pnl = _to_float(pos.get("realized_pnl"))
    if (
        pnl is None
        and entry_price is not None
        and close_price is not None
        and amount is not None
        and amount > 0
        and side in ("buy", "sell")
    ):
        sign = 1.0 if side == "buy" else -1.0
        pnl = (close_price - entry_price) * amount * sign

    if pnl is None:
        return None
    if symbol is None:
        return None
    costs = _extract_cost_components(details, pos, pnl)

    symbol = str(symbol)
    strategy = str(strategy)
    strategy_key = strategy.strip().lower()
    if strategy_key and strategy_key in (exclude_strategies or set()):
        return None
    ts = str(ts_raw) if ts_raw is not None else ""
    if not ts:
        ts = datetime.now(timezone.utc).isoformat()
    entry_ts = pos.get("timestamp")
    close_ts = pos.get("close_timestamp") or details.get("close_timestamp")
    out_details = {
        "symbol": symbol,
        "strategy": strategy,
        "realized_pnl": float(pnl),
        "gross_pnl": costs["gross_pnl"],
        "fee_total": costs["fee_total"],
        "funding_total": costs["funding_total"],
        "position": {
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
            "entry_price": entry_price,
            "close_price": close_price,
            "amount": amount,
            "timestamp": entry_ts,
            "close_timestamp": close_ts,
            "realized_pnl": float(pnl),
            "gross_pnl": costs["gross_pnl"],
            "fee_total": costs["fee_total"],
            "funding_total": costs["funding_total"],
        },
    }
    key = (
        symbol,
        strategy,
        side,
        str(entry_ts or ""),
        str(close_ts or ""),
        round(float(pnl), 8),
        round(float(entry_price), 8) if entry_price is not None else None,
        round(float(close_price), 8) if close_price is not None else None,
        round(float(amount), 8) if amount is not None else None,
    )
    return ts, out_details, key


def _iter_sources(glob_patterns):
    sources = []
    seen = set()
    for pattern in glob_patterns:
        pattern = str(pattern or "").strip()
        if not pattern:
            continue
        for path in WORKDIR.glob(pattern):
            try:
                rp = str(path.resolve())
            except Exception:
                rp = str(path)
            if rp in seen:
                continue
            seen.add(rp)
            sources.append(path)
    sources.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return sources


def _init_out_db(out_path: Path):
    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(out_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event TEXT NOT NULL,
            details TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS ix_logs_event ON logs(event)")
    conn.commit()
    return conn


def _pair_from_details(details: dict):
    try:
        symbol = str(details.get("symbol") or "")
        strategy = str(details.get("strategy") or "")
    except Exception:
        return None
    if not symbol or not strategy:
        return None
    return symbol, strategy


def _pair_side_from_details(details: dict):
    pair = _pair_from_details(details)
    if pair is None:
        return None
    try:
        pos = details.get("position") if isinstance(
            details.get("position"), dict) else {}
    except Exception:
        pos = {}
    side = str(pos.get("side") or details.get("side") or "").strip().lower()
    if side in ("long",):
        side = "buy"
    elif side in ("short",):
        side = "sell"
    if side not in ("buy", "sell"):
        return None
    return pair[0], pair[1], side


def _pair_stats(rows):
    stats = {}
    for row in rows:
        details = row.get("details")
        pnl = row.get("pnl")
        if not isinstance(details, dict):
            continue
        pair = _pair_from_details(details)
        if pair is None:
            continue
        try:
            pnl = float(pnl)
        except Exception:
            continue
        gross_pnl = _to_float(row.get("gross_pnl"))
        if gross_pnl is None and isinstance(details, dict):
            gross_pnl = _to_float(details.get("gross_pnl"))
        if gross_pnl is None:
            gross_pnl = pnl
        fee_total = _to_float(row.get("fee_total"))
        if fee_total is None and isinstance(details, dict):
            fee_total = _to_float(details.get("fee_total"))
        if fee_total is None:
            fee_total = 0.0
        funding_total = _to_float(row.get("funding_total"))
        if funding_total is None and isinstance(details, dict):
            funding_total = _to_float(details.get("funding_total"))
        if funding_total is None:
            funding_total = 0.0
        bucket = stats.setdefault(
            pair,
            {
                "trade_count": 0,
                "wins": 0,
                "net_pnl": 0.0,
                "gross_pnl": 0.0,
                "fee_total": 0.0,
                "funding_total": 0.0,
                "gross_positive_net_negative_count": 0,
                "gross_nonpositive_count": 0,
            },
        )
        bucket["trade_count"] += 1
        bucket["net_pnl"] += pnl
        bucket["gross_pnl"] += float(gross_pnl)
        bucket["fee_total"] += float(fee_total)
        bucket["funding_total"] += float(funding_total)
        if float(gross_pnl) > 0.0 and pnl <= 0.0:
            bucket["gross_positive_net_negative_count"] += 1
        if float(gross_pnl) <= 0.0:
            bucket["gross_nonpositive_count"] += 1
        if pnl > 0:
            bucket["wins"] += 1
    out = {}
    for pair, val in stats.items():
        n = int(val.get("trade_count") or 0)
        net = float(val.get("net_pnl") or 0.0)
        wins = int(val.get("wins") or 0)
        wr = (wins / n) if n > 0 else 0.0
        exp = (net / n) if n > 0 else 0.0
        gross = float(val.get("gross_pnl") or 0.0)
        fee = float(val.get("fee_total") or 0.0)
        out[pair] = {
            "trade_count": n,
            "wins": wins,
            "winrate": wr,
            "net_pnl": net,
            "expectancy": exp,
            "gross_pnl": gross,
            "fee_total": fee,
            "funding_total": float(val.get("funding_total") or 0.0),
            "avg_fee_total": (fee / n) if n > 0 else 0.0,
            "fee_to_abs_gross_ratio": (fee / abs(gross)) if abs(gross) > 0 else None,
            "gross_positive_net_negative_count": int(
                val.get("gross_positive_net_negative_count") or 0
            ),
            "gross_nonpositive_count": int(val.get("gross_nonpositive_count") or 0),
        }
    return out


def _pair_side_stats(rows):
    stats = {}
    for row in rows:
        details = row.get("details")
        pnl = row.get("pnl")
        if not isinstance(details, dict):
            continue
        pair_side = _pair_side_from_details(details)
        if pair_side is None:
            continue
        try:
            pnl = float(pnl)
        except Exception:
            continue
        gross_pnl = _to_float(row.get("gross_pnl"))
        if gross_pnl is None and isinstance(details, dict):
            gross_pnl = _to_float(details.get("gross_pnl"))
        if gross_pnl is None:
            gross_pnl = pnl
        fee_total = _to_float(row.get("fee_total"))
        if fee_total is None and isinstance(details, dict):
            fee_total = _to_float(details.get("fee_total"))
        if fee_total is None:
            fee_total = 0.0
        funding_total = _to_float(row.get("funding_total"))
        if funding_total is None and isinstance(details, dict):
            funding_total = _to_float(details.get("funding_total"))
        if funding_total is None:
            funding_total = 0.0
        bucket = stats.setdefault(
            pair_side,
            {
                "trade_count": 0,
                "wins": 0,
                "net_pnl": 0.0,
                "gross_pnl": 0.0,
                "fee_total": 0.0,
                "funding_total": 0.0,
                "gross_positive_net_negative_count": 0,
                "gross_nonpositive_count": 0,
            },
        )
        bucket["trade_count"] += 1
        bucket["net_pnl"] += pnl
        bucket["gross_pnl"] += float(gross_pnl)
        bucket["fee_total"] += float(fee_total)
        bucket["funding_total"] += float(funding_total)
        if float(gross_pnl) > 0.0 and pnl <= 0.0:
            bucket["gross_positive_net_negative_count"] += 1
        if float(gross_pnl) <= 0.0:
            bucket["gross_nonpositive_count"] += 1
        if pnl > 0:
            bucket["wins"] += 1
    out = {}
    for pair_side, val in stats.items():
        n = int(val.get("trade_count") or 0)
        net = float(val.get("net_pnl") or 0.0)
        wins = int(val.get("wins") or 0)
        wr = (wins / n) if n > 0 else 0.0
        exp = (net / n) if n > 0 else 0.0
        gross = float(val.get("gross_pnl") or 0.0)
        fee = float(val.get("fee_total") or 0.0)
        out[pair_side] = {
            "trade_count": n,
            "wins": wins,
            "winrate": wr,
            "net_pnl": net,
            "expectancy": exp,
            "gross_pnl": gross,
            "fee_total": fee,
            "funding_total": float(val.get("funding_total") or 0.0),
            "avg_fee_total": (fee / n) if n > 0 else 0.0,
            "fee_to_abs_gross_ratio": (fee / abs(gross)) if abs(gross) > 0 else None,
            "gross_positive_net_negative_count": int(
                val.get("gross_positive_net_negative_count") or 0
            ),
            "gross_nonpositive_count": int(val.get("gross_nonpositive_count") or 0),
        }
    return out


def _choose_allowed_pairs(
    stats,
    *,
    min_pair_trades: int,
    min_pair_winrate: float,
    min_pair_expectancy: float,
    fallback_top_pairs: int,
):
    allowed = set()
    rejected_min_trades = 0
    rejected_min_winrate = 0
    rejected_min_expectancy = 0
    for pair, st in (stats or {}).items():
        n = int(st.get("trade_count") or 0)
        wr = float(st.get("winrate") or 0.0)
        exp = float(st.get("expectancy") or 0.0)
        if (
            n >= int(min_pair_trades)
            and wr >= float(min_pair_winrate)
            and exp >= float(min_pair_expectancy)
        ):
            allowed.add(pair)
        else:
            # Count which rules caused rejection (a pair may fail multiple)
            if n < int(min_pair_trades):
                rejected_min_trades += 1
            if wr < float(min_pair_winrate):
                rejected_min_winrate += 1
            if exp < float(min_pair_expectancy):
                rejected_min_expectancy += 1

    rejection_telemetry = {
        "rejected_min_trades": rejected_min_trades,
        "rejected_min_winrate": rejected_min_winrate,
        "rejected_min_expectancy": rejected_min_expectancy,
    }

    if allowed or int(fallback_top_pairs) <= 0:
        return allowed, False, rejection_telemetry

    ranked = []
    for pair, st in (stats or {}).items():
        n = int(st.get("trade_count") or 0)
        if n <= 0:
            continue
        ranked.append(
            (
                float(st.get("expectancy") or 0.0),
                float(st.get("winrate") or 0.0),
                n,
                pair,
            )
        )
    ranked.sort(reverse=True)
    for _, _, _, pair in ranked[: max(1, int(fallback_top_pairs))]:
        allowed.add(pair)
    return allowed, True, rejection_telemetry


def build_history_db(
    output_path: Path,
    glob_patterns,
    max_sources: int,
    max_per_source: int,
    max_total: int,
    min_abs_pnl: float,
    quality_filter: bool,
    min_pair_trades: int,
    min_pair_winrate: float,
    min_pair_expectancy: float,
    fallback_top_pairs: int,
    exclude_strategies=None,
):
    sources = _iter_sources(glob_patterns)
    target_used_sources = max(0, int(max_sources))
    # Recent DBs are often sparse; allow scanning deeper to find enough sources
    # with usable close trades, while keeping a hard cap on scan effort.
    max_scan_sources = (target_used_sources * 8) if target_used_sources > 0 else 0
    normalized_rows = []
    seen_keys = set()
    scanned_rows = 0
    scanned_sources = 0
    used_sources = 0
    source_stats = []

    for src in sources:
        if len(normalized_rows) >= max_total:
            break
        if target_used_sources > 0 and used_sources >= target_used_sources:
            break
        if max_scan_sources > 0 and scanned_sources >= max_scan_sources:
            break
        if src.resolve() == output_path.resolve():
            continue
        scanned_sources += 1
        src_inserted = 0
        src_valid = 0
        src_rows = 0
        conn_src = None
        try:
            src_uri = f"file:{src.resolve().as_posix()}?mode=ro"
            conn_src = sqlite3.connect(src_uri, uri=True, timeout=0.2)
            cur_src = conn_src.cursor()
            cur_src.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='logs' LIMIT 1"  # noqa: E501
            )
            if cur_src.fetchone() is None:
                continue
            cur_src.execute(
                "SELECT timestamp, details FROM logs WHERE event='position_close' ORDER BY id DESC LIMIT ?",  # noqa: E501
                (max(1, int(max_per_source)),),
            )
            rows = cur_src.fetchall()
            src_rows = len(rows)
            scanned_rows += src_rows
            for ts_raw, details_raw in rows:
                if len(normalized_rows) >= max_total:
                    break
                normalized = _normalize_close_row(
                    ts_raw,
                    details_raw,
                    exclude_strategies=exclude_strategies,
                )
                if normalized is None:
                    continue
                ts, out_details, key = normalized
                src_valid += 1
                pnl = float(out_details.get("realized_pnl") or 0.0)
                if abs(pnl) < float(min_abs_pnl):
                    continue
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                normalized_rows.append(
                    {
                        "timestamp": ts,
                        "details": out_details,
                        "pnl": pnl,
                        "gross_pnl": float(out_details.get("gross_pnl") or pnl),
                        "fee_total": float(out_details.get("fee_total") or 0.0),
                        "funding_total": float(
                            out_details.get("funding_total") or 0.0
                        ),
                        "source": src.name,
                    }
                )
                src_inserted += 1
            if src_inserted > 0:
                used_sources += 1
                source_stats.append((src.name, src_rows, src_valid, src_inserted))
        except Exception as exc:
            source_stats.append((src.name, 0, 0, 0, f"ERR: {exc}"))
        finally:
            try:
                if conn_src is not None:
                    conn_src.close()
            except Exception:
                pass

    pair_stats = _pair_stats(normalized_rows)
    pair_side_stats = _pair_side_stats(normalized_rows)
    allowed_pairs = set()
    fallback_used = False
    rejection_telemetry: dict = {}
    if quality_filter:
        allowed_pairs, fallback_used, rejection_telemetry = _choose_allowed_pairs(
            pair_stats,
            min_pair_trades=max(1, int(min_pair_trades)),
            min_pair_winrate=float(min_pair_winrate),
            min_pair_expectancy=float(min_pair_expectancy),
            fallback_top_pairs=max(0, int(fallback_top_pairs)),
        )
    else:
        allowed_pairs = set(pair_stats.keys())

    conn_out = _init_out_db(output_path)
    cur_out = conn_out.cursor()
    inserted = 0
    inserted_by_pair = {}
    try:
        for row in normalized_rows:
            details = row.get("details")
            pair = _pair_from_details(details) if isinstance(details, dict) else None
            if pair is None or pair not in allowed_pairs:
                continue
            cur_out.execute(
                "INSERT INTO logs(timestamp, event, details) VALUES(?, 'position_close', ?)", (str(  # noqa: E501
                    row.get("timestamp") or ""), json.dumps(
                    details, ensure_ascii=True), ), )
            inserted += 1
            inserted_by_pair[pair] = int(inserted_by_pair.get(pair, 0)) + 1
        conn_out.commit()
    finally:
        conn_out.close()

    pair_ranking = []
    for pair, st in pair_stats.items():
        pair_ranking.append(
            {
                "symbol": pair[0],
                "strategy": pair[1],
                "trade_count": int(st.get("trade_count") or 0),
                "winrate": float(st.get("winrate") or 0.0),
                "expectancy": float(st.get("expectancy") or 0.0),
                "net_pnl": float(st.get("net_pnl") or 0.0),
                "gross_pnl": float(st.get("gross_pnl") or 0.0),
                "fee_total": float(st.get("fee_total") or 0.0),
                "funding_total": float(st.get("funding_total") or 0.0),
                "avg_fee_total": float(st.get("avg_fee_total") or 0.0),
                "fee_to_abs_gross_ratio": st.get("fee_to_abs_gross_ratio"),
                "gross_positive_net_negative_count": int(
                    st.get("gross_positive_net_negative_count") or 0
                ),
                "gross_nonpositive_count": int(st.get("gross_nonpositive_count") or 0),
                "selected": bool(pair in allowed_pairs),
                "inserted_rows": int(inserted_by_pair.get(pair, 0)),
            }
        )
    pair_ranking.sort(
        key=lambda x: (x.get("expectancy"), x.get("winrate"), x.get("trade_count")),
        reverse=True,
    )
    pair_side_ranking = []
    for pair_side, st in pair_side_stats.items():
        pair_side_ranking.append(
            {
                "symbol": pair_side[0],
                "strategy": pair_side[1],
                "side": pair_side[2],
                "trade_count": int(st.get("trade_count") or 0),
                "winrate": float(st.get("winrate") or 0.0),
                "expectancy": float(st.get("expectancy") or 0.0),
                "net_pnl": float(st.get("net_pnl") or 0.0),
                "gross_pnl": float(st.get("gross_pnl") or 0.0),
                "fee_total": float(st.get("fee_total") or 0.0),
                "funding_total": float(st.get("funding_total") or 0.0),
                "avg_fee_total": float(st.get("avg_fee_total") or 0.0),
                "fee_to_abs_gross_ratio": st.get("fee_to_abs_gross_ratio"),
                "gross_positive_net_negative_count": int(
                    st.get("gross_positive_net_negative_count") or 0
                ),
                "gross_nonpositive_count": int(st.get("gross_nonpositive_count") or 0),
            }
        )
    pair_side_ranking.sort(
        key=lambda x: (x.get("expectancy"), x.get("winrate"), x.get("trade_count")),
        reverse=True,
    )

    return {
        "output": str(output_path),
        "sources_scanned": scanned_sources,
        "sources_used": used_sources,
        "max_sources": int(max_sources),
        "max_scan_sources": int(max_scan_sources),
        "rows_scanned": scanned_rows,
        "rows_inserted": inserted,
        "dedup_size": len(seen_keys),
        "quality_filter": bool(quality_filter),
        "min_pair_trades": int(min_pair_trades),
        "min_pair_winrate": float(min_pair_winrate),
        "min_pair_expectancy": float(min_pair_expectancy),
        "fallback_top_pairs": int(fallback_top_pairs),
        "exclude_strategies": sorted(list(exclude_strategies or set())),
        "fallback_used": bool(fallback_used),
        "pairs_total": len(pair_stats),
        "pairs_selected": len(allowed_pairs),
        "pairs_rejected_per_rule": rejection_telemetry,
        "source_stats_top": source_stats[:30],
        "pair_stats_top": pair_ranking[:30],
        "pair_side_stats_top": pair_side_ranking[:60],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=str,
        default="tmp/alpha_history.db",
        help="Output sqlite DB path (workspace-relative).",
    )
    parser.add_argument(
        "--glob",
        type=str,
        default="tmp/controlled_kpi_*.db",
        help="Comma-separated glob patterns for source DBs.",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
        default=40,
        help="Target number of source DB files with usable rows (0=all).",
    )
    parser.add_argument("--max-per-source", type=int, default=450)
    parser.add_argument("--max-total", type=int, default=6000)
    parser.add_argument("--min-abs-pnl", type=float, default=0.0)
    parser.add_argument(
        "--quality-filter",
        action="store_true",
        help="Filter history by symbol+strategy quality thresholds.",
    )
    parser.add_argument("--min-pair-trades", type=int, default=3)
    parser.add_argument("--min-pair-winrate", type=float, default=0.35)
    parser.add_argument("--min-pair-expectancy", type=float, default=-0.20)
    parser.add_argument(
        "--fallback-top-pairs",
        type=int,
        default=4,
        help="If no pair passes quality filter, keep top-N pairs by expectancy.",
    )
    parser.add_argument(
        "--report-json",
        type=str,
        default="",
        help="Optional path to write full build report JSON.",
    )
    parser.add_argument(
        "--exclude-strategies",
        type=str,
        default="auto_test,ExchangeSync",
        help="Comma-separated strategy names to exclude from history.",
    )
    args = parser.parse_args()

    output_path = (WORKDIR / args.output).resolve()
    patterns = [x.strip() for x in str(args.glob or "").split(",") if x.strip()]
    if not patterns:
        raise SystemExit("No source glob patterns provided")

    report = build_history_db(
        output_path=output_path,
        glob_patterns=patterns,
        max_sources=max(0, int(args.max_sources)),
        max_per_source=max(1, int(args.max_per_source)),
        max_total=max(1, int(args.max_total)),
        min_abs_pnl=max(0.0, float(args.min_abs_pnl)),
        quality_filter=bool(args.quality_filter),
        min_pair_trades=max(1, int(args.min_pair_trades)),
        min_pair_winrate=float(args.min_pair_winrate),
        min_pair_expectancy=float(args.min_pair_expectancy),
        fallback_top_pairs=max(0, int(args.fallback_top_pairs)),
        exclude_strategies=_parse_csv_set(args.exclude_strategies),
    )
    report_json_path = None
    if str(args.report_json or "").strip():
        report_json_path = (WORKDIR / str(args.report_json).strip()).resolve()
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        report_json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
    print("ALPHA_HISTORY_DB=" + str(output_path))
    print(
        "ALPHA_HISTORY_STATS "
        f"sources_scanned={report['sources_scanned']} "
        f"sources_used={report['sources_used']} "
        f"rows_scanned={report['rows_scanned']} "
        f"rows_inserted={report['rows_inserted']} "
        f"dedup={report['dedup_size']} "
        f"pairs_total={report['pairs_total']} "
        f"pairs_selected={report['pairs_selected']} "
        f"fallback_used={int(bool(report.get('fallback_used')))}"
    )
    for row in report.get("source_stats_top") or []:
        if len(row) == 4:
            name, src_rows, src_valid, src_inserted = row
            print(
                "ALPHA_HISTORY_SOURCE "
                f"name={name} rows={src_rows} valid={src_valid} inserted={src_inserted}"
            )
        else:
            name, _, _, _, err = row
            print(f"ALPHA_HISTORY_SOURCE name={name} {err}")
    for row in report.get("pair_stats_top") or []:
        print(
            "ALPHA_HISTORY_PAIR "
            f"symbol={row.get('symbol')} strategy={row.get('strategy')} "
            f"selected={int(bool(row.get('selected')))} "
            f"trades={row.get('trade_count')} "
            f"winrate={row.get('winrate'):.4f} "
            f"expectancy={row.get('expectancy'):.6f} "
            f"net={row.get('net_pnl'):.6f} "
            f"inserted={row.get('inserted_rows')}"
        )
    for row in report.get("pair_side_stats_top") or []:
        sym = row.get('symbol')
        strat = row.get('strategy')
        side = row.get('side')
        tc = row.get('trade_count')
        wr = row.get('winrate')
        exp = row.get('expectancy')
        net = row.get('net_pnl')
        print(
            f"ALPHA_HISTORY_PAIR_SIDE"
            f" symbol={sym} strategy={strat} side={side}"
            f" trades={tc} winrate={wr:.4f}"
            f" expectancy={exp:.6f} net={net:.6f}"
        )
    if report_json_path is not None:
        print("ALPHA_HISTORY_REPORT_JSON=" + str(report_json_path))


if __name__ == "__main__":
    main()
