from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
TMP_DIR = WORKDIR / "tmp"
RESULTS_DIR = WORKDIR / "results"
CONTROLLED_KPI_SCRIPT = WORKDIR / "scripts" / "controlled_kpi_run.py"

DEFAULT_SYMBOLS = "ETHUSDTM,BTCUSDTM,SOLUSDTM,XRPUSDTM,ADAUSDTM,BNBUSDTM"
DEFAULT_EXCLUDE_STRATEGIES = "auto_test,ExchangeSync"
DEFAULT_AFTER_ENV_OVERRIDES = [
    "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=0",
    "PAPER_AUTO_OPEN_STARTUP_ENABLE=1",
    "PAPER_AUTO_OPEN_FALLBACK_ENABLE=1",
    "PAPER_AUTO_OPEN_REPEAT=1",
    "EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC=10",
    "ENTRY_SYMBOL_BLOCKLIST=",
    "ENTRY_SYMBOL_STRATEGY_BLOCKLIST=",
    "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST=",
    "ENTRY_STRATEGY_SIDE_BLOCKLIST=",
    "DISABLE_STRATEGIES=",
    "ALPHA_WHITELIST_ENABLE=0",
    "ALPHA_WHITELIST_COLDSTART_ALLOW=0",
    "ALPHA_WHITELIST_FALLBACK_ENABLE=0",
]

if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))

from scripts.build_alpha_history_db import _normalize_close_row, _pair_side_stats  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _workspace_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKDIR.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _parse_csv_set(value: str) -> set[str]:
    out: set[str] = set()
    for token in str(value or "").split(","):
        item = str(token or "").strip().lower()
        if item:
            out.add(item)
    return out


def _resolve_repo_path(path_text: str | Path) -> Path:
    raw = str(path_text or "").strip()
    if not raw:
        return (WORKDIR / "__missing_path__").resolve()
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (WORKDIR / path).resolve()


def _canonical_side_token(symbol: str, strategy: str, side: str) -> str:
    return f"{symbol.upper()}:{strategy.upper()}:{side.lower()}"


def _normalize_after_env_overrides(raw_items: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        txt = str(item or "").strip()
        if not txt or "=" not in txt:
            continue
        key, value = txt.split("=", 1)
        key = str(key).strip()
        if not key:
            continue
        key_upper = key.upper()
        normalized_item = f"{key_upper}={value}"
        if key_upper in seen:
            # Last value wins; replace in-place.
            normalized = [
                x for x in normalized if not x.startswith(f"{key_upper}=")
            ]
        normalized.append(normalized_item)
        seen.add(key_upper)
    return normalized


def _parse_report_json_path(stdout: str) -> Path | None:
    matches = re.findall(r"^REPORT_JSON=(.+)$", stdout or "", flags=re.MULTILINE)
    if not matches:
        return None
    return _resolve_repo_path(matches[-1].strip())


def _latest_controlled_report(after_start_utc: datetime) -> Path | None:
    candidates: list[Path] = []
    for path in RESULTS_DIR.glob("controlled_kpi_*.json"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except Exception:
            continue
        if mtime >= after_start_utc:
            candidates.append(path.resolve())
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _paper_env() -> dict[str, str]:
    env = dict(os.environ)
    env["LIVE"] = "0"
    env["BOT_MODE"] = "paper"
    env["PAPER_RUN_ONCE"] = "1"
    env["USE_MOCK"] = "0"
    env["ZOL0_ALLOW_MOCK"] = "0"
    return env


def _run_single_after(args: argparse.Namespace, run_index: int) -> dict[str, Any]:
    if not CONTROLLED_KPI_SCRIPT.exists():
        raise FileNotFoundError(f"Missing script: {CONTROLLED_KPI_SCRIPT}")
    started_at = datetime.now(timezone.utc)
    cmd = [
        sys.executable,
        str(CONTROLLED_KPI_SCRIPT.resolve()),
        "--variant-only",
        "after",
        "--after-min",
        str(int(args.after_min)),
        "--symbols",
        str(args.symbols),
        "--market-type",
        "futures",
        "--paper-auto-open",
        "--paper-auto-close-sec",
        str(int(args.paper_auto_close_sec)),
        "--equity-snapshot-sec",
        str(int(args.equity_snapshot_sec)),
        "--quality-profile",
        "--alpha-bootstrap-build-min-pair-trades",
        str(int(args.alpha_bootstrap_build_min_pair_trades)),
        "--alpha-bootstrap-build-min-pair-winrate",
        str(float(args.alpha_bootstrap_build_min_pair_winrate)),
        "--alpha-bootstrap-build-min-pair-expectancy",
        str(float(args.alpha_bootstrap_build_min_pair_expectancy)),
        "--alpha-bootstrap-build-fallback-positive-side-pairs",
        str(int(args.alpha_bootstrap_build_fallback_positive_side_pairs)),
        "--alpha-bootstrap-build-min-side-trades",
        str(int(args.alpha_bootstrap_build_min_side_trades)),
        "--alpha-bootstrap-build-min-side-winrate",
        str(float(args.alpha_bootstrap_build_min_side_winrate)),
        "--alpha-bootstrap-build-min-side-expectancy",
        str(float(args.alpha_bootstrap_build_min_side_expectancy)),
    ]
    if bool(args.alpha_bootstrap_auto_refresh):
        cmd.append("--alpha-bootstrap-auto-refresh")
    else:
        cmd.append("--no-alpha-bootstrap-auto-refresh")

    after_env_items = _normalize_after_env_overrides(
        DEFAULT_AFTER_ENV_OVERRIDES + list(args.after_env or [])
    )
    for env_item in after_env_items:
        cmd.extend(["--after-env", env_item])

    proc = subprocess.run(
        cmd,
        cwd=str(WORKDIR),
        env=_paper_env(),
        text=True,
        capture_output=True,
    )
    report_path = _parse_report_json_path(proc.stdout or "")
    if report_path is None:
        report_path = _latest_controlled_report(started_at)

    result = {
        "run_index": int(run_index),
        "command": cmd,
        "returncode": int(proc.returncode),
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-80:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-40:]),
        "report_json_path": _workspace_rel(report_path) if report_path else None,
        "db_path": None,
        "trade_count": 0,
        "net_pnl": 0.0,
        "winrate": 0.0,
        "shutdown_classification": "",
    }
    if report_path is None or not report_path.exists():
        result["reason"] = "REPORT_JSON_NOT_FOUND"
        return result

    payload = _load_json(report_path)
    after = payload.get("after") or {}
    db_path = _resolve_repo_path(str(after.get("db_path") or ""))
    result.update(
        {
            "db_path": _workspace_rel(db_path) if db_path.exists() else str(db_path),
            "trade_count": _safe_int(after.get("trade_count")),
            "net_pnl": _safe_float(after.get("net_pnl")),
            "winrate": _safe_float(after.get("winrate")),
            "shutdown_classification": str(after.get("shutdown_classification") or ""),
        }
    )
    return result


def _collect_pair_side_stats_from_dbs(
    db_paths: list[Path],
    *,
    exclude_strategies: set[str],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    dedupe_keys: set[tuple[Any, ...]] = set()
    source_stats: list[dict[str, Any]] = []
    for db_path in db_paths:
        conn = None
        source_item = {
            "db_path": _workspace_rel(db_path),
            "position_close_rows": 0,
            "normalized_rows": 0,
            "error": "",
        }
        if not db_path.exists():
            source_item["error"] = "db_missing"
            source_stats.append(source_item)
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(
                "SELECT timestamp, details FROM logs WHERE event='position_close'"
            )
            rows = list(cur.fetchall())
            source_item["position_close_rows"] = len(rows)
            normalized_rows_before = len(normalized_rows)
            for ts_raw, details_raw in rows:
                normalized = _normalize_close_row(
                    ts_raw,
                    details_raw,
                    exclude_strategies=exclude_strategies,
                )
                if normalized is None:
                    continue
                ts, details, key = normalized
                if key in dedupe_keys:
                    continue
                dedupe_keys.add(key)
                normalized_rows.append(
                    {
                        "timestamp": ts,
                        "details": details,
                        "pnl": float(details.get("realized_pnl") or 0.0),
                        "gross_pnl": float(details.get("gross_pnl") or 0.0),
                        "fee_total": float(details.get("fee_total") or 0.0),
                        "funding_total": float(details.get("funding_total") or 0.0),
                    }
                )
            source_item["normalized_rows"] = len(normalized_rows) - normalized_rows_before
        except Exception as exc:
            source_item["error"] = f"{exc.__class__.__name__}:{exc}"
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
        source_stats.append(source_item)
    stats = _pair_side_stats(normalized_rows)
    meta = {
        "sources_scanned": len(db_paths),
        "dedup_rows": len(normalized_rows),
        "source_stats": source_stats,
    }
    return stats, meta


def _derive_positive_side_rows(
    pair_side_stats: dict[tuple[str, str, str], dict[str, Any]],
    *,
    min_side_trades: int,
    min_side_winrate: float,
    min_side_expectancy: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    allowlist: list[str] = []
    for (symbol, strategy, side), item in pair_side_stats.items():
        trade_count = _safe_int(item.get("trade_count"))
        winrate = _safe_float(item.get("winrate"))
        expectancy = _safe_float(item.get("expectancy"))
        token = _canonical_side_token(symbol, strategy, side)
        row = {
            "token": token,
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
            "trade_count": trade_count,
            "winrate": winrate,
            "expectancy": expectancy,
            "net_pnl": _safe_float(item.get("net_pnl")),
            "gross_pnl": _safe_float(item.get("gross_pnl")),
            "fee_total": _safe_float(item.get("fee_total")),
        }
        rows.append(row)
        if (
            trade_count >= int(min_side_trades)
            and winrate >= float(min_side_winrate)
            and expectancy > float(min_side_expectancy)
        ):
            allowlist.append(token)
    rows.sort(
        key=lambda x: (
            float(x.get("expectancy") or 0.0),
            float(x.get("winrate") or 0.0),
            int(x.get("trade_count") or 0),
            str(x.get("token") or ""),
        ),
        reverse=True,
    )
    allowlist = sorted(set(allowlist))
    return rows, allowlist


def _target_reached(
    rows: list[dict[str, Any]],
    *,
    min_positive_buckets: int,
    min_positive_trades_total: int,
) -> bool:
    if len(rows) < int(min_positive_buckets):
        return False
    total_trades = sum(_safe_int(row.get("trade_count")) for row in rows)
    return total_trades >= int(min_positive_trades_total)


def _write_positive_corpus_db(
    *,
    output_db_path: Path,
    source_db_paths: list[Path],
    allowlist_tokens: set[str],
    exclude_strategies: set[str],
) -> dict[str, Any]:
    if output_db_path.exists():
        output_db_path.unlink()
    output_db_path.parent.mkdir(parents=True, exist_ok=True)

    conn_out = sqlite3.connect(str(output_db_path))
    cur_out = conn_out.cursor()
    cur_out.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event TEXT NOT NULL,
            details TEXT
        )
        """
    )
    cur_out.execute("CREATE INDEX IF NOT EXISTS ix_logs_event ON logs(event)")

    dedupe_keys: set[tuple[Any, ...]] = set()
    inserted = 0
    inserted_by_token: dict[str, int] = {}
    source_stats: list[dict[str, Any]] = []
    for db_path in source_db_paths:
        source_item = {
            "db_path": _workspace_rel(db_path),
            "position_close_rows": 0,
            "rows_inserted": 0,
            "error": "",
        }
        if not db_path.exists():
            source_item["error"] = "db_missing"
            source_stats.append(source_item)
            continue
        conn_in = None
        try:
            conn_in = sqlite3.connect(str(db_path))
            cur_in = conn_in.cursor()
            cur_in.execute(
                "SELECT timestamp, details FROM logs WHERE event='position_close'"
            )
            rows = list(cur_in.fetchall())
            source_item["position_close_rows"] = len(rows)
            for ts_raw, details_raw in rows:
                normalized = _normalize_close_row(
                    ts_raw,
                    details_raw,
                    exclude_strategies=exclude_strategies,
                )
                if normalized is None:
                    continue
                ts, details, key = normalized
                token = _canonical_side_token(
                    str(details.get("symbol") or ""),
                    str(details.get("strategy") or ""),
                    str((details.get("position") or {}).get("side") or ""),
                )
                if token not in allowlist_tokens:
                    continue
                if key in dedupe_keys:
                    continue
                dedupe_keys.add(key)
                cur_out.execute(
                    "INSERT INTO logs(timestamp, event, details) VALUES(?, 'position_close', ?)",
                    (str(ts), json.dumps(details, ensure_ascii=True)),
                )
                inserted += 1
                source_item["rows_inserted"] += 1
                inserted_by_token[token] = inserted_by_token.get(token, 0) + 1
        except Exception as exc:
            source_item["error"] = f"{exc.__class__.__name__}:{exc}"
        finally:
            if conn_in is not None:
                try:
                    conn_in.close()
                except Exception:
                    pass
        source_stats.append(source_item)

    conn_out.commit()
    conn_out.close()
    return {
        "db_path": _workspace_rel(output_db_path),
        "rows_inserted": inserted,
        "tokens_inserted": sorted(inserted_by_token.items()),
        "source_stats": source_stats,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate fresh PAPER-only corpus with positive side buckets from "
            "new controlled KPI runs."
        )
    )
    parser.add_argument("--max-runs", type=int, default=6)
    parser.add_argument("--after-min", type=int, default=12)
    parser.add_argument("--symbols", type=str, default=DEFAULT_SYMBOLS)
    parser.add_argument("--paper-auto-close-sec", type=int, default=45)
    parser.add_argument("--equity-snapshot-sec", type=int, default=10)
    parser.add_argument(
        "--alpha-bootstrap-auto-refresh",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--alpha-bootstrap-build-min-pair-trades", type=int, default=10)
    parser.add_argument(
        "--alpha-bootstrap-build-min-pair-winrate", type=float, default=0.40
    )
    parser.add_argument(
        "--alpha-bootstrap-build-min-pair-expectancy", type=float, default=0.0
    )
    parser.add_argument(
        "--alpha-bootstrap-build-fallback-positive-side-pairs", type=int, default=2
    )
    parser.add_argument("--alpha-bootstrap-build-min-side-trades", type=int, default=2)
    parser.add_argument(
        "--alpha-bootstrap-build-min-side-winrate", type=float, default=0.45
    )
    parser.add_argument(
        "--alpha-bootstrap-build-min-side-expectancy", type=float, default=0.0
    )
    parser.add_argument("--min-side-trades", type=int, default=2)
    parser.add_argument("--min-side-winrate", type=float, default=0.45)
    parser.add_argument("--min-side-expectancy", type=float, default=0.0)
    parser.add_argument("--min-positive-buckets", type=int, default=2)
    parser.add_argument("--min-positive-trades-total", type=int, default=8)
    parser.add_argument(
        "--exclude-strategies",
        type=str,
        default=DEFAULT_EXCLUDE_STRATEGIES,
    )
    parser.add_argument(
        "--output-db",
        type=str,
        default="tmp/alpha_history_fresh_positive_corpus.db",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="tmp/alpha_history_fresh_positive_corpus_report.json",
    )
    parser.add_argument(
        "--strict-status-json",
        type=str,
        default="analysis/zol0_strict_bucket_gate_fresh_corpus_status_current.json",
    )
    parser.add_argument(
        "--after-env",
        action="append",
        default=[],
        help="Additional after-env overrides (KEY=VALUE). Repeatable.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    run_started_utc = _utc_now_iso()
    reason_codes: list[str] = []
    run_results: list[dict[str, Any]] = []
    source_db_paths: list[Path] = []
    exclude_strategies = _parse_csv_set(args.exclude_strategies)

    positive_rows: list[dict[str, Any]] = []
    positive_allowlist: list[str] = []
    side_rows_ranked: list[dict[str, Any]] = []
    side_stats_meta: dict[str, Any] = {}

    for run_index in range(1, int(args.max_runs) + 1):
        run_result = _run_single_after(args, run_index)
        run_results.append(run_result)
        if _safe_int(run_result.get("returncode"), default=1) != 0:
            reason_codes.append("CONTROLLED_KPI_RUN_FAILED")
            break

        db_path = _resolve_repo_path(str(run_result.get("db_path") or ""))
        if not db_path.exists():
            reason_codes.append("RUN_DB_PATH_MISSING")
            break
        source_db_paths.append(db_path)

        pair_side_stats, side_stats_meta = _collect_pair_side_stats_from_dbs(
            source_db_paths,
            exclude_strategies=exclude_strategies,
        )
        side_rows_ranked, positive_allowlist = _derive_positive_side_rows(
            pair_side_stats,
            min_side_trades=int(args.min_side_trades),
            min_side_winrate=float(args.min_side_winrate),
            min_side_expectancy=float(args.min_side_expectancy),
        )
        positive_rows = [
            row for row in side_rows_ranked if row.get("token") in positive_allowlist
        ]
        if _target_reached(
            positive_rows,
            min_positive_buckets=int(args.min_positive_buckets),
            min_positive_trades_total=int(args.min_positive_trades_total),
        ):
            break

    target_reached = _target_reached(
        positive_rows,
        min_positive_buckets=int(args.min_positive_buckets),
        min_positive_trades_total=int(args.min_positive_trades_total),
    )
    output_db_path = _resolve_repo_path(args.output_db)
    corpus_write = {
        "db_path": _workspace_rel(output_db_path),
        "rows_inserted": 0,
        "tokens_inserted": [],
        "source_stats": [],
    }
    status = "FAIL_CLOSED"
    if target_reached:
        corpus_write = _write_positive_corpus_db(
            output_db_path=output_db_path,
            source_db_paths=source_db_paths,
            allowlist_tokens=set(positive_allowlist),
            exclude_strategies=exclude_strategies,
        )
        if _safe_int(corpus_write.get("rows_inserted")) > 0:
            status = "PASS"
        else:
            reason_codes.append("POSITIVE_CORPUS_EMPTY")
    else:
        reason_codes.append("TARGET_NOT_REACHED")

    report = {
        "report_type": "fresh_positive_corpus_generation",
        "status": status,
        "reason_codes": sorted(set(reason_codes)),
        "started_at_utc": run_started_utc,
        "completed_at_utc": _utc_now_iso(),
        "params": {
            "max_runs": int(args.max_runs),
            "after_min": int(args.after_min),
            "symbols": [s.strip() for s in str(args.symbols).split(",") if s.strip()],
            "paper_auto_close_sec": int(args.paper_auto_close_sec),
            "equity_snapshot_sec": int(args.equity_snapshot_sec),
            "alpha_bootstrap_auto_refresh": bool(args.alpha_bootstrap_auto_refresh),
            "min_side_trades": int(args.min_side_trades),
            "min_side_winrate": float(args.min_side_winrate),
            "min_side_expectancy": float(args.min_side_expectancy),
            "min_positive_buckets": int(args.min_positive_buckets),
            "min_positive_trades_total": int(args.min_positive_trades_total),
            "exclude_strategies": sorted(exclude_strategies),
            "after_env_overrides": _normalize_after_env_overrides(
                DEFAULT_AFTER_ENV_OVERRIDES + list(args.after_env or [])
            ),
        },
        "run_results": run_results,
        "source_db_paths": [_workspace_rel(path) for path in source_db_paths],
        "target_reached": bool(target_reached),
        "positive_side_allowlist": positive_allowlist,
        "positive_side_rows": positive_rows,
        "side_rows_ranked_top": side_rows_ranked[:60],
        "side_stats_meta": side_stats_meta,
        "output_corpus": corpus_write,
    }

    output_json_path = _resolve_repo_path(args.output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    strict_status_path = _resolve_repo_path(args.strict_status_json)
    strict_status_path.parent.mkdir(parents=True, exist_ok=True)
    strict_status_payload = {
        "report_type": "zol0_strict_bucket_gate_fresh_corpus_status",
        "status": "PASS" if status == "PASS" else "UNCONFIRMED",
        "classification": (
            "STRICT_FRESH_CORPUS_SUFFICIENT"
            if status == "PASS"
            else "STRICT_FRESH_CORPUS_INSUFFICIENT"
        ),
        "reason_codes": sorted(set(reason_codes)),
        "strict_gate_inventory": {
            "accepted_run_count": sum(
                1 for item in run_results if _safe_int(item.get("returncode"), 1) == 0
            ),
            "positive_bucket_count": len(positive_rows),
            "positive_trades_total": sum(
                _safe_int(item.get("trade_count")) for item in positive_rows
            ),
        },
        "collection_standard": {
            "required_accepted_runs": int(args.max_runs),
        },
        "pass_fail_criteria": {
            "accepted_20_of_20_after_runs": bool(status == "PASS"),
        },
        "source_report_path": _workspace_rel(output_json_path),
        "generated_at_utc": _utc_now_iso(),
    }
    strict_status_path.write_text(
        json.dumps(strict_status_payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    print(f"FRESH_POSITIVE_CORPUS status={status}")
    print(f"FRESH_POSITIVE_CORPUS_REPORT_JSON={output_json_path}")
    print(f"FRESH_POSITIVE_CORPUS_STRICT_STATUS_JSON={strict_status_path}")
    print(
        "FRESH_POSITIVE_CORPUS_ALLOWLIST="
        + (",".join(positive_allowlist) if positive_allowlist else "-")
    )
    print(f"FRESH_POSITIVE_CORPUS_DB={output_db_path}")
    if status == "PASS":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
