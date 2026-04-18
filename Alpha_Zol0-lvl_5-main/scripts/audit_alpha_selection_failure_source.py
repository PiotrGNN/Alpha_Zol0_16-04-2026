from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_locked_positive_subset import (  # noqa: E402
    _manifest_artifact_path,
    _scorecard_manifest_text,
    build_audit as build_locked_subset_audit,
)
from build_alpha_history_db import _normalize_close_row, _parse_json_payload  # noqa: E402
from profitability_audit_scorecard import (  # noqa: E402
    _load_json,
    _resolve_repo_path,
    _safe_float,
    _safe_int,
    _workspace_rel,
)


WORKDIR = Path(__file__).resolve().parents[1]
DEFAULT_SCORECARD_PATH = WORKDIR / "analysis" / "zol0_profitability_audit_scorecard.json"
DEFAULT_OUTPUT_JSON = (
    WORKDIR / "analysis" / "alpha_selection_failure_source_audit_current.json"
)


def _round6(value: Any) -> float:
    return round(_safe_float(value), 6)


def _first_float(*values: Any) -> float | None:
    for value in values:
        try:
            if value is None or isinstance(value, bool):
                continue
            out = float(value)
        except Exception:
            continue
        if math.isfinite(out):
            return out
    return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _extract_cost_rows(
    manifest: dict[str, Any],
    *,
    exclude_strategies: set[str],
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for entry in manifest.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        run_id = str(entry.get("run_id") or "").strip()
        db_path = _manifest_artifact_path(entry, "db")
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, timestamp, details FROM logs "
                "WHERE event='position_close' ORDER BY id ASC"
            ).fetchall()
        finally:
            conn.close()

        for log_id, ts_raw, details_raw in rows:
            normalized = _normalize_close_row(
                ts_raw,
                details_raw,
                exclude_strategies=exclude_strategies,
            )
            if normalized is None:
                continue
            _ts, normalized_details, dedupe_key = normalized
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            details = _parse_json_payload(details_raw)
            position = details.get("position") if isinstance(details.get("position"), dict) else {}
            norm_pos = normalized_details.get("position") or {}
            decompose = (
                details.get("pnl_decompose")
                if isinstance(details.get("pnl_decompose"), dict)
                else position.get("pnl_decompose")
                if isinstance(position.get("pnl_decompose"), dict)
                else {}
            )
            net_pnl = _safe_float(normalized_details.get("realized_pnl"))
            fee_total = _first_float(
                decompose.get("fee_total"),
                details.get("fee_total"),
                position.get("fee_total"),
                details.get("fee_cost"),
                position.get("fee_cost"),
            )
            funding_total = _first_float(
                decompose.get("funding_total"),
                details.get("funding_cost"),
                position.get("funding_cost"),
            )
            gross_pnl = _first_float(
                decompose.get("gross_fill_pnl_model"),
                decompose.get("gross_pnl"),
                decompose.get("gross"),
                details.get("gross_fill_pnl_model"),
                position.get("gross_fill_pnl_model"),
            )
            gross_source = "pnl_decompose"
            if gross_pnl is None:
                gross_pnl = net_pnl + float(fee_total or 0.0) + float(funding_total or 0.0)
                gross_source = "net_plus_costs_fallback"
            pre_best = _first_float(
                details.get("pre_hard_close_best_feasible_net"),
                position.get("pre_hard_close_best_feasible_net"),
            )
            feasible = _bool_value(
                details.get("economic_exit_feasible")
                if details.get("economic_exit_feasible") is not None
                else position.get("economic_exit_feasible")
            )
            captured = _bool_value(
                details.get("economic_exit_captured")
                if details.get("economic_exit_captured") is not None
                else position.get("economic_exit_captured")
            )
            rows_out.append(
                {
                    "run_id": run_id,
                    "db_path": _workspace_rel(db_path),
                    "log_id": _safe_int(log_id),
                    "timestamp": str(ts_raw or ""),
                    "symbol": str(norm_pos.get("symbol") or normalized_details.get("symbol") or "").upper(),
                    "strategy": str(norm_pos.get("strategy") or normalized_details.get("strategy") or ""),
                    "side": str(norm_pos.get("side") or normalized_details.get("side") or "").lower(),
                    "net_pnl": net_pnl,
                    "gross_pnl": float(gross_pnl),
                    "gross_source": gross_source,
                    "fee_total": float(fee_total or 0.0),
                    "funding_total": float(funding_total or 0.0),
                    "signed_slippage_bps_close": _first_float(
                        details.get("signed_slippage_bps_close"),
                        position.get("signed_slippage_bps_close"),
                        position.get("signed_slippage_bps"),
                    ),
                    "mfe": _first_float(details.get("mfe"), position.get("mfe")),
                    "mae": _first_float(details.get("mae"), position.get("mae")),
                    "pre_hard_close_best_feasible_net": pre_best,
                    "economic_exit_feasible": feasible,
                    "economic_exit_captured": captured,
                    "missed_feasible_positive_exit": bool(
                        feasible and not captured and (pre_best or 0.0) > 0.0
                    ),
                    "gross_positive_net_negative": bool(gross_pnl > 0.0 and net_pnl <= 0.0),
                    "gross_nonpositive": bool(gross_pnl <= 0.0),
                    "net_positive": bool(net_pnl > 0.0),
                }
            )
    return rows_out


def _profit_factor(gross_profit: float, gross_loss_abs: float) -> float | str:
    if gross_loss_abs > 0:
        return _round6(gross_profit / gross_loss_abs)
    if gross_profit > 0:
        return "Infinity"
    return 0.0


def _empty_bucket(grouping: str, name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "grouping": grouping,
        "name": name,
        "symbol": row.get("symbol") if grouping != "global" else "",
        "strategy": row.get("strategy") if grouping in {"symbol_strategy", "symbol_strategy_side"} else "",
        "side": row.get("side") if grouping == "symbol_strategy_side" else "",
        "trade_count": 0,
        "net_pnl": 0.0,
        "gross_pnl": 0.0,
        "fee_total": 0.0,
        "funding_total": 0.0,
        "gross_positive_count": 0,
        "net_positive_count": 0,
        "gross_positive_net_negative_count": 0,
        "gross_nonpositive_count": 0,
        "missed_feasible_positive_exit_count": 0,
        "economic_exit_feasible_count": 0,
        "economic_exit_captured_count": 0,
        "slippage_bps_close_sum": 0.0,
        "slippage_bps_close_count": 0,
    }


def _classify_bucket(bucket: dict[str, Any], *, min_trades: int) -> str:
    trade_count = _safe_int(bucket.get("trade_count"))
    net_pnl = _safe_float(bucket.get("net_pnl"))
    gross_pnl = _safe_float(bucket.get("gross_pnl"))
    fee_total = _safe_float(bucket.get("fee_total"))
    if trade_count < int(min_trades):
        return "SAMPLE_LIMITED"
    if gross_pnl > 0.0 and net_pnl < 0.0 and fee_total >= gross_pnl:
        return "COST_BURDEN_PRIMARY"
    if gross_pnl <= 0.0 and net_pnl < 0.0:
        return "ALPHA_GROSS_TOXICITY_PRIMARY"
    if _safe_int(bucket.get("missed_feasible_positive_exit_count")) > 0 and net_pnl < 0.0:
        return "EXIT_CAPTURE_CONFOUNDER_NON_PRIMARY"
    if net_pnl >= 0.0 and gross_pnl > 0.0:
        return "CANDIDATE_POSITIVE"
    return "MIXED_UNRESOLVED"


def _finalize_bucket(bucket: dict[str, Any], *, min_trades: int) -> dict[str, Any]:
    trade_count = _safe_int(bucket.get("trade_count"))
    gross_profit = sum(0.0 for _ in [])
    gross_loss_abs = 0.0
    for pnl in bucket.pop("_net_pnls", []):
        if pnl > 0:
            gross_profit += pnl
        elif pnl < 0:
            gross_loss_abs += abs(pnl)
    avg_net = _safe_float(bucket["net_pnl"]) / trade_count if trade_count > 0 else 0.0
    avg_gross = _safe_float(bucket["gross_pnl"]) / trade_count if trade_count > 0 else 0.0
    avg_fee = _safe_float(bucket["fee_total"]) / trade_count if trade_count > 0 else 0.0
    avg_slippage = (
        _safe_float(bucket["slippage_bps_close_sum"]) / _safe_int(bucket["slippage_bps_close_count"])
        if _safe_int(bucket["slippage_bps_close_count"]) > 0
        else None
    )
    bucket.update(
        {
            "net_pnl": _round6(bucket["net_pnl"]),
            "gross_pnl": _round6(bucket["gross_pnl"]),
            "fee_total": _round6(bucket["fee_total"]),
            "funding_total": _round6(bucket["funding_total"]),
            "avg_net_pnl": _round6(avg_net),
            "avg_gross_pnl": _round6(avg_gross),
            "avg_fee_total": _round6(avg_fee),
            "net_profit_factor": _profit_factor(gross_profit, gross_loss_abs),
            "fee_to_abs_gross_ratio": _round6(
                _safe_float(bucket["fee_total"]) / abs(_safe_float(bucket["gross_pnl"]))
            )
            if abs(_safe_float(bucket["gross_pnl"])) > 0
            else None,
            "avg_signed_slippage_bps_close": _round6(avg_slippage)
            if avg_slippage is not None
            else None,
        }
    )
    bucket["failure_classification"] = _classify_bucket(bucket, min_trades=min_trades)
    return bucket


def _aggregate_cost_rows(
    rows: list[dict[str, Any]],
    *,
    grouping: str,
    min_trades: int,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        if grouping == "global":
            key = ("GLOBAL",)
            name = "GLOBAL"
        elif grouping == "symbol":
            key = (row["symbol"],)
            name = row["symbol"]
        elif grouping == "symbol_strategy":
            key = (row["symbol"], row["strategy"])
            name = f"{row['symbol']}|{row['strategy']}"
        elif grouping == "symbol_strategy_side":
            key = (row["symbol"], row["strategy"], row["side"])
            name = f"{row['symbol']}|{row['strategy']}|{row['side']}"
        else:
            raise ValueError(f"unsupported grouping: {grouping}")
        bucket = buckets.setdefault(key, _empty_bucket(grouping, name, row))
        bucket["trade_count"] += 1
        bucket["net_pnl"] += _safe_float(row.get("net_pnl"))
        bucket["gross_pnl"] += _safe_float(row.get("gross_pnl"))
        bucket["fee_total"] += _safe_float(row.get("fee_total"))
        bucket["funding_total"] += _safe_float(row.get("funding_total"))
        bucket["gross_positive_count"] += int(_safe_float(row.get("gross_pnl")) > 0.0)
        bucket["net_positive_count"] += int(_safe_float(row.get("net_pnl")) > 0.0)
        bucket["gross_positive_net_negative_count"] += int(
            bool(row.get("gross_positive_net_negative"))
        )
        bucket["gross_nonpositive_count"] += int(bool(row.get("gross_nonpositive")))
        bucket["missed_feasible_positive_exit_count"] += int(
            bool(row.get("missed_feasible_positive_exit"))
        )
        bucket["economic_exit_feasible_count"] += int(bool(row.get("economic_exit_feasible")))
        bucket["economic_exit_captured_count"] += int(bool(row.get("economic_exit_captured")))
        if row.get("signed_slippage_bps_close") is not None:
            bucket["slippage_bps_close_sum"] += _safe_float(row.get("signed_slippage_bps_close"))
            bucket["slippage_bps_close_count"] += 1
        bucket.setdefault("_net_pnls", []).append(_safe_float(row.get("net_pnl")))

    ranking = [
        _finalize_bucket(bucket, min_trades=min_trades)
        for bucket in buckets.values()
    ]
    ranking.sort(
        key=lambda item: (
            _safe_int(item.get("trade_count")),
            _safe_float(item.get("net_pnl")),
        ),
        reverse=True,
    )
    return ranking


def _derive_primary_failure(global_bucket: dict[str, Any], side_buckets: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in side_buckets if _safe_int(row.get("trade_count")) >= 10]
    cost_burden = [
        row for row in eligible if row.get("failure_classification") == "COST_BURDEN_PRIMARY"
    ]
    gross_toxic = [
        row
        for row in eligible
        if row.get("failure_classification") == "ALPHA_GROSS_TOXICITY_PRIMARY"
    ]
    if cost_burden:
        return {
            "primary_failure": "COST_BURDEN_PRIMARY_ON_ELIGIBLE_BUCKET",
            "primary_bucket": cost_burden[0]["name"],
            "next_single_repair_target": (
                "Isolate entry cost-burden on the eligible bucket only; do not loosen "
                "throughput and do not change exit timing."
            ),
        }
    if gross_toxic:
        return {
            "primary_failure": "ALPHA_GROSS_TOXICITY_PRIMARY_ON_ELIGIBLE_BUCKET",
            "primary_bucket": gross_toxic[0]["name"],
            "next_single_repair_target": (
                "Tighten or replace alpha selection for the eligible toxic bucket only."
            ),
        }
    if not eligible:
        return {
            "primary_failure": "SAMPLE_LIMITED_NO_ELIGIBLE_BUCKET",
            "primary_bucket": "",
            "next_single_repair_target": (
                "Collect exact corpus evidence before changing alpha semantics."
            ),
        }
    return {
        "primary_failure": global_bucket.get("failure_classification") or "MIXED_UNRESOLVED",
        "primary_bucket": global_bucket.get("name") or "GLOBAL",
        "next_single_repair_target": "Review one eligible bucket before any runtime change.",
    }


def build_audit(
    *,
    scorecard_path: Path = DEFAULT_SCORECARD_PATH,
    manifest_path: Path | None = None,
    min_trades: int = 10,
    exclude_strategies: str = "auto_test,ExchangeSync",
) -> dict[str, Any]:
    scorecard_path = _resolve_repo_path(scorecard_path)
    scorecard = _load_json(scorecard_path)
    manifest_path = (
        _resolve_repo_path(manifest_path)
        if manifest_path is not None and str(manifest_path).strip()
        else _resolve_repo_path(_scorecard_manifest_text(scorecard))
    )
    manifest = _load_json(manifest_path)
    exclude = {
        token.strip().lower()
        for token in str(exclude_strategies or "").split(",")
        if token.strip()
    }

    locked_subset = build_locked_subset_audit(
        scorecard_path=scorecard_path,
        manifest_path=manifest_path,
        min_trades=min_trades,
        exclude_strategies=exclude_strategies,
    )
    rows = _extract_cost_rows(manifest, exclude_strategies=exclude)
    rankings = {
        "global": _aggregate_cost_rows(rows, grouping="global", min_trades=min_trades),
        "symbol": _aggregate_cost_rows(rows, grouping="symbol", min_trades=min_trades),
        "symbol_strategy": _aggregate_cost_rows(
            rows,
            grouping="symbol_strategy",
            min_trades=min_trades,
        ),
        "symbol_strategy_side": _aggregate_cost_rows(
            rows,
            grouping="symbol_strategy_side",
            min_trades=min_trades,
        ),
    }
    global_bucket = rankings["global"][0] if rankings["global"] else {}
    failure = _derive_primary_failure(global_bucket, rankings["symbol_strategy_side"])
    reason_codes = [
        "EXACT_ACCEPTED_CORPUS_VALIDATED"
        if locked_subset["evidence_contract"]["status"] == "PASS"
        else "INVALID_EXACT_CORPUS_EVIDENCE",
        locked_subset["subset_decision"]["verdict"],
        failure["primary_failure"],
    ]
    if _safe_int(global_bucket.get("gross_positive_net_negative_count")) > 0:
        reason_codes.append("FEE_FLIP_EVENTS_PRESENT")
    if _safe_int(global_bucket.get("gross_nonpositive_count")) > _safe_int(
        global_bucket.get("gross_positive_count")
    ):
        reason_codes.append("GLOBAL_GROSS_TOXICITY_PRESENT")
    if _safe_int(global_bucket.get("missed_feasible_positive_exit_count")) > 0:
        reason_codes.append("EXIT_CAPTURE_CONFOUNDER_PRESENT_BUT_NOT_REPAIRED")

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_type": "alpha_selection_failure_source_audit",
            "method_version": "v1",
            "scope": {
                "exchange": "KuCoin",
                "mode": "PAPER_ONLY",
                "variant": "after",
                "market_data": "real",
                "live_in_scope": False,
            },
            "sources": {
                "scorecard_path": _workspace_rel(scorecard_path),
                "accepted_manifest_path": _workspace_rel(manifest_path),
                "locked_subset_audit": "analysis/locked_positive_expectancy_subset_audit_current.json",
            },
            "thresholds": {
                "min_trades": int(min_trades),
                "exclude_strategies": sorted(exclude),
                "fallback_allowed": False,
            },
        },
        "evidence_contract": {
            "status": locked_subset["evidence_contract"]["status"],
            "locked_subset_verdict": locked_subset["subset_decision"]["verdict"],
            "locked_subset_reason_codes": locked_subset["subset_decision"]["reason_codes"],
            "exact_corpus_rows": len(rows),
        },
        "failure_decision": {
            "status": "NO_GO",
            "reason_codes": reason_codes,
            **failure,
            "runtime_change_allowed": False,
        },
        "cost_burden_summary": global_bucket,
        "rankings": rankings,
    }


def render_markdown(audit: dict[str, Any]) -> str:
    decision = audit["failure_decision"]
    summary = audit["cost_burden_summary"]
    metadata = audit["metadata"]
    lines = [
        "# Alpha Selection Failure Source Audit",
        "",
        f"- status: `{decision['status']}`",
        f"- primary_failure: `{decision['primary_failure']}`",
        f"- primary_bucket: `{decision['primary_bucket']}`",
        f"- runtime_change_allowed: `{decision['runtime_change_allowed']}`",
        f"- accepted_manifest_path: `{metadata['sources']['accepted_manifest_path']}`",
        f"- reason_codes: `{', '.join(decision['reason_codes'])}`",
        "",
        "## Global Cost Burden",
        "",
        f"- trade_count: `{summary.get('trade_count')}`",
        f"- net_pnl: `{summary.get('net_pnl')}`",
        f"- gross_pnl: `{summary.get('gross_pnl')}`",
        f"- fee_total: `{summary.get('fee_total')}`",
        f"- fee_to_abs_gross_ratio: `{summary.get('fee_to_abs_gross_ratio')}`",
        f"- gross_positive_net_negative_count: `{summary.get('gross_positive_net_negative_count')}`",
        f"- gross_nonpositive_count: `{summary.get('gross_nonpositive_count')}`",
        f"- missed_feasible_positive_exit_count: `{summary.get('missed_feasible_positive_exit_count')}`",
        "",
        "## Bucket Ranking",
        "",
        "| bucket | trades | net | gross | fee | fee/abs(gross) | class |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in audit["rankings"]["symbol_strategy_side"][:20]:
        lines.append(
            f"| {row['name']} | {row['trade_count']} | {row['net_pnl']} | "
            f"{row['gross_pnl']} | {row['fee_total']} | "
            f"{row['fee_to_abs_gross_ratio']} | {row['failure_classification']} |"
        )
    lines.extend(
        [
            "",
            "## Next Single Repair Target",
            "",
            f"`{decision['next_single_repair_target']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    audit: dict[str, Any],
    output_json_path: Path = DEFAULT_OUTPUT_JSON,
    output_md_path: Path | None = None,
) -> tuple[Path, Path]:
    output_json_path = _resolve_repo_path(output_json_path)
    output_md_path = (
        _resolve_repo_path(output_md_path)
        if output_md_path is not None and str(output_md_path).strip()
        else output_json_path.with_suffix(".md")
    )
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    output_md_path.write_text(render_markdown(audit), encoding="utf-8")
    return output_json_path, output_md_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit alpha-selection failure source from exact accepted corpus."
    )
    parser.add_argument("--scorecard-path", default=str(DEFAULT_SCORECARD_PATH))
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default="")
    parser.add_argument("--min-trades", type=int, default=10)
    parser.add_argument("--exclude-strategies", default="auto_test,ExchangeSync")
    args = parser.parse_args()
    audit = build_audit(
        scorecard_path=_resolve_repo_path(args.scorecard_path),
        manifest_path=(
            _resolve_repo_path(args.manifest_path)
            if str(args.manifest_path or "").strip()
            else None
        ),
        min_trades=args.min_trades,
        exclude_strategies=args.exclude_strategies,
    )
    output_json, output_md = write_outputs(
        audit,
        output_json_path=_resolve_repo_path(args.output_json),
        output_md_path=(
            _resolve_repo_path(args.output_md)
            if str(args.output_md or "").strip()
            else None
        ),
    )
    decision = audit["failure_decision"]
    summary = audit["cost_burden_summary"]
    print(f"ALPHA_SELECTION_FAILURE_SOURCE_AUDIT_JSON={output_json}")
    print(f"ALPHA_SELECTION_FAILURE_SOURCE_AUDIT_MD={output_md}")
    print(
        "ALPHA_SELECTION_FAILURE_SOURCE "
        f"primary_failure={decision['primary_failure']} "
        f"primary_bucket={decision['primary_bucket']} "
        f"trade_count={summary.get('trade_count')} "
        f"net_pnl={summary.get('net_pnl')} "
        f"gross_pnl={summary.get('gross_pnl')} "
        f"fee_total={summary.get('fee_total')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
