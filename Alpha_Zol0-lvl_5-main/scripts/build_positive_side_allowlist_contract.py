from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
DEFAULT_SCORECARD_PATH = (
    WORKDIR / "analysis" / "zol0_profitability_audit_scorecard.json"
)
DEFAULT_OUTPUT_JSON = (
    WORKDIR / "analysis" / "zol0_positive_side_allowlist_contract_current.json"
)
DEFAULT_OUTPUT_MD = (
    WORKDIR / "analysis" / "zol0_positive_side_allowlist_contract_current.md"
)

DEFAULT_MIN_TRADES = 1
DEFAULT_MIN_WINRATE = 0.45
DEFAULT_MIN_EXPECTANCY = 0.0
DEFAULT_BLOCKED_SIDE_TOKENS = ("ETHUSDTM:TRENDFOLLOWING:buy",)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _workspace_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKDIR.resolve()).as_posix()
    except Exception:
        return str(path)


def _resolve_repo_path(path_text: str) -> Path:
    path = Path(str(path_text or "").strip())
    if path.is_absolute():
        return path.resolve()
    return (WORKDIR / path).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().upper()


def _artifact_descriptor(path: Path) -> dict[str, Any]:
    return {
        "path": _workspace_rel(path),
        "size_bytes": int(path.stat().st_size) if path.exists() else 0,
        "sha256": _sha256_file(path) if path.exists() and path.is_file() else "",
        "mtime_utc": (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if path.exists()
            else ""
        ),
    }


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


def _normalize_side(side: Any) -> str:
    text = str(side or "").strip().lower()
    if text == "long":
        return "buy"
    if text == "short":
        return "sell"
    return text


def _normalize_side_token(token: Any) -> str:
    parts = [part.strip() for part in str(token or "").split(":")]
    if len(parts) != 3:
        return ""
    symbol, strategy, side = parts
    side_norm = _normalize_side(side)
    if not symbol or not strategy or side_norm not in {"buy", "sell"}:
        return ""
    return f"{symbol.upper()}:{strategy.upper()}:{side_norm}"


def _validate_scorecard_contract(scorecard: dict[str, Any]) -> dict[str, bool]:
    metadata = scorecard.get("metadata") or {}
    scope = metadata.get("scope") or {}
    selection = metadata.get("selection") or {}
    return {
        "report_type_ok": metadata.get("report_type")
        == "zol0_profitability_audit_scorecard",
        "scope_exchange_kucoin": str(scope.get("exchange") or "").lower()
        == "kucoin",
        "scope_mode_paper": "paper" in str(scope.get("mode") or "").lower(),
        "scope_variant_after": str(scope.get("variant") or "").lower() == "after",
        "scope_live_false": scope.get("live_in_scope") is False,
        "selection_source_accepted_manifest": selection.get("selection_source")
        == "accepted_manifest",
        "accepted_run_ids_present": bool(selection.get("accepted_run_ids") or []),
    }


def _validate_manifest_contract(
    *,
    manifest: dict[str, Any],
    scorecard: dict[str, Any],
) -> dict[str, bool]:
    selection = (scorecard.get("metadata") or {}).get("selection") or {}
    expected_ids = [str(x) for x in (selection.get("accepted_run_ids") or [])]
    entries = manifest.get("entries") or []
    manifest_ids = [str((entry or {}).get("run_id") or "") for entry in entries]
    validation = manifest.get("bundle_validation") or {}
    required_validation = [
        "accepted_run_count_matches_scorecard",
        "all_source_artifacts_present",
        "all_source_artifacts_nonzero",
        "all_bundled_hashes_match_source",
        "all_bundled_result_after_only",
        "all_bundled_result_use_mock_false",
        "all_bundled_result_process_ok",
    ]
    return {
        "report_type_ok": manifest.get("report_type")
        == "zol0_accepted_corpus_manifest",
        "entry_count_matches_scorecard": len(entries)
        == _safe_int(selection.get("accepted_run_count")),
        "run_ids_match_scorecard": set(manifest_ids) == set(expected_ids),
        "bundle_validation_pass": all(
            bool(validation.get(key)) for key in required_validation
        ),
    }


def _derive_positive_side_entries(
    *,
    bootstrap_report: dict[str, Any],
    min_trades: int,
    min_winrate: float,
    min_expectancy: float,
) -> list[dict[str, Any]]:
    selected_pairs = set()
    for row in bootstrap_report.get("pair_stats_top") or []:
        if not isinstance(row, dict) or not bool(row.get("selected")):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        strategy = str(row.get("strategy") or "").strip().upper()
        if symbol and strategy:
            selected_pairs.add(f"{symbol}:{strategy}")

    entries = []
    for row in bootstrap_report.get("pair_side_stats_top") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        strategy = str(row.get("strategy") or "").strip().upper()
        side = _normalize_side(row.get("side"))
        if not symbol or not strategy or side not in {"buy", "sell"}:
            continue
        pair_key = f"{symbol}:{strategy}"
        trade_count = _safe_int(row.get("trade_count"))
        winrate = _safe_float(row.get("winrate"))
        expectancy = _safe_float(row.get("expectancy"))
        if (
            pair_key not in selected_pairs
            or trade_count < int(min_trades)
            or winrate < float(min_winrate)
            or expectancy <= float(min_expectancy)
        ):
            continue
        entries.append(
            {
                "token": f"{symbol}:{strategy}:{side}",
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "trade_count": trade_count,
                "winrate": winrate,
                "expectancy": expectancy,
                "net_pnl": _safe_float(row.get("net_pnl")),
                "gross_pnl": _safe_float(row.get("gross_pnl")),
                "fee_total": _safe_float(row.get("fee_total")),
            }
        )
    return sorted(entries, key=lambda item: item["token"])


def build_contract(
    *,
    scorecard_path: Path,
    min_trades: int = DEFAULT_MIN_TRADES,
    min_winrate: float = DEFAULT_MIN_WINRATE,
    min_expectancy: float = DEFAULT_MIN_EXPECTANCY,
    blocked_side_tokens: list[str] | tuple[str, ...] = DEFAULT_BLOCKED_SIDE_TOKENS,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    scorecard_path = scorecard_path.resolve()
    scorecard: dict[str, Any] = {}
    if not scorecard_path.exists():
        reason_codes.append("SCORECARD_MISSING")
    else:
        try:
            scorecard = _load_json(scorecard_path)
        except Exception:
            reason_codes.append("SCORECARD_UNREADABLE")

    scorecard_checks = _validate_scorecard_contract(scorecard) if scorecard else {}
    for key, ok in scorecard_checks.items():
        if not ok:
            reason_codes.append(f"SCORECARD_{key.upper()}_FAILED")

    metadata = scorecard.get("metadata") or {}
    selection = metadata.get("selection") or {}
    sources = metadata.get("sources") or {}
    manifest_path_text = str(
        sources.get("accepted_corpus_manifest_path")
        or selection.get("accepted_manifest_path")
        or ""
    ).strip()
    bootstrap_report_text = str(sources.get("bootstrap_report_path") or "").strip()

    manifest_path = (
        _resolve_repo_path(manifest_path_text) if manifest_path_text else None
    )
    bootstrap_report_path = (
        _resolve_repo_path(bootstrap_report_text) if bootstrap_report_text else None
    )

    manifest: dict[str, Any] = {}
    manifest_checks: dict[str, bool] = {}
    if not manifest_path:
        reason_codes.append("ACCEPTED_MANIFEST_PATH_MISSING")
    elif not manifest_path.exists():
        reason_codes.append("ACCEPTED_MANIFEST_MISSING")
    else:
        try:
            manifest = _load_json(manifest_path)
            manifest_checks = _validate_manifest_contract(
                manifest=manifest,
                scorecard=scorecard,
            )
            for key, ok in manifest_checks.items():
                if not ok:
                    reason_codes.append(f"ACCEPTED_MANIFEST_{key.upper()}_FAILED")
        except Exception:
            reason_codes.append("ACCEPTED_MANIFEST_UNREADABLE")

    bootstrap_report: dict[str, Any] = {}
    if not bootstrap_report_path:
        reason_codes.append("BOOTSTRAP_REPORT_PATH_MISSING")
    elif not bootstrap_report_path.exists():
        reason_codes.append("BOOTSTRAP_REPORT_MISSING")
    else:
        try:
            bootstrap_report = _load_json(bootstrap_report_path)
        except Exception:
            reason_codes.append("BOOTSTRAP_REPORT_UNREADABLE")

    selected_pair_count = set()
    for row in bootstrap_report.get("pair_stats_top") or []:
        if not isinstance(row, dict) or not bool(row.get("selected")):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        strategy = str(row.get("strategy") or "").strip().upper()
        if symbol and strategy:
            selected_pair_count.add(f"{symbol}:{strategy}")
    selected_pair_count = len(selected_pair_count)

    rows_inserted = _safe_int(bootstrap_report.get("rows_inserted"))
    pairs_selected = _safe_int(bootstrap_report.get("pairs_selected"))
    sources_used = _safe_int(bootstrap_report.get("sources_used"))
    if rows_inserted <= 0:
        reason_codes.append("BOOTSTRAP_ROWS_INSERTED_ZERO")
    if pairs_selected <= 0:
        reason_codes.append("BOOTSTRAP_PAIRS_SELECTED_ZERO")
    if pairs_selected != selected_pair_count:
        reason_codes.append("BOOTSTRAP_PAIRS_SELECTED_MISMATCH")
    if sources_used <= 0:
        reason_codes.append("BOOTSTRAP_SOURCES_USED_ZERO")

    raw_entries = _derive_positive_side_entries(
        bootstrap_report=bootstrap_report,
        min_trades=min_trades,
        min_winrate=min_winrate,
        min_expectancy=min_expectancy,
    )
    blocked_tokens = sorted(
        {
            token
            for token in (_normalize_side_token(item) for item in blocked_side_tokens)
            if token
        }
    )
    blocked_set = set(blocked_tokens)
    blocked_entries = [
        entry for entry in raw_entries if str(entry.get("token") or "") in blocked_set
    ]
    entries = [
        entry
        for entry in raw_entries
        if str(entry.get("token") or "") not in blocked_set
    ]
    allowlist = [entry["token"] for entry in entries]
    if blocked_entries and not entries:
        reason_codes.append("ALL_POSITIVE_SIDE_BUCKETS_BLOCKED")
    elif blocked_entries:
        reason_codes.append("SOME_POSITIVE_SIDE_BUCKETS_BLOCKED")
    if not allowlist:
        reason_codes.append("NO_ELIGIBLE_POSITIVE_SIDE_BUCKETS")

    status = "PASS" if not reason_codes else "FAIL_CLOSED"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_type": "zol0_positive_side_allowlist_contract",
        "contract_version": "v1",
        "status": status,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "scope": {
            "exchange": "KuCoin",
            "mode": "PAPER_ONLY",
            "variant": "after",
            "market_data": "real",
            "live_in_scope": False,
        },
        "thresholds": {
            "min_trades": int(min_trades),
            "min_winrate": float(min_winrate),
            "min_expectancy": float(min_expectancy),
            "pair_must_be_selected": True,
            "fallback_allowed": False,
            "blocked_side_tokens": blocked_tokens,
        },
        "sources": {
            "scorecard": _artifact_descriptor(scorecard_path)
            if scorecard_path.exists()
            else {"path": _workspace_rel(scorecard_path)},
            "accepted_manifest": _artifact_descriptor(manifest_path)
            if manifest_path and manifest_path.exists()
            else {"path": manifest_path_text},
            "bootstrap_report": _artifact_descriptor(bootstrap_report_path)
            if bootstrap_report_path and bootstrap_report_path.exists()
            else {"path": bootstrap_report_text},
        },
        "evidence_contract": {
            "scorecard_checks": scorecard_checks,
            "accepted_manifest_checks": manifest_checks,
            "bootstrap_rows_inserted": rows_inserted,
            "bootstrap_pairs_selected": pairs_selected,
            "bootstrap_sources_used": sources_used,
            "accepted_run_count": _safe_int(selection.get("accepted_run_count")),
            "accepted_run_ids": list(selection.get("accepted_run_ids") or []),
        },
        "blocked_positive_side_allowlist": [
            entry["token"] for entry in blocked_entries
        ],
        "blocked_entries": blocked_entries,
        "positive_side_allowlist": allowlist,
        "entries": entries,
    }


def render_markdown(contract: dict[str, Any]) -> str:
    lines = [
        "# Positive Side Allowlist Contract",
        "",
        f"- status: `{contract.get('status')}`",
        f"- reason_codes: `{','.join(contract.get('reason_codes') or []) or '-'}`",
        f"- allowlist: `"
        f"{','.join(contract.get('positive_side_allowlist') or []) or '-'}`",
        f"- blocked_allowlist: `"
        f"{','.join(contract.get('blocked_positive_side_allowlist') or []) or '-'}`",
        "",
        "## Entries",
    ]
    for entry in contract.get("entries") or []:
        lines.append(
            f"- `{entry['token']}` trades={entry['trade_count']} "
            f"wr={entry['winrate']:.4f} exp={entry['expectancy']:.6f}"
        )
    if not contract.get("entries"):
        lines.append("- none")
    lines.extend(["", "## Blocked Entries"])
    for entry in contract.get("blocked_entries") or []:
        lines.append(
            f"- `{entry['token']}` trades={entry['trade_count']} "
            f"wr={entry['winrate']:.4f} exp={entry['expectancy']:.6f}"
        )
    if not contract.get("blocked_entries"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build exact positive side allowlist contract for PAPER validation."
    )
    parser.add_argument("--scorecard-path", default=str(DEFAULT_SCORECARD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    parser.add_argument("--min-winrate", type=float, default=DEFAULT_MIN_WINRATE)
    parser.add_argument("--min-expectancy", type=float, default=DEFAULT_MIN_EXPECTANCY)
    parser.add_argument(
        "--blocked-side-token",
        action="append",
        default=list(DEFAULT_BLOCKED_SIDE_TOKENS),
        help=(
            "Symbol:strategy:side token that must never be emitted into the "
            "positive allowlist. May be repeated."
        ),
    )
    args = parser.parse_args(argv)

    contract = build_contract(
        scorecard_path=_resolve_repo_path(args.scorecard_path),
        min_trades=int(args.min_trades),
        min_winrate=float(args.min_winrate),
        min_expectancy=float(args.min_expectancy),
        blocked_side_tokens=list(args.blocked_side_token or []),
    )
    output_json = _resolve_repo_path(args.output_json)
    output_md = _resolve_repo_path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(contract), encoding="utf-8")
    print(f"POSITIVE_SIDE_ALLOWLIST_CONTRACT_JSON={output_json}")
    print(f"POSITIVE_SIDE_ALLOWLIST_CONTRACT_MD={output_md}")
    print(
        "POSITIVE_SIDE_ALLOWLIST_CONTRACT "
        f"status={contract.get('status')} "
        f"allowlist={','.join(contract.get('positive_side_allowlist') or []) or '-'} "
        f"reasons={','.join(contract.get('reason_codes') or []) or '-'}"
    )
    return 0 if contract.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
