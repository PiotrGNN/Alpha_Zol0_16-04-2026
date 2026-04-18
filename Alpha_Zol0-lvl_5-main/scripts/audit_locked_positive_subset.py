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

from build_alpha_history_db import _normalize_close_row  # noqa: E402
from profitability_audit_scorecard import (  # noqa: E402
    _load_json,
    _main_run_process_ok,
    _resolve_repo_path,
    _safe_float,
    _safe_int,
    _sha256_file,
    _workspace_rel,
)


WORKDIR = Path(__file__).resolve().parents[1]
DEFAULT_SCORECARD_PATH = WORKDIR / "analysis" / "zol0_profitability_audit_scorecard.json"
DEFAULT_OUTPUT_JSON = (
    WORKDIR / "analysis" / "locked_positive_expectancy_subset_audit_current.json"
)
REQUIRED_MANIFEST_BUNDLE_CHECKS = (
    "accepted_run_count_matches_scorecard",
    "all_source_artifacts_present",
    "all_source_artifacts_nonzero",
    "all_bundled_hashes_match_source",
    "all_bundled_result_after_only",
    "all_bundled_result_use_mock_false",
    "all_bundled_result_process_ok",
)


def _round6(value: Any) -> float:
    return round(_safe_float(value), 6)


def _profit_factor(gross_profit: float, gross_loss_abs: float) -> float | None:
    if gross_loss_abs > 0:
        return gross_profit / gross_loss_abs
    if gross_profit > 0:
        return math.inf
    return 0.0


def _display_profit_factor(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isinf(value):
        return "Infinity"
    return _round6(value)


def _profit_factor_sort(value: float | str | None) -> float:
    if value == "Infinity":
        return 1_000_000.0
    if value is None:
        return -1.0
    return _safe_float(value, default=-1.0)


def _scorecard_manifest_text(scorecard: dict[str, Any]) -> str:
    metadata = scorecard.get("metadata") or {}
    sources = metadata.get("sources") or {}
    selection = metadata.get("selection") or {}
    return str(
        sources.get("accepted_corpus_manifest_path")
        or selection.get("accepted_manifest_path")
        or ""
    ).strip()


def _manifest_artifact(entry: dict[str, Any], key: str) -> dict[str, Any]:
    return ((entry.get("bundled_artifacts") or {}).get(key) or {})


def _manifest_artifact_path(entry: dict[str, Any], key: str) -> Path:
    path_text = str(_manifest_artifact(entry, key).get("path") or "").strip()
    if not path_text:
        raise ValueError(f"manifest entry missing bundled artifact path: {key}")
    return _resolve_repo_path(path_text)


def _artifact_check(entry: dict[str, Any], key: str, run_id: str) -> dict[str, Any]:
    descriptor = _manifest_artifact(entry, key)
    path = _manifest_artifact_path(entry, key)
    exists = path.exists()
    size_bytes = int(path.stat().st_size) if exists and path.is_file() else 0
    expected_sha = str(descriptor.get("sha256") or "").strip()
    actual_sha = _sha256_file(path) if exists and path.is_file() else ""
    checks = {
        "path_present": bool(str(descriptor.get("path") or "").strip()),
        "exists": bool(exists),
        "nonzero": bool(size_bytes > 0),
        "sha256_match": bool((not expected_sha) or expected_sha == actual_sha),
    }
    return {
        "run_id": run_id,
        "artifact_key": key,
        "path": _workspace_rel(path),
        "size_bytes": size_bytes,
        "checks": checks,
        "ok": all(checks.values()),
    }


def _result_check(result_path: Path, db_path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    payload = _load_json(result_path)
    after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    process_ok = _main_run_process_ok(
        {
            "process_returncode": _safe_int(after.get("process_returncode")),
            "log_error_count": _safe_int((after.get("log_health") or {}).get("error_count")),
            "shutdown_classification": str(after.get("shutdown_classification") or ""),
        }
    )
    checks = {
        "after_present": bool(after),
        "after_variant": str(after.get("variant") or "").lower() == "after",
        "use_mock_false": params.get("use_mock") is False,
        "process_ok": bool(process_ok),
        "db_nonzero": db_path.exists() and db_path.stat().st_size > 0,
    }
    return {
        "run_id": str(entry.get("run_id") or payload.get("run_id") or ""),
        "path": _workspace_rel(result_path),
        "trade_count": _safe_int(after.get("trade_count")),
        "net_pnl": _round6(after.get("net_pnl")),
        "checks": checks,
        "ok": all(checks.values()),
    }


def _extract_deduped_rows(
    manifest: dict[str, Any],
    exclude_strategies: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_rows: list[dict[str, Any]] = []
    deduped_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    artifact_checks: list[dict[str, Any]] = []
    result_checks: list[dict[str, Any]] = []
    run_summaries: list[dict[str, Any]] = []

    for entry in manifest.get("entries") or []:
        if not isinstance(entry, dict):
            raise ValueError("manifest entry must be an object")
        run_id = str(entry.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("manifest entry has empty run_id")
        result_path = _manifest_artifact_path(entry, "result_json")
        csv_path = _manifest_artifact_path(entry, "csv")
        db_path = _manifest_artifact_path(entry, "db")
        for key in ("result_json", "csv", "db"):
            artifact_checks.append(_artifact_check(entry, key, run_id))
        result_checks.append(_result_check(result_path, db_path, entry))

        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, timestamp, details FROM logs "
                "WHERE event='position_close' ORDER BY id ASC"
            ).fetchall()
        finally:
            conn.close()

        valid_rows = 0
        for log_id, ts_raw, details_raw in rows:
            normalized = _normalize_close_row(
                ts_raw,
                details_raw,
                exclude_strategies=exclude_strategies or set(),
            )
            if normalized is None:
                continue
            ts, details, dedupe_key = normalized
            valid_rows += 1
            position = details.get("position") or {}
            row = {
                "run_id": run_id,
                "db_path": _workspace_rel(db_path),
                "log_id": _safe_int(log_id),
                "timestamp": str(ts or ""),
                "symbol": str(position.get("symbol") or details.get("symbol") or "").upper(),
                "strategy": str(position.get("strategy") or details.get("strategy") or ""),
                "side": str(position.get("side") or details.get("side") or "").lower(),
                "realized_pnl": _safe_float(
                    position.get("realized_pnl", details.get("realized_pnl"))
                ),
                "dedupe_key": dedupe_key,
            }
            raw_rows.append(row)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            deduped_rows.append(row)

        run_summaries.append(
            {
                "run_id": run_id,
                "manifest_trade_count": _safe_int(entry.get("trade_count")),
                "position_close_rows": len(rows),
                "valid_position_close_rows": valid_rows,
                "manifest_net_pnl": _round6(entry.get("net_pnl")),
                "db_path": _workspace_rel(db_path),
                "csv_path": _workspace_rel(csv_path),
                "result_json_path": _workspace_rel(result_path),
            }
        )

    extraction = {
        "raw_rows": raw_rows,
        "artifact_checks": artifact_checks,
        "result_checks": result_checks,
        "run_summaries": run_summaries,
        "all_artifacts_ok": all(item.get("ok") for item in artifact_checks),
        "all_results_ok": all(item.get("ok") for item in result_checks),
        "all_close_counts_within_manifest_after_exclusions": all(
            _safe_int(item.get("valid_position_close_rows"))
            <= _safe_int(item.get("manifest_trade_count"))
            for item in run_summaries
        ),
    }
    return deduped_rows, extraction


def _aggregate(
    rows: list[dict[str, Any]],
    grouping: str,
    thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        if grouping == "symbol":
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
        bucket = groups.setdefault(
            key,
            {
                "grouping": grouping,
                "name": name,
                "symbol": row["symbol"],
                "strategy": row["strategy"] if len(key) >= 2 else "",
                "side": row["side"] if len(key) >= 3 else "",
                "trade_count": 0,
                "wins": 0,
                "losses": 0,
                "gross_profit": 0.0,
                "gross_loss_abs": 0.0,
                "net_pnl": 0.0,
            },
        )
        pnl = _safe_float(row.get("realized_pnl"))
        bucket["trade_count"] += 1
        bucket["net_pnl"] += pnl
        if pnl > 0:
            bucket["wins"] += 1
            bucket["gross_profit"] += pnl
        elif pnl < 0:
            bucket["losses"] += 1
            bucket["gross_loss_abs"] += abs(pnl)

    ranking: list[dict[str, Any]] = []
    for bucket in groups.values():
        trade_count = _safe_int(bucket["trade_count"])
        net_pnl = _safe_float(bucket["net_pnl"])
        winrate = _safe_float(bucket["wins"]) / trade_count if trade_count > 0 else 0.0
        expectancy = net_pnl / trade_count if trade_count > 0 else 0.0
        pf = _display_profit_factor(
            _profit_factor(
                _safe_float(bucket["gross_profit"]),
                _safe_float(bucket["gross_loss_abs"]),
            )
        )
        rejections: list[str] = []
        if trade_count < _safe_int(thresholds["min_trades"]):
            rejections.append("BELOW_MIN_TRADES")
        if winrate < _safe_float(thresholds["min_winrate"]):
            rejections.append("BELOW_MIN_WINRATE")
        if expectancy < _safe_float(thresholds["min_expectancy"]):
            rejections.append("BELOW_MIN_EXPECTANCY")
        if net_pnl < _safe_float(thresholds["min_net_pnl"]):
            rejections.append("NEGATIVE_NET_PNL")
        if _profit_factor_sort(pf) < _safe_float(thresholds["min_profit_factor"]):
            rejections.append("PROFIT_FACTOR_BELOW_MIN")
        ranking.append(
            {
                **bucket,
                "trade_count": trade_count,
                "wins": _safe_int(bucket["wins"]),
                "losses": _safe_int(bucket["losses"]),
                "gross_profit": _round6(bucket["gross_profit"]),
                "gross_loss_abs": _round6(bucket["gross_loss_abs"]),
                "net_pnl": _round6(net_pnl),
                "avg_pnl_per_trade": _round6(expectancy),
                "expectancy": _round6(expectancy),
                "winrate": _round6(winrate),
                "profit_factor": pf,
                "selected": not rejections,
                "rejection_reasons": rejections,
            }
        )
    ranking.sort(
        key=lambda item: (
            bool(item.get("selected")),
            _safe_float(item.get("net_pnl")),
            _profit_factor_sort(item.get("profit_factor")),
            _safe_int(item.get("trade_count")),
        ),
        reverse=True,
    )
    return ranking


def _scorecard_contract(
    scorecard_path: Path,
    scorecard: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    metadata = scorecard.get("metadata") or {}
    scope = metadata.get("scope") or {}
    selection = metadata.get("selection") or {}
    manifest_text = _scorecard_manifest_text(scorecard)
    referenced = _resolve_repo_path(manifest_text) if manifest_text else None
    checks = {
        "scorecard_exists": scorecard_path.exists(),
        "report_type_ok": metadata.get("report_type") == "zol0_profitability_audit_scorecard",
        "scope_exchange_kucoin": str(scope.get("exchange") or "").lower() == "kucoin",
        "scope_mode_paper": str(scope.get("mode") or "").upper() == "PAPER_ONLY",
        "scope_variant_after": str(scope.get("variant") or "").lower() == "after",
        "scope_live_false": scope.get("live_in_scope") is False,
        "selection_accepted_manifest": selection.get("selection_source")
        == "accepted_manifest",
        "manifest_path_referenced": bool(manifest_text),
        "manifest_path_matches": bool(
            referenced is not None and referenced.resolve() == manifest_path.resolve()
        ),
    }
    return {
        "path": _workspace_rel(scorecard_path),
        "referenced_manifest_path": manifest_text,
        "checks": checks,
        "ok": all(checks.values()),
    }


def _reason_codes(
    evidence_ok: bool,
    selected_count: int,
    rejected_positive: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> list[str]:
    if not evidence_ok:
        return ["INVALID_EXACT_CORPUS_EVIDENCE"]
    codes = ["EXACT_ACCEPTED_CORPUS_VALIDATED"]
    if selected_count > 0:
        codes.append("LOCKED_POSITIVE_SUBSET_FOUND")
        return codes
    codes.extend(["NO_POSITIVE_SUBSET_FOUND", f"STRICT_MIN_TRADES_{thresholds['min_trades']}"])
    if rejected_positive:
        codes.append("POSITIVE_BUCKETS_REJECTED_BY_STRICT_THRESHOLDS")
    if any("BELOW_MIN_TRADES" in row.get("rejection_reasons", []) for row in rejected_positive):
        codes.append("BEST_POSITIVE_BUCKET_TINY_SAMPLE")
    return codes


def build_audit(
    *,
    scorecard_path: Path = DEFAULT_SCORECARD_PATH,
    manifest_path: Path | None = None,
    min_trades: int = 10,
    min_winrate: float = 0.40,
    min_expectancy: float = 0.0,
    min_net_pnl: float = 0.0,
    min_profit_factor: float = 1.0,
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
    thresholds = {
        "candidate_grouping": "symbol_strategy_side",
        "min_trades": max(1, int(min_trades)),
        "min_winrate": float(min_winrate),
        "min_expectancy": float(min_expectancy),
        "min_net_pnl": float(min_net_pnl),
        "min_profit_factor": float(min_profit_factor),
        "exclude_strategies": sorted(
            {
                token.strip().lower()
                for token in str(exclude_strategies or "").split(",")
                if token.strip()
            }
        ),
        "fallback_allowed": False,
    }

    deduped_rows, extraction = _extract_deduped_rows(
        manifest,
        exclude_strategies=set(thresholds["exclude_strategies"]),
    )
    rankings = {
        "symbol": _aggregate(deduped_rows, "symbol", thresholds),
        "symbol_strategy": _aggregate(deduped_rows, "symbol_strategy", thresholds),
        "symbol_strategy_side": _aggregate(
            deduped_rows,
            "symbol_strategy_side",
            thresholds,
        ),
    }
    selected = [row for row in rankings["symbol_strategy_side"] if row["selected"]]
    rejected_positive = [
        row
        for row in rankings["symbol_strategy_side"]
        if _safe_float(row.get("net_pnl")) > 0 and not row["selected"]
    ]
    scorecard_contract = _scorecard_contract(scorecard_path, scorecard, manifest_path)
    manifest_scope = manifest.get("scope") if isinstance(manifest.get("scope"), dict) else {}
    manifest_bundle_validation = (
        manifest.get("bundle_validation")
        if isinstance(manifest.get("bundle_validation"), dict)
        else {}
    )
    evidence_checks = {
        "scorecard_contract_ok": bool(scorecard_contract["ok"]),
        "scorecard_validation_all_passed": bool(
            ((scorecard.get("metadata") or {}).get("validation") or {}).get("all_passed")
        ),
        "manifest_scope_exchange_kucoin": str(manifest_scope.get("exchange") or "").lower()
        == "kucoin",
        "manifest_scope_paper_only": str(manifest_scope.get("mode") or "").upper()
        == "PAPER_ONLY",
        "manifest_scope_after": str(manifest_scope.get("variant") or "").lower() == "after",
        "manifest_live_false": manifest_scope.get("live_in_scope") is False,
        "manifest_bundle_validation_ok": all(
            bool(manifest_bundle_validation.get(key))
            for key in REQUIRED_MANIFEST_BUNDLE_CHECKS
        ),
        "artifacts_present_nonzero_hash_match": bool(extraction["all_artifacts_ok"]),
        "result_payloads_after_real_paper_process_ok": bool(extraction["all_results_ok"]),
        "close_counts_within_manifest_after_exclusions": bool(
            extraction["all_close_counts_within_manifest_after_exclusions"]
        ),
        "deduped_closed_rows_present": len(deduped_rows) > 0,
    }
    evidence_ok = all(evidence_checks.values())
    selected_count = len(selected) if evidence_ok else 0
    verdict = (
        "LOCKED_POSITIVE_SUBSET_FOUND"
        if evidence_ok and selected_count > 0
        else "NO_POSITIVE_SUBSET_FOUND"
        if evidence_ok
        else "INVALID_EXACT_CORPUS_EVIDENCE"
    )
    status = "PASS" if verdict == "LOCKED_POSITIVE_SUBSET_FOUND" else "NO_GO"
    if verdict == "INVALID_EXACT_CORPUS_EVIDENCE":
        status = "FAIL"

    raw_rows = extraction["raw_rows"]
    gross_profit = sum(
        _safe_float(row["realized_pnl"]) for row in deduped_rows if row["realized_pnl"] > 0
    )
    gross_loss_abs = sum(
        abs(_safe_float(row["realized_pnl"]))
        for row in deduped_rows
        if row["realized_pnl"] < 0
    )
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_type": "locked_positive_expectancy_subset_audit",
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
                "bundle_dir": str(manifest.get("bundle_dir") or ""),
            },
            "thresholds": thresholds,
        },
        "evidence_contract": {
            "status": "PASS" if evidence_ok else "FAIL",
            "checks": evidence_checks,
            "scorecard_contract": scorecard_contract,
            "manifest_bundle_validation": manifest_bundle_validation,
            "failed_artifact_checks": [
                item for item in extraction["artifact_checks"] if not item["ok"]
            ],
            "failed_result_checks": [
                item for item in extraction["result_checks"] if not item["ok"]
            ],
        },
        "corpus_summary": {
            "accepted_run_count": _safe_int(
                (manifest.get("selection") or {}).get("accepted_run_count"),
                default=len(manifest.get("entries") or []),
            ),
            "raw_closed_rows": len(raw_rows),
            "deduped_closed_rows": len(deduped_rows),
            "duplicate_closed_rows_removed": max(0, len(raw_rows) - len(deduped_rows)),
            "deduped_total_net_pnl": _round6(
                sum(_safe_float(row["realized_pnl"]) for row in deduped_rows)
            ),
            "deduped_profit_factor": _display_profit_factor(
                _profit_factor(gross_profit, gross_loss_abs)
            ),
            "dedupe_key_version": "build_alpha_history_compatible_v1",
            "run_summaries": extraction["run_summaries"],
        },
        "subset_decision": {
            "status": status,
            "verdict": verdict,
            "reason_codes": _reason_codes(
                evidence_ok,
                selected_count,
                rejected_positive,
                thresholds,
            ),
            "selected_candidate_count": selected_count,
            "locked_symbol_strategy_side_allowlist": [
                f"{row['symbol']}:{row['strategy'].upper()}:{row['side']}"
                for row in selected
            ],
            "fallback_allowed": False,
            "next_runtime_action_allowed": evidence_ok and selected_count > 0,
        },
        "rankings": rankings,
        "rejected_positive_candidates": rejected_positive[:20],
    }


def render_markdown(audit: dict[str, Any]) -> str:
    metadata = audit["metadata"]
    decision = audit["subset_decision"]
    corpus = audit["corpus_summary"]
    evidence = audit["evidence_contract"]
    thresholds = metadata["thresholds"]
    lines = [
        "# Locked Positive Expectancy Subset Audit",
        "",
        f"- status: `{decision['status']}`",
        f"- verdict: `{decision['verdict']}`",
        f"- evidence_status: `{evidence['status']}`",
        f"- accepted_manifest_path: `{metadata['sources']['accepted_manifest_path']}`",
        f"- raw_closed_rows: `{corpus['raw_closed_rows']}`",
        f"- deduped_closed_rows: `{corpus['deduped_closed_rows']}`",
        f"- deduped_total_net_pnl: `{corpus['deduped_total_net_pnl']}`",
        f"- min_trades: `{thresholds['min_trades']}`",
        f"- min_winrate: `{thresholds['min_winrate']}`",
        f"- min_expectancy: `{thresholds['min_expectancy']}`",
        f"- min_profit_factor: `{thresholds['min_profit_factor']}`",
        f"- reason_codes: `{', '.join(decision['reason_codes'])}`",
        "",
        "| bucket | trades | net_pnl | avg_pnl | winrate | pf | selected | reasons |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in audit["rankings"]["symbol_strategy_side"][:20]:
        lines.append(
            f"| {row['name']} | {row['trade_count']} | {row['net_pnl']} | "
            f"{row['avg_pnl_per_trade']} | {row['winrate']} | "
            f"{row['profit_factor']} | {row['selected']} | "
            f"{','.join(row['rejection_reasons'])} |"
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
        description="Audit locked positive-expectancy subset from exact accepted corpus."
    )
    parser.add_argument("--scorecard-path", default=str(DEFAULT_SCORECARD_PATH))
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default="")
    parser.add_argument("--min-trades", type=int, default=10)
    parser.add_argument("--min-winrate", type=float, default=0.40)
    parser.add_argument("--min-expectancy", type=float, default=0.0)
    parser.add_argument("--min-net-pnl", type=float, default=0.0)
    parser.add_argument("--min-profit-factor", type=float, default=1.0)
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
        min_winrate=args.min_winrate,
        min_expectancy=args.min_expectancy,
        min_net_pnl=args.min_net_pnl,
        min_profit_factor=args.min_profit_factor,
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
    decision = audit["subset_decision"]
    corpus = audit["corpus_summary"]
    print(f"LOCKED_POSITIVE_SUBSET_AUDIT_JSON={output_json}")
    print(f"LOCKED_POSITIVE_SUBSET_AUDIT_MD={output_md}")
    print(
        "LOCKED_POSITIVE_SUBSET "
        f"status={decision['status']} "
        f"verdict={decision['verdict']} "
        f"selected={decision['selected_candidate_count']} "
        f"raw_closed_rows={corpus['raw_closed_rows']} "
        f"deduped_closed_rows={corpus['deduped_closed_rows']}"
    )
    return 2 if decision["verdict"] == "INVALID_EXACT_CORPUS_EVIDENCE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
