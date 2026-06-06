import argparse
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter


WORKDIR = Path(__file__).resolve().parents[1]
TMP_DIR = WORKDIR / "tmp"
RESULTS_DIR = WORKDIR / "results"
ARTIFACTS_DIR = WORKDIR / "artifacts"
DIAGNOSTICS_DIR = ARTIFACTS_DIR / "diagnostics"
TMP_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)
if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))


def _parse_symbols(value: str):
    if not value:
        return []
    return [s.strip() for s in str(value).split(",") if s.strip()]


def _parse_env_overrides(items):
    out = {}
    for raw in items or []:
        txt = str(raw or "").strip()
        if not txt:
            continue
        if "=" not in txt:
            raise SystemExit(f"Invalid env override (expected KEY=VALUE): {txt}")
        key, value = txt.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit(f"Invalid env override key: {txt}")
        out[key] = value
    return out


def _resolve_run_id(explicit_run_id: str | None = None) -> str:
    run_id = str(explicit_run_id or "").strip()
    if run_id:
        if not re.fullmatch(r"\d{8}_\d{6}", run_id):
            raise SystemExit("--run-id must match YYYYMMDD_HHMMSS")
        return run_id
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _merge_csv_values(existing, incoming):
    vals = set()
    for raw in (existing, incoming):
        for part in str(raw or "").split(","):
            token = str(part or "").strip()
            if token:
                vals.add(token)
    return ",".join(sorted(vals))


def _merge_csv_tokens_preserving_order(*values) -> str:
    merged = []
    seen = set()
    for raw in values:
        for part in str(raw or "").split(","):
            token = str(part or "").strip()
            if not token or token in seen:
                continue
            merged.append(token)
            seen.add(token)
    return ",".join(merged)


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "y", "on"}:
        return True
    if txt in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _build_entry_gate_summary_artifact(
    *,
    run_id: str,
    variant_metrics: dict | None,
) -> dict:
    if not isinstance(variant_metrics, dict):
        return {}

    db_path_txt = str(variant_metrics.get("db_path") or "").strip()
    variant_name = str(variant_metrics.get("variant") or "").strip() or "run"
    if not db_path_txt:
        return {}

    db_path = Path(db_path_txt)
    try:
        db_path = db_path.resolve()
    except Exception:
        pass
    if not db_path.exists():
        return {}

    try:
        from scripts.report_entry_gate_decision_summary import build_report

        summary = build_report(db_path, hours=None)
    except Exception as exc:
        return {
            "summary_json": "",
            "entry_gate_report_path": "",
            "summary": {},
            "summary_error": f"{type(exc).__name__}: {exc}",
        }

    summary_path = RESULTS_DIR / f"controlled_kpi_{run_id}_{variant_name}_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return {
        "summary_json": str(summary_path),
        "entry_gate_report_path": str(summary_path),
        "summary": summary,
    }


STRICT_ALPHA_SIDE_MIN_TRADES = 2
STRICT_ALPHA_SIDE_MIN_WINRATE = 0.45
STRICT_ALPHA_SIDE_MIN_EXPECTANCY = 0.0
TOXIC_COST_PAIR_MIN_TRADES = 8
TOXIC_COST_PAIR_MIN_WINRATE = 0.50
TOXIC_COST_PAIR_MAX_EXPECTANCY = -0.003
TOXIC_COST_SIDE_MIN_TRADES = 5
TOXIC_COST_SIDE_MIN_WINRATE = 0.50
TOXIC_COST_SIDE_MAX_EXPECTANCY = -0.003
DEFAULT_ALPHA_BOOTSTRAP_ACCEPTED_SCORECARD = (
    "analysis/zol0_profitability_audit_scorecard.json"
)
EXACT_ALPHA_BOOTSTRAP_EMPTY_SENTINEL = (
    "tmp/__alpha_bootstrap_exact_source_missing__.db"
)
STRICT_BOOTSTRAP_PREBUILT_MANIFEST = (
    "analysis/zol0_profitability_audit_strict_bootstrap_manifest.json"
)


def _narrow_negative_symbols_from_side_evidence(
    negative_symbols: set[str] | None,
    alpha_refresh_report: dict | None,
    active_run_symbols: set[str] | None = None,
) -> set[str]:
    narrowed = {
        str(symbol_name or "").strip().upper()
        for symbol_name in (negative_symbols or set())
        if str(symbol_name or "").strip()
    }
    if not narrowed or not isinstance(alpha_refresh_report, dict):
        return narrowed

    scoped_active_run_symbols = {
        str(symbol_name or "").strip().upper()
        for symbol_name in (active_run_symbols or set())
        if str(symbol_name or "").strip()
    }
    positive_marker_keys = (
        "positive",
        "allow",
        "allowed",
        "pass",
        "is_positive",
        "selected_positive",
        "positive_side",
        "positive_side_evidence",
    )
    released_symbols = set()
    for row in alpha_refresh_report.get("pair_side_stats_top") or []:
        if not isinstance(row, dict):
            continue
        try:
            symbol_name = str(row.get("symbol") or "").strip().upper()
        except Exception:
            symbol_name = ""
        if not symbol_name or symbol_name not in narrowed:
            continue
        if scoped_active_run_symbols and symbol_name not in scoped_active_run_symbols:
            continue
        explicit_positive_marker = any(
            _coerce_bool(row.get(marker_key)) for marker_key in positive_marker_keys
        )
        try:
            expectancy = float(row.get("expectancy") or 0.0)
        except Exception:
            expectancy = 0.0
        if expectancy > 0.0 or explicit_positive_marker:
            released_symbols.add(symbol_name)
    if not released_symbols:
        return narrowed
    return {
        symbol_name
        for symbol_name in narrowed
        if symbol_name not in released_symbols
    }


def _derive_profitability_bucket_gate(
    alpha_refresh_report: dict | None,
    _disable_contract_fallback: bool = False,
    active_run_symbols: set[str] | None = None,
) -> dict:
    if not isinstance(alpha_refresh_report, dict):
        return {
            "overrides": {},
            "positive_side_allowlist": [],
            "toxic_pair_blocklist": [],
            "toxic_side_blocklist": [],
            "cost_burden_side_blocklist": [],
        }

    positive_side_allowlist = set()
    toxic_pair_blocklist = set()
    toxic_side_blocklist = set()
    cost_burden_side_blocklist = set()
    selected_pairs = set()
    explicit_positive_side_fallback_tokens = {
        str(token or "").strip().upper()
        for token in (alpha_refresh_report.get("positive_side_fallback_side_tokens") or [])
        if str(token or "").strip()
    }
    try:
        rows_inserted = int(alpha_refresh_report.get("rows_inserted") or 0)
    except Exception:
        rows_inserted = 0
    scoped_active_run_symbols = {
        str(symbol).strip().upper()
        for symbol in (active_run_symbols or set())
        if str(symbol).strip()
    }
    positive_side_fallback_used = _coerce_bool(
        alpha_refresh_report.get("positive_side_fallback_used")
    )

    for row in alpha_refresh_report.get("pair_stats_top") or []:
        if not isinstance(row, dict):
            continue
        try:
            symbol_name = str(row.get("symbol") or "").strip().upper()
            strategy_name = str(row.get("strategy") or "").strip().upper()
            trade_count = int(row.get("trade_count") or 0)
            expectancy = float(row.get("expectancy") or 0.0)
            winrate = float(row.get("winrate") or 0.0)
        except Exception:
            continue
        if not symbol_name or not strategy_name:
            continue
        if _coerce_bool(row.get("selected")):
            selected_pairs.add(f"{symbol_name}:{strategy_name}")
        if (
            trade_count >= TOXIC_COST_PAIR_MIN_TRADES
            and expectancy <= TOXIC_COST_PAIR_MAX_EXPECTANCY
            and winrate >= TOXIC_COST_PAIR_MIN_WINRATE
        ):
            toxic_pair_blocklist.add(f"{symbol_name}:{strategy_name}")

    valid_side_rows_seen = 0
    for row in alpha_refresh_report.get("pair_side_stats_top") or []:
        if not isinstance(row, dict):
            continue
        try:
            symbol_name = str(row.get("symbol") or "").strip().upper()
            strategy_name = str(row.get("strategy") or "").strip().upper()
            side_name = str(row.get("side") or "").strip().lower()
            trade_count = int(row.get("trade_count") or 0)
            expectancy = float(row.get("expectancy") or 0.0)
            winrate = float(row.get("winrate") or 0.0)
            net_pnl = float(row.get("net_pnl") or 0.0)
            gross_pnl = float(row.get("gross_pnl") or 0.0)
            fee_total = float(row.get("fee_total") or 0.0)
        except Exception:
            continue
        if side_name == "long":
            side_name = "buy"
        elif side_name == "short":
            side_name = "sell"
        if (
            not symbol_name
            or not strategy_name
            or side_name not in ("buy", "sell")
        ):
            continue
        valid_side_rows_seen += 1
        pair_key = f"{symbol_name}:{strategy_name}"
        side_token = f"{symbol_name}:{strategy_name}:{side_name}"
        if (
            not positive_side_fallback_used
            and
            pair_key in selected_pairs
            and
            trade_count >= STRICT_ALPHA_SIDE_MIN_TRADES
            and expectancy > STRICT_ALPHA_SIDE_MIN_EXPECTANCY
            and winrate >= STRICT_ALPHA_SIDE_MIN_WINRATE
        ):
            positive_side_allowlist.add(side_token)
        if (
            positive_side_fallback_used
            and rows_inserted > 0
            and side_token.upper() in explicit_positive_side_fallback_tokens
            and expectancy > STRICT_ALPHA_SIDE_MIN_EXPECTANCY
            and net_pnl > 0.0
            and winrate >= STRICT_ALPHA_SIDE_MIN_WINRATE
        ):
            positive_side_allowlist.add(side_token)
        if (
            trade_count >= TOXIC_COST_SIDE_MIN_TRADES
            and expectancy <= TOXIC_COST_SIDE_MAX_EXPECTANCY
            and winrate >= TOXIC_COST_SIDE_MIN_WINRATE
        ):
            toxic_side_blocklist.add(f"{symbol_name}:{strategy_name}:{side_name}")
        if (
            trade_count >= TOXIC_COST_SIDE_MIN_TRADES
            and net_pnl < 0.0
            and fee_total > max(gross_pnl, 0.0)
        ):
            cost_burden_side_blocklist.add(
                f"{symbol_name}:{strategy_name}:{side_name}"
            )

    overrides = {}
    if (
        not positive_side_allowlist
        and not _disable_contract_fallback
        and valid_side_rows_seen <= 0
    ):
        # Fallback: when live bootstrap data yields no positive pairs (e.g.,
        # no usable side rows are available), load the
        # pre-computed allowlist from the verified positive-side contract file.
        _contract_path = (
            WORKDIR / "analysis" / "zol0_positive_side_allowlist_contract_current.json"
        )
        try:
            if _contract_path.exists():
                _contract = json.loads(_contract_path.read_text())
                if _contract.get("status") == "PASS":
                    for _token in (_contract.get("positive_side_allowlist") or []):
                        _t = str(_token).strip()
                        if not _t:
                            continue
                        if scoped_active_run_symbols:
                            _symbol = _t.split(":", 1)[0].strip().upper()
                            if _symbol not in scoped_active_run_symbols:
                                continue
                        if _t:
                            positive_side_allowlist.add(_t)
        except Exception:
            pass
    expanded_allowlist = set(positive_side_allowlist)
    allow_upper = set()
    if positive_side_allowlist:
        # The runtime alpha whitelist is pair-level and can suppress a positive
        # side bucket inside a mixed pair. Use the explicit side-bucket gate for
        # PAPER validation when bootstrap history is strong enough to support it.
        overrides["ALPHA_WHITELIST_ENABLE"] = "0"
        overrides["ALPHA_WHITELIST_COLDSTART_ALLOW"] = "0"
        overrides["ALPHA_WHITELIST_FALLBACK_ENABLE"] = "0"
        # Expand allowlist: also permit Universal:sell for any allowlisted
        # sell-side symbol so that Universal signals (which fire when
        # bootstrapped TF/Momentum are in hold/exit regime) can contribute.
        side_block_candidates_upper = {
            str(token).strip().upper()
            for token in (toxic_side_blocklist | cost_burden_side_blocklist)
            if str(token).strip()
        }
        for token in list(positive_side_allowlist):
            sym = token.split(":")[0]
            if token.lower().endswith(":sell"):
                universal_sell = f"{sym}:UNIVERSAL:sell"
                # Never add expanded allowlist tokens that are already known
                # toxic/cost-burden side blocks; avoid admission conflict.
                if universal_sell.upper() not in side_block_candidates_upper:
                    expanded_allowlist.add(universal_sell)
        allow_upper = {t.upper() for t in expanded_allowlist}
        overrides["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] = ",".join(
            sorted(expanded_allowlist)
        )
        overrides["ENTRY_SYMBOL_STRATEGY_BLOCKLIST"] = ",".join(
            sorted(toxic_pair_blocklist)
        )
        # Bootstrap-validated allowlist acts as the history gate; bypass the
        # runtime "seed_only" cold-start block so allowlisted sides can trade.
        overrides["ENTRY_EDGE_COLDSTART_MODE"] = "fail_open"
        # Prevent the fallback-mode logic from adding broad symbol/strategy-side
        # blocklists that fire BEFORE BotCore reaches the allowlist check.
        # Setting these to "" here wins the setdefault race against the fallback.
        overrides["ENTRY_SYMBOL_BLOCKLIST"] = ""
        overrides["ENTRY_STRATEGY_SIDE_BLOCKLIST"] = ""
    side_blocklist = sorted(toxic_side_blocklist | cost_burden_side_blocklist)
    if positive_side_allowlist:
        # Remove any token that is also in the allowlist to avoid
        # ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT in the admission contract.
        side_blocklist = [t for t in side_blocklist if t.upper() not in allow_upper]
        # Pre-empt the fallback-mode setdefault race: always set the blocklist
        # key (possibly empty) so the fallback cannot add conflicting tokens.
        overrides["ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST"] = ",".join(side_blocklist)
    # When no strict positive-side allowlist exists, avoid injecting
    # symbol-strategy-side hard blocks from bootstrap side stats alone.
    # This keeps the admission path open for natural candidate discovery.
    return {
        "overrides": overrides,
        "positive_side_allowlist": sorted(positive_side_allowlist),
        "toxic_pair_blocklist": sorted(toxic_pair_blocklist),
        "toxic_side_blocklist": sorted(toxic_side_blocklist),
        "cost_burden_side_blocklist": sorted(cost_burden_side_blocklist),
    }


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest().upper()
    except Exception:
        return None


def _load_alpha_bootstrap_prebuilt_manifest(
    manifest_rel: str,
    expected_run_ids: list[str] | None,
) -> dict:
    manifest = {
        "path": None,
        "valid": False,
        "source_scorecard_path": None,
        "db_path": None,
        "report_path": None,
        "rows_inserted": 0,
        "reason_codes": [],
    }
    manifest_txt = str(manifest_rel or "").strip()
    if not manifest_txt:
        manifest["reason_codes"].append("manifest_path_missing")
        return manifest

    manifest_path = (WORKDIR / manifest_txt).resolve()
    manifest["path"] = str(manifest_path)
    if not manifest_path.exists():
        manifest["reason_codes"].append("manifest_missing")
        return manifest

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest["reason_codes"].append("manifest_unreadable")
        return manifest
    if not isinstance(payload, dict):
        manifest["reason_codes"].append("manifest_malformed")
        return manifest

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        manifest["reason_codes"].append("manifest_metadata_malformed")
        metadata = {}
    scope = metadata.get("scope") or {}
    if not isinstance(scope, dict):
        manifest["reason_codes"].append("manifest_scope_malformed")
        scope = {}
    if str(scope.get("exchange") or "").strip().lower() != "kucoin":
        manifest["reason_codes"].append("manifest_scope_exchange_invalid")
    if str(scope.get("mode") or "").strip().upper() != "PAPER_ONLY":
        manifest["reason_codes"].append("manifest_scope_mode_invalid")
    if str(scope.get("variant") or "").strip().lower() != "after":
        manifest["reason_codes"].append("manifest_scope_variant_invalid")
    if _coerce_bool(scope.get("live_in_scope")):
        manifest["reason_codes"].append("manifest_scope_live_invalid")

    selection = payload.get("selection") or {}
    if not isinstance(selection, dict):
        manifest["reason_codes"].append("manifest_selection_malformed")
        selection = {}
    manifest_run_ids = [
        str(run_id).strip()
        for run_id in (selection.get("accepted_run_ids") or [])
        if str(run_id).strip()
    ]
    if len(manifest_run_ids) != len(set(manifest_run_ids)):
        manifest["reason_codes"].append("manifest_accepted_run_ids_duplicate")
    expected_ids = [
        str(run_id).strip()
        for run_id in (expected_run_ids or [])
        if str(run_id).strip()
    ]
    if expected_ids and manifest_run_ids != expected_ids:
        manifest["reason_codes"].append("manifest_accepted_run_ids_mismatch")

    source = payload.get("prebuilt_source") or {}
    if not isinstance(source, dict):
        manifest["reason_codes"].append("manifest_prebuilt_source_malformed")
        source = {}
    source_scorecard_txt = str(source.get("source_scorecard_path") or "").strip()
    if source_scorecard_txt:
        source_scorecard_path = (WORKDIR / source_scorecard_txt).resolve()
        manifest["source_scorecard_path"] = str(source_scorecard_path)

    db_txt = str(source.get("db_path") or "").strip()
    if not db_txt:
        manifest["reason_codes"].append("manifest_db_path_missing")
        return manifest
    db_path = (WORKDIR / db_txt).resolve()
    manifest["db_path"] = str(db_path)
    if not db_path.exists():
        manifest["reason_codes"].append("manifest_db_missing")
        return manifest
    if _path_is_within(db_path, TMP_DIR):
        manifest["reason_codes"].append("manifest_db_tmp_forbidden")
    if not _path_is_within(db_path, DIAGNOSTICS_DIR):
        manifest["reason_codes"].append("manifest_db_outside_diagnostics")
    try:
        db_size_bytes = int(db_path.stat().st_size)
    except Exception:
        db_size_bytes = 0
    if db_size_bytes <= 0:
        manifest["reason_codes"].append("manifest_db_zero_or_empty")
    expected_db_size = int(source.get("db_size_bytes") or 0)
    if expected_db_size > 0 and db_size_bytes != expected_db_size:
        manifest["reason_codes"].append("manifest_db_size_mismatch")
    expected_db_sha = str(source.get("db_sha256") or "").strip().upper()
    if expected_db_sha:
        actual_db_sha = _sha256_file(db_path)
        if not actual_db_sha or actual_db_sha != expected_db_sha:
            manifest["reason_codes"].append("manifest_db_sha_mismatch")

    report_txt = str(source.get("report_path") or "").strip()
    if not report_txt:
        manifest["reason_codes"].append("manifest_report_path_missing")
        return manifest
    report_path = (WORKDIR / report_txt).resolve()
    manifest["report_path"] = str(report_path)
    if not report_path.exists():
        manifest["reason_codes"].append("manifest_report_missing")
        return manifest
    if _path_is_within(report_path, TMP_DIR):
        manifest["reason_codes"].append("manifest_report_tmp_forbidden")
    if not _path_is_within(report_path, DIAGNOSTICS_DIR):
        manifest["reason_codes"].append("manifest_report_outside_diagnostics")
    try:
        report_size_bytes = int(report_path.stat().st_size)
    except Exception:
        report_size_bytes = 0
    if report_size_bytes <= 0:
        manifest["reason_codes"].append("manifest_report_zero_or_empty")
    expected_report_size = int(source.get("report_size_bytes") or 0)
    if expected_report_size > 0 and report_size_bytes != expected_report_size:
        manifest["reason_codes"].append("manifest_report_size_mismatch")
    expected_report_sha = str(source.get("report_sha256") or "").strip().upper()
    if expected_report_sha:
        actual_report_sha = _sha256_file(report_path)
        if not actual_report_sha or actual_report_sha != expected_report_sha:
            manifest["reason_codes"].append("manifest_report_sha_mismatch")

    report_payload = {}
    try:
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        manifest["reason_codes"].append("manifest_report_unreadable")
    rows_inserted = 0
    if report_payload:
        try:
            rows_inserted = int(report_payload.get("rows_inserted") or 0)
        except Exception:
            rows_inserted = 0
        report_output_txt = str(report_payload.get("output") or "").strip()
        if report_output_txt:
            try:
                report_output_path = Path(report_output_txt).resolve()
            except Exception:
                report_output_path = None
            if report_output_path is None or report_output_path != db_path:
                manifest["reason_codes"].append("manifest_report_output_mismatch")
    if rows_inserted <= 0:
        manifest["reason_codes"].append("manifest_rows_inserted_zero")
    manifest["rows_inserted"] = rows_inserted
    expected_rows_inserted = int(source.get("rows_inserted") or 0)
    if expected_rows_inserted > 0 and rows_inserted != expected_rows_inserted:
        manifest["reason_codes"].append("manifest_rows_inserted_mismatch")

    manifest["valid"] = not bool(manifest["reason_codes"])
    return manifest


def _resolve_alpha_bootstrap_exact_source_contract(scorecard_rel: str) -> dict:
    contract = {
        "active": False,
        "scorecard_path": None,
        "resolved_scorecard_path": None,
        "prebuilt_manifest_path": None,
        "accepted_run_ids": [],
        "exact_after_db_patterns": [],
        "existing_run_ids": [],
        "missing_run_ids": [],
        "nonzero_run_ids": [],
        "source_mode": "accepted_after_run_dbs",
        "prebuilt_alpha_history_db_path": None,
        "prebuilt_alpha_history_report_path": None,
        "prebuilt_alpha_history_rows_inserted": 0,
        "reason_codes": [],
    }
    scorecard_txt = str(scorecard_rel or "").strip()
    if not scorecard_txt:
        return contract

    contract["active"] = True
    scorecard_path = (WORKDIR / scorecard_txt).resolve()
    contract["scorecard_path"] = str(scorecard_path)
    contract["resolved_scorecard_path"] = str(scorecard_path)
    if not scorecard_path.exists():
        contract["reason_codes"].append("scorecard_missing")
        return contract

    try:
        payload = json.loads(scorecard_path.read_text(encoding="utf-8"))
    except Exception:
        contract["reason_codes"].append("scorecard_unreadable")
        return contract

    def _scorecard_prebuilt_source(
        scorecard_payload: dict | None,
    ) -> tuple[str | None, str | None, int]:
        if not isinstance(scorecard_payload, dict):
            return None, None, 0
        sources = ((scorecard_payload.get("metadata") or {}).get("sources") or {})
        db_txt = str(sources.get("alpha_history_db_path") or "").strip()
        report_txt = str(sources.get("bootstrap_report_path") or "").strip()
        db_path = (WORKDIR / db_txt).resolve() if db_txt else None
        report_path = (WORKDIR / report_txt).resolve() if report_txt else None
        if not db_path or not db_path.exists() or db_path.stat().st_size <= 0:
            return None, None, 0
        if _path_is_within(db_path, TMP_DIR):
            return None, None, 0
        if report_path is not None and _path_is_within(report_path, TMP_DIR):
            return None, None, 0
        rows_inserted = 0
        if report_path and report_path.exists():
            try:
                report_text = report_path.read_text(encoding="utf-8")
                report_payload = json.loads(report_text)
                rows_inserted = int(report_payload.get("rows_inserted") or 0)
            except Exception:
                rows_inserted = 0
        report_path_txt = (
            str(report_path) if report_path and report_path.exists() else None
        )
        return str(db_path), report_path_txt, rows_inserted

    selection = ((payload.get("metadata") or {}).get("selection") or {})
    accepted_run_ids = [
        str(run_id).strip()
        for run_id in (selection.get("accepted_run_ids") or [])
        if str(run_id).strip()
    ]
    contract["accepted_run_ids"] = accepted_run_ids
    if not accepted_run_ids:
        contract["reason_codes"].append("accepted_run_ids_missing")
        return contract

    for run_id in accepted_run_ids:
        rel = f"tmp/controlled_kpi_after_{run_id}.db"
        path = (WORKDIR / rel).resolve()
        contract["exact_after_db_patterns"].append(rel)
        if path.exists():
            contract["existing_run_ids"].append(run_id)
            if path.stat().st_size > 0:
                contract["nonzero_run_ids"].append(run_id)
        else:
            contract["missing_run_ids"].append(run_id)

    if contract["missing_run_ids"]:
        contract["reason_codes"].append("accepted_after_db_missing")
    if len(contract["nonzero_run_ids"]) < len(contract["accepted_run_ids"]):
        contract["reason_codes"].append("accepted_after_db_zero_or_empty")

    prebuilt_db_path, prebuilt_report_path, prebuilt_rows_inserted = (
        _scorecard_prebuilt_source(payload)
    )
    if prebuilt_db_path and prebuilt_rows_inserted > 0:
        contract["source_mode"] = "prebuilt_alpha_history_db"
        contract["prebuilt_alpha_history_db_path"] = prebuilt_db_path
        contract["prebuilt_alpha_history_report_path"] = prebuilt_report_path
        contract["prebuilt_alpha_history_rows_inserted"] = prebuilt_rows_inserted
        contract["reason_codes"] = []
        return contract

    prebuilt_manifest = _load_alpha_bootstrap_prebuilt_manifest(
        STRICT_BOOTSTRAP_PREBUILT_MANIFEST,
        contract["accepted_run_ids"],
    )
    contract["prebuilt_manifest_path"] = prebuilt_manifest.get("path")
    if (
        "accepted_after_db_zero_or_empty" in contract["reason_codes"]
        and prebuilt_manifest.get("valid")
    ):
        if prebuilt_manifest.get("source_scorecard_path"):
            contract["resolved_scorecard_path"] = str(
                prebuilt_manifest.get("source_scorecard_path")
            )
        contract["source_mode"] = "prebuilt_alpha_history_manifest"
        contract["prebuilt_alpha_history_db_path"] = prebuilt_manifest.get("db_path")
        contract["prebuilt_alpha_history_report_path"] = prebuilt_manifest.get(
            "report_path"
        )
        contract["prebuilt_alpha_history_rows_inserted"] = int(
            prebuilt_manifest.get("rows_inserted") or 0
        )
        contract["reason_codes"] = []
        return contract
    for code in prebuilt_manifest.get("reason_codes") or []:
        if code not in contract["reason_codes"]:
            contract["reason_codes"].append(code)
    return contract


def _finalize_alpha_bootstrap_refresh_contract(alpha_refresh: dict | None) -> dict:
    refresh = dict(alpha_refresh or {})
    report = refresh.get("report") if isinstance(refresh.get("report"), dict) else {}
    exact = (
        refresh.get("exact_source_contract")
        if isinstance(refresh.get("exact_source_contract"), dict)
        else {}
    )
    reason_codes = list(exact.get("reason_codes") or [])
    status = "PASS"
    allow_seed_only_refresh_gap = False

    if not _coerce_bool(refresh.get("ran")):
        status = "FAIL"
        if "refresh_not_run" not in reason_codes:
            reason_codes.append("refresh_not_run")
    elif not _coerce_bool(refresh.get("output_exists")):
        status = "FAIL"
        if "refresh_output_missing" not in reason_codes:
            reason_codes.append("refresh_output_missing")
    elif int(refresh.get("returncode") or 0) != 0:
        status = "FAIL"
        if "refresh_returncode_nonzero" not in reason_codes:
            reason_codes.append("refresh_returncode_nonzero")

    if _coerce_bool(exact.get("active")):
        rows_inserted = int(report.get("rows_inserted") or 0)
        source_mode = str(exact.get("source_mode") or "").strip().lower()
        prebuilt_seed_rows = int(exact.get("prebuilt_alpha_history_rows_inserted") or 0)
        allow_seed_only_refresh_gap = bool(
            source_mode
            in {"prebuilt_alpha_history_db", "prebuilt_alpha_history_manifest"}
            and prebuilt_seed_rows > 0
        )
        if rows_inserted <= 0:
            if "external_rows_inserted_zero" not in reason_codes:
                reason_codes.append("external_rows_inserted_zero")
            if status == "PASS" and not allow_seed_only_refresh_gap:
                status = "UNCONFIRMED"
        if reason_codes and status == "PASS":
            if not (
                allow_seed_only_refresh_gap
                and set(reason_codes) == {"external_rows_inserted_zero"}
            ):
                status = "UNCONFIRMED"

    refresh["status"] = status
    refresh["reason_codes"] = reason_codes
    refresh["success"] = bool(status == "PASS")
    if exact:
        exact["status"] = status
        exact["reason_codes"] = reason_codes
        refresh["exact_source_contract"] = exact
    return refresh


def _derive_alpha_bootstrap_runtime_contract(alpha_refresh: dict | None) -> dict:
    refresh = dict(alpha_refresh or {})
    exact = (
        refresh.get("exact_source_contract")
        if isinstance(refresh.get("exact_source_contract"), dict)
        else {}
    )
    source_fail_closed = _coerce_bool(refresh.get("source_fail_closed"))
    status = "FAIL_CLOSED" if source_fail_closed else "PASS"
    reason_codes = []
    if source_fail_closed:
        reason_codes.append("source_fail_closed")
    for code in refresh.get("reason_codes") or []:
        txt = str(code or "").strip()
        if txt and txt not in reason_codes:
            reason_codes.append(txt)
    return {
        "status": status,
        "active": _coerce_bool(exact.get("active")),
        "source_fail_closed": source_fail_closed,
        "refresh_status": str(refresh.get("status") or ""),
        "reason_codes": reason_codes,
    }


def _split_csv_tokens(value) -> list[str]:
    tokens = []
    seen = set()
    for part in str(value or "").split(","):
        token = str(part or "").strip()
        if not token or token in seen:
            continue
        tokens.append(token)
        seen.add(token)
    return tokens


def _canonical_symbol_strategy_side_token(value: str) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    if ":" in token:
        parts = [part.strip() for part in token.split(":")]
    elif "|" in token:
        parts = [part.strip() for part in token.split("|")]
    else:
        return None
    if len(parts) < 3:
        return None
    symbol_key = str(parts[0] or "").strip().upper()
    strategy_key = str(parts[1] or "").strip().upper()
    side_key = str(parts[2] or "").strip().lower()
    if side_key == "long":
        side_key = "buy"
    elif side_key == "short":
        side_key = "sell"
    if not symbol_key or not strategy_key or side_key not in {"buy", "sell"}:
        return None
    return f"{symbol_key}:{strategy_key}:{side_key}"


def _canonical_symbol_strategy_pair_token(value: str) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    if ":" in token:
        parts = [part.strip() for part in token.split(":")]
    elif "|" in token:
        parts = [part.strip() for part in token.split("|")]
    else:
        return None
    if len(parts) < 2:
        return None
    symbol_key = str(parts[0] or "").strip().upper()
    strategy_key = str(parts[1] or "").strip().upper()
    if not symbol_key or not strategy_key:
        return None
    return f"{symbol_key}:{strategy_key}"


def _derive_positive_side_allowlist_contract(
    strict_bucket_gate: dict | None,
) -> dict:
    gate = strict_bucket_gate if isinstance(strict_bucket_gate, dict) else {}
    allowlist = [
        str(item).strip()
        for item in (gate.get("positive_side_allowlist") or [])
        if str(item).strip()
    ]
    reason_codes = []
    status = "PASS" if allowlist else "FAIL_CLOSED"
    if allowlist:
        reason_codes.append("POSITIVE_SIDE_ALLOWLIST_PRESENT")
    else:
        reason_codes.extend(
            [
                "NO_ELIGIBLE_POSITIVE_SIDE_BUCKETS",
                "STRICT_POSITIVE_SIDE_ALLOWLIST_EMPTY",
            ]
        )
    return {
        "status": status,
        "positive_side_allowlist": allowlist,
        "reason_codes": reason_codes,
        "source": "strict_profitability_bucket_gate",
    }


def _load_positive_side_allowlist_contract(path_text: str) -> dict:
    path = Path(str(path_text or "")).resolve()
    result = {
        "status": "MISSING",
        "positive_side_allowlist": [],
        "reason_codes": ["contract_missing"],
        "path": str(path),
    }
    if not str(path_text or "").strip() or not path.exists():
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        result["status"] = "MALFORMED"
        result["reason_codes"] = ["contract_malformed"]
        return result
    if not isinstance(payload, dict) or not isinstance(
        payload.get("positive_side_allowlist"),
        list,
    ):
        result["status"] = "MALFORMED"
        result["reason_codes"] = ["contract_malformed"]
        return result
    allowlist = [
        str(item).strip()
        for item in (payload.get("positive_side_allowlist") or [])
        if str(item).strip()
    ]
    result.update(
        {
            "status": str(payload.get("status") or "UNKNOWN").strip() or "UNKNOWN",
            "positive_side_allowlist": allowlist,
            "reason_codes": [
                str(code).strip()
                for code in (payload.get("reason_codes") or [])
                if str(code).strip()
            ],
        }
    )
    return result


def _apply_positive_side_allowlist_contract(
    *,
    after_overrides: dict,
    after_overrides_cli: dict,
    contract: dict,
) -> dict:
    status = str((contract or {}).get("status") or "").strip().upper()
    allowlist = [
        str(item).strip()
        for item in ((contract or {}).get("positive_side_allowlist") or [])
        if str(item).strip()
    ]
    result = {
        "allowlist_applied": False,
        "allowlist_skipped": [],
        "positive_side_allowlist": allowlist,
        "reason_codes": list((contract or {}).get("reason_codes") or []),
    }
    if status != "PASS" or not allowlist:
        result["allowlist_skipped"].append("contract_not_pass_or_empty")
        return result
    if "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST" in after_overrides_cli:
        result["allowlist_skipped"].append("cli_side_allowlist_override_present")
        return result

    after_overrides["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] = ",".join(allowlist)
    for key in (
        "ALPHA_WHITELIST_ENABLE",
        "ALPHA_WHITELIST_COLDSTART_ALLOW",
        "ALPHA_WHITELIST_FALLBACK_ENABLE",
    ):
        if key not in after_overrides_cli:
            after_overrides[key] = "0"
    result["allowlist_applied"] = True
    return result


def _resolve_regime_deadlock_expansion(
    after_overrides: dict,
    after_overrides_cli: dict,
    strategy_side_stats: dict,
    positive_side_fallback_used: bool,
    active_run_symbols: set,
) -> None:
    """Detect TF-only strategy allowlist + positive_side_fallback regime deadlock.

    When ENTRY_STRATEGY_ALLOWLIST is TF-only and positive_side_fallback is
    active, TrendFollowing cannot generate buy signals in a bearish regime
    (requires EMA crossover in uptrend). Expands the allowlist with
    regime-compatible strategies found in strategy_side_stats if they pass
    minimum quality thresholds.

    Mutates ``after_overrides`` and ``after_overrides_cli`` in place.
    """
    _REGIME_COMPAT_PRIORITY = ["MeanReversion", "Universal", "Momentum"]
    _MIN_TC = 2
    _MIN_EXP = -0.01
    _MIN_WR = 0.30

    allowlist_raw = str(after_overrides.get("ENTRY_STRATEGY_ALLOWLIST", ""))
    current_allowlist = [s.strip() for s in allowlist_raw.split(",") if s.strip()]
    only_tf = bool(
        current_allowlist
        and all(str(s).upper() == "TRENDFOLLOWING" for s in current_allowlist)
    )
    if not (only_tf and positive_side_fallback_used):
        return

    candidates = []
    for rname in _REGIME_COMPAT_PRIORITY:
        bucket = (strategy_side_stats or {}).get(f"{rname}:buy") or {}
        rtc = int(bucket.get("trade_count") or 0)
        if rtc < _MIN_TC:
            continue
        rnet = float(bucket.get("net_pnl") or 0.0)
        rwins = float(bucket.get("wins_weighted") or 0.0)
        rexp = (rnet / rtc) if rtc > 0 else 0.0
        rwr = (rwins / rtc) if rtc > 0 else 0.0
        if rexp >= _MIN_EXP and rwr >= _MIN_WR:
            candidates.append(rname)

    if candidates:
        new_allowlist = sorted(set(current_allowlist) | set(candidates))
        after_overrides["ENTRY_STRATEGY_ALLOWLIST"] = ",".join(new_allowlist)
        after_overrides_cli.pop("ENTRY_STRATEGY_ALLOWLIST", None)
        print(
            "ALLOWLIST_REGIME_DEADLOCK_BREAK: expanded ENTRY_STRATEGY_ALLOWLIST "
            f"from={current_allowlist} to={new_allowlist} "
            f"regime_compat_added={candidates}"
        )
        # Also expand ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST if TF-only tokens
        side_tokens = [
            t.strip()
            for t in str(
                after_overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", "")
            ).split(",")
            if t.strip()
        ]
        if side_tokens and all(
            ":TRENDFOLLOWING:" in t.upper() for t in side_tokens
        ):
            side_new = list(side_tokens)
            for sname in candidates:
                for sym in sorted(active_run_symbols or set()):
                    side_new.append(f"{sym}:{sname}:buy")
            after_overrides["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] = ",".join(
                sorted(set(side_new))
            )
            after_overrides_cli.pop("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", None)
            print(
                "ALLOWLIST_REGIME_DEADLOCK_BREAK: expanded "
                "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST "
                f"regime_compat_added={candidates}"
            )
    else:
        print(
            "ALLOWLIST_REGIME_DEADLOCK_DETECTED: TF-only allowlist with "
            "positive_side_fallback_used=True but no regime-compatible buy "
            "strategy found in strategy_side_stats. "
            "allowlist_regime_deadlock_detected=True"
        )


def _derive_entry_admission_contract(
    *,
    variant_only: str,
    paper_auto_open: bool,
    after_overrides: dict,
    alpha_bootstrap_runtime_contract: dict,
    strict_bucket_gate: dict,
    symbols: list[str] | None = None,
) -> dict:
    variant_txt = str(variant_only or "").strip().lower()
    after_requested = variant_txt in {"after", "both"}
    explicit_side_allowlist = _split_csv_tokens(
        (after_overrides or {}).get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST")
    )
    explicit_side_blocklist = _split_csv_tokens(
        (after_overrides or {}).get("ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST")
    )
    positive_side_allowlist = [
        str(item).strip()
        for item in ((strict_bucket_gate or {}).get("positive_side_allowlist") or [])
        if str(item).strip()
    ]

    allow_side_tokens = set()
    for token in explicit_side_allowlist:
        canonical = _canonical_symbol_strategy_side_token(token)
        if canonical:
            allow_side_tokens.add(canonical)
    for token in positive_side_allowlist:
        canonical = _canonical_symbol_strategy_side_token(token)
        if canonical:
            allow_side_tokens.add(canonical)

    allowlist_contract_type = "none"
    allowlist_scope_tokens = []
    if explicit_side_allowlist:
        allowlist_contract_type = "explicit_side_allowlist"
        allowlist_scope_tokens = list(explicit_side_allowlist)
    elif positive_side_allowlist:
        allowlist_contract_type = "strict_positive_side_allowlist"
        allowlist_scope_tokens = list(positive_side_allowlist)

    allowlist_side_coverage = set()
    for token in allowlist_scope_tokens:
        canonical = _canonical_symbol_strategy_side_token(token)
        if not canonical:
            continue
        try:
            _, _, side_key = canonical.split(":", 2)
        except Exception:
            continue
        if side_key in {"buy", "sell"}:
            allowlist_side_coverage.add(side_key)
    one_sided_allowlist_detected = bool(
        allowlist_scope_tokens and len(allowlist_side_coverage) == 1
    )

    active_symbols = {
        str(symbol or "").strip().upper()
        for symbol in (symbols or [])
        if str(symbol or "").strip()
    }
    symbol_scope_count = len(active_symbols)
    symbol_scope_type = (
        "single_symbol"
        if symbol_scope_count == 1
        else "narrow_symbol_corridor"
        if symbol_scope_count == 2
        else "multi_symbol"
    )

    block_side_tokens = set()
    for token in explicit_side_blocklist:
        canonical = _canonical_symbol_strategy_side_token(token)
        if canonical:
            block_side_tokens.add(canonical)

    conflicting_side_tokens = sorted(allow_side_tokens & block_side_tokens)

    require_explicit = str(
        (after_overrides or {}).get(
            "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST",
            "1",
        )
    ).strip() not in {"0", "false", "False", "no", "NO"}
    bootstrap_status = str(
        (alpha_bootstrap_runtime_contract or {}).get("status") or ""
    ).strip().upper()

    reason_codes = []
    status = "PASS"
    validation_classification = "PAPER_VALIDATION_CANDIDATE"
    invalid_reason = None
    allow_one_sided_validation = _coerce_bool(
        (after_overrides or {}).get("ALLOW_ONE_SIDED_VALIDATION"),
        default=True,
    )
    if not after_requested:
        reason_codes.append("AFTER_VARIANT_NOT_REQUESTED")
        validation_classification = "NOT_AFTER_VALIDATION"
    elif not bool(paper_auto_open):
        reason_codes.extend(["DIAGNOSTIC_NO_OPEN_RUN", "PAPER_AUTO_OPEN_DISABLED"])
        validation_classification = "DIAGNOSTIC_NO_OPEN_RUN"
    elif explicit_side_allowlist:
        reason_codes.append("EXPLICIT_SIDE_ALLOWLIST_PRESENT")
    elif positive_side_allowlist:
        reason_codes.append("STRICT_POSITIVE_SIDE_ALLOWLIST_PRESENT")
    elif require_explicit:
        status = "FAIL_CLOSED"
        reason_codes.extend(
            [
                "NO_ELIGIBLE_ENTRY_BUCKETS",
                "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_EMPTY",
                "STRICT_POSITIVE_SIDE_ALLOWLIST_EMPTY",
                "PAPER_AUTO_OPEN_EXPLICIT_SIDE_ALLOWLIST_REQUIRED",
            ]
        )
        validation_classification = "NO_ELIGIBLE_POSITIVE_ENTRY_BUCKETS"

    if conflicting_side_tokens:
        status = "FAIL_CLOSED"
        validation_classification = "ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT"
        if "ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT" not in reason_codes:
            reason_codes.append("ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT")

    if bootstrap_status == "FAIL_CLOSED":
        if "ALPHA_BOOTSTRAP_RUNTIME_FAIL_CLOSED" not in reason_codes:
            reason_codes.append("ALPHA_BOOTSTRAP_RUNTIME_FAIL_CLOSED")
        if bool(paper_auto_open) and after_requested and not (
            explicit_side_allowlist or positive_side_allowlist
        ):
            status = "FAIL_CLOSED"
            validation_classification = "NO_ELIGIBLE_POSITIVE_ENTRY_BUCKETS"

    throughput_collapse_risk = bool(
        after_requested
        and bool(paper_auto_open)
        and symbol_scope_count in {1, 2}
        and one_sided_allowlist_detected
    )
    if throughput_collapse_risk:
        if allow_one_sided_validation:
            invalid_reason = "ONE_SIDED_ALLOWLIST_DIAGNOSTIC_OPT_IN"
            if "ONE_SIDED_ALLOWLIST_DIAGNOSTIC_OPT_IN" not in reason_codes:
                reason_codes.append("ONE_SIDED_ALLOWLIST_DIAGNOSTIC_OPT_IN")
            if (
                "PROFIT_VALIDATION_CORPUS_INVALID_ONE_SIDED_ALLOWLIST"
                not in reason_codes
            ):
                reason_codes.append(
                    "PROFIT_VALIDATION_CORPUS_INVALID_ONE_SIDED_ALLOWLIST"
                )
        else:
            status = "FAIL_CLOSED"
            validation_classification = (
                "INVALID_PROFIT_VALIDATION_CORPUS_ONE_SIDED_ALLOWLIST"
            )
            invalid_reason = "ONE_SIDED_ALLOWLIST_THROUGHPUT_COLLAPSE_RISK"
            if "ONE_SIDED_ALLOWLIST_THROUGHPUT_COLLAPSE_RISK" not in reason_codes:
                reason_codes.append("ONE_SIDED_ALLOWLIST_THROUGHPUT_COLLAPSE_RISK")
            if (
                "PROFIT_VALIDATION_CORPUS_INVALID_ONE_SIDED_ALLOWLIST"
                not in reason_codes
            ):
                reason_codes.append(
                    "PROFIT_VALIDATION_CORPUS_INVALID_ONE_SIDED_ALLOWLIST"
                )

    profit_valid = bool(
        status == "PASS"
        and after_requested
        and bool(paper_auto_open)
        and not bool(invalid_reason)
    )

    return {
        "status": status,
        "validation_classification": validation_classification,
        "reason_codes": reason_codes,
        "variant_only": variant_txt,
        "after_requested": bool(after_requested),
        "paper_auto_open": bool(paper_auto_open),
        "require_explicit_side_allowlist": bool(require_explicit),
        "explicit_side_allowlist": explicit_side_allowlist,
        "explicit_side_blocklist": explicit_side_blocklist,
        "positive_side_allowlist": positive_side_allowlist,
        "conflicting_side_tokens": conflicting_side_tokens,
        "alpha_bootstrap_runtime_status": bootstrap_status,
        "profit_valid": bool(profit_valid),
        "invalid_reason": str(invalid_reason or ""),
        "allowlist_contract_type": allowlist_contract_type,
        "one_sided_allowlist_detected": bool(one_sided_allowlist_detected),
        "allowlist_side_coverage": sorted(allowlist_side_coverage),
        "allow_one_sided_validation": bool(allow_one_sided_validation),
        "symbol_scope_count": int(symbol_scope_count),
        "symbol_scope_type": symbol_scope_type,
    }


def _write_entry_admission_contract_artifact(
    *,
    run_id: str,
    contract: dict,
) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DIAGNOSTICS_DIR / f"entry_admission_contract_{run_id}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "contract": contract,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return out_path


def _analyze_process_logs(out_log: Path, err_log: Path) -> dict:
    error_patterns = [
        "traceback",
        "exception",
        "error",
        "critical",
        "panic_exit",
        "no such table",
        "queuepool",
    ]
    warning_patterns = ["warning", "warn"]
    error_count = 0
    warning_count = 0
    matched_error_lines = []

    for path in (out_log, err_log):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    lower = line.lower()
                    is_error = any(p in lower for p in error_patterns)
                    is_warning = any(p in lower for p in warning_patterns)
                    if is_error:
                        error_count += 1
                        if len(matched_error_lines) < 20:
                            matched_error_lines.append(line[:350])
                    elif is_warning:
                        warning_count += 1
        except Exception:
            continue

    return {
        "error_count": error_count,
        "warning_count": warning_count,
        "sample_errors": matched_error_lines,
    }


def _sqlite_enqueue_window_sentinel_path(db_path: Path) -> Path:
    return db_path.with_name(f"{db_path.name}.enqueue_window.flag")


def _arm_sqlite_enqueue_window_sentinel(db_path: Path) -> Path:
    sentinel_path = _sqlite_enqueue_window_sentinel_path(db_path)
    sentinel_path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return sentinel_path


def _clear_sqlite_enqueue_window_sentinel(db_path: Path) -> Path:
    sentinel_path = _sqlite_enqueue_window_sentinel_path(db_path)
    try:
        sentinel_path.unlink()
    except FileNotFoundError:
        pass
    return sentinel_path


def _run_data_integrity_checks(
        symbols,
        market_type: str,
        use_mock: bool,
        timeframe: str):
    if use_mock:
        return {
            "skipped": True,
            "reason": "USE_MOCK=1",
            "symbols": symbols,
            "results": {},
        }

    from core.MarketDataFetcher import MarketDataFetcher

    fetcher = MarketDataFetcher(market_type=market_type)
    now_ms = int(time.time() * 1000)
    results = {}
    for symbol in symbols:
        try:
            candles = fetcher.get_ohlcv(symbol, timeframe, limit=120)
        except Exception as exc:
            results[symbol] = {
                "ok": False,
                "error": str(exc),
                "count": 0,
            }
            continue

        count = len(candles or [])
        ts_list = []
        bad_ohlc_count = 0
        bad_volume_count = 0

        for c in candles or []:
            ts = c.get("timestamp")
            try:
                ts_f = float(ts)
                if ts_f < 10_000_000_000:
                    ts_f *= 1000.0
                ts_list.append(int(ts_f))
            except Exception:
                continue
            try:
                o = float(c.get("open"))
                h = float(c.get("high"))
                low_val = float(c.get("low"))
                cl = float(c.get("close"))
                if h < max(o, cl, low_val) or low_val > min(o, cl, h):
                    bad_ohlc_count += 1
            except Exception:
                bad_ohlc_count += 1
            try:
                v = float(c.get("volume"))
                if not math.isfinite(v) or v < 0:
                    bad_volume_count += 1
            except Exception:
                bad_volume_count += 1

        monotonic = all(ts_list[i] < ts_list[i + 1] for i in range(len(ts_list) - 1))
        unique_ratio = (
            (len(set(ts_list)) / len(ts_list))
            if ts_list
            else 0.0
        )
        last_ts = ts_list[-1] if ts_list else None
        stale_sec = ((now_ms - last_ts) / 1000.0) if last_ts else None
        ok = (
            count >= 50
            and monotonic
            and unique_ratio > 0.95
            and bad_ohlc_count == 0
            and bad_volume_count == 0
            and (stale_sec is not None and stale_sec < 20 * 60)
        )
        results[symbol] = {
            "ok": ok,
            "count": count,
            "monotonic_ts": monotonic,
            "unique_ts_ratio": unique_ratio,
            "bad_ohlc_count": bad_ohlc_count,
            "bad_volume_count": bad_volume_count,
            "stale_sec": stale_sec,
            "last_ts": last_ts,
        }
    return {
        "skipped": False,
        "symbols": symbols,
        "market_type": market_type,
        "timeframe": timeframe,
        "results": results,
    }


def _refresh_alpha_bootstrap_history(
    *,
    enabled: bool,
    output_rel: str,
    glob_patterns: str,
    max_sources: int,
    max_per_source: int,
    max_total: int,
    min_abs_pnl: float,
    min_pair_trades: int,
    min_pair_winrate: float,
    min_pair_expectancy: float,
    fallback_top_pairs: int,
    report_json_rel: str,
    fallback_positive_side_pairs: int = 0,
    min_side_trades: int = 2,
    min_side_winrate: float = 0.45,
    min_side_expectancy: float = 0.0,
) -> dict:
    if not enabled:
        return {"enabled": False, "ran": False, "success": False}

    output_txt = str(output_rel or "").strip()
    glob_txt = str(glob_patterns or "").strip()
    if not output_txt or not glob_txt:
        return {
            "enabled": True,
            "ran": False,
            "success": False,
            "error": "missing_output_or_glob",
        }

    report_path = None
    cmd = [
        sys.executable,
        str((WORKDIR / "scripts" / "build_alpha_history_db.py").resolve()),
        "--output",
        output_txt,
        "--glob",
        glob_txt,
        "--max-sources",
        str(max(0, int(max_sources))),
        "--max-per-source",
        str(max(1, int(max_per_source))),
        "--max-total",
        str(max(1, int(max_total))),
        "--min-abs-pnl",
        str(max(0.0, float(min_abs_pnl))),
        "--quality-filter",
        "--min-pair-trades",
        str(max(1, int(min_pair_trades))),
        "--min-pair-winrate",
        str(float(min_pair_winrate)),
        "--min-pair-expectancy",
        str(float(min_pair_expectancy)),
        "--fallback-top-pairs",
        str(max(0, int(fallback_top_pairs))),
        "--fallback-positive-side-pairs",
        str(max(0, int(fallback_positive_side_pairs))),
        "--min-side-trades",
        str(max(1, int(min_side_trades))),
        "--min-side-winrate",
        str(float(min_side_winrate)),
        "--min-side-expectancy",
        str(float(min_side_expectancy)),
    ]
    report_txt = str(report_json_rel or "").strip()
    if report_txt:
        report_path = (WORKDIR / report_txt).resolve()
        cmd.extend(["--report-json", report_txt])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKDIR),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "ran": True,
            "success": False,
            "error": str(exc),
        }

    out_path = (WORKDIR / output_txt).resolve()
    out_exists = out_path.exists()
    out_tail = ""
    err_tail = ""
    try:
        out_tail = "\n".join((proc.stdout or "").strip().splitlines()[-8:])
    except Exception:
        out_tail = ""
    try:
        err_tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
    except Exception:
        err_tail = ""

    parsed_report = {}
    if report_path is not None and report_path.exists():
        try:
            parsed_report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            parsed_report = {}

    return {
        "enabled": True,
        "ran": True,
        "success": bool(proc.returncode == 0 and out_exists),
        "returncode": int(proc.returncode),
        "output_path": str(out_path),
        "output_exists": bool(out_exists),
        "report_path": str(report_path) if report_path is not None else None,
        "report": parsed_report if isinstance(parsed_report, dict) else {},
        "stdout_tail": out_tail,
        "stderr_tail": err_tail,
    }


def _probe_alpha_bootstrap_source_db(
    *,
    source_db_url: str,
    source_db_glob: str,
) -> dict:
    source_spec = str(source_db_url or "").strip()
    if not source_spec:
        source_spec = str(source_db_glob or "").strip()
    if not source_spec:
        return {"enabled": True, "ran": False, "success": False}

    lower = source_spec.lower()
    if lower.startswith("sqlite:///"):
        source_spec = source_spec[len("sqlite:///") :]
    elif lower.startswith("sqlite://"):
        source_spec = source_spec[len("sqlite://") :]
    if (
        os.name == "nt"
        and len(source_spec) >= 3
        and source_spec[0] == "/"
        and source_spec[2] == ":"
    ):
        source_spec = source_spec[1:]

    source_path = Path(source_spec).resolve()
    if not source_path.exists():
        return {
            "enabled": True,
            "ran": False,
            "success": False,
            "output_path": str(source_path),
            "output_exists": False,
            "report": {},
            "stdout_tail": "",
            "stderr_tail": "probe_source_missing",
        }

    rows_inserted = 0
    try:
        import sqlite3

        conn = sqlite3.connect(str(source_path))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(1) FROM logs WHERE event='position_close'"
            )
            row = cur.fetchone()
            rows_inserted = int((row or [0])[0] or 0)
        finally:
            conn.close()
    except Exception as exc:
        return {
            "enabled": True,
            "ran": False,
            "success": False,
            "output_path": str(source_path),
            "output_exists": True,
            "report": {},
            "stdout_tail": "",
            "stderr_tail": f"probe_failed:{exc}",
        }

    return {
        "enabled": True,
        "ran": True,
        "success": True,
        "returncode": 0,
        "output_path": str(source_path),
        "output_exists": True,
        "report_path": None,
        "report": {
            "rows_inserted": rows_inserted,
            "pairs_selected": 0,
            "pair_stats_top": [],
            "pair_side_stats_top": [],
        },
        "stdout_tail": "PROBED_ALPHA_BOOTSTRAP_SOURCE_DB",
        "stderr_tail": "",
    }


def _init_db_schema(db_path: Path) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    cmd = [
        sys.executable,
        "-c",
        "from core.db_models import init_db; init_db(); print('init_db ok')",
    ]
    subprocess.run(cmd, cwd=str(WORKDIR), env=env, check=True)


def _enqueue_close_requests(
    db_path: Path,
    symbols: list[str],
    reason: str,
    diag_cb=None,
) -> int:
    requested_symbols = []
    seen_symbols = set()
    for raw_symbol in symbols or []:
        symbol = str(raw_symbol or "").strip()
        if not symbol:
            continue
        symbol_key = symbol.upper()
        if symbol_key in seen_symbols:
            continue
        seen_symbols.add(symbol_key)
        requested_symbols.append(symbol)
    if not requested_symbols:
        if diag_cb is not None:
            try:
                diag_cb(
                    "position_close_request_enqueue_skipped",
                    reason="empty_symbol_list",
                    symbols=[],
                    inserted=0,
                )
            except Exception:
                pass
        return 0
    pending_open_symbols = _pending_open_symbols(db_path)
    pending_open_symbol_keys = {
        str(symbol or "").strip().upper()
        for symbol in (pending_open_symbols or [])
        if str(symbol or "").strip()
    }
    symbol_filter_state = (
        "pending_open_symbols_filtered"
        if pending_open_symbols is not None
        else "pending_open_symbols_unavailable"
    )
    if pending_open_symbol_keys:
        symbols_payload = [
            symbol
            for symbol in requested_symbols
            if str(symbol).strip().upper() in pending_open_symbol_keys
        ]
    elif pending_open_symbols is not None:
        symbols_payload = []
    else:
        symbols_payload = list(requested_symbols)
    skipped_symbols = [
        symbol for symbol in requested_symbols if symbol not in symbols_payload
    ]
    if not symbols_payload:
        if diag_cb is not None:
            try:
                diag_cb(
                    "position_close_request_enqueue_skipped",
                    reason=(
                        "no_pending_open_symbols"
                        if pending_open_symbols is not None
                        else "pending_open_symbol_probe_unavailable"
                    ),
                    symbols=requested_symbols,
                    requested_symbols=requested_symbols,
                    pending_open_symbols=list(pending_open_symbols or []),
                    skipped_symbols=skipped_symbols,
                    symbol_filter_state=symbol_filter_state,
                    inserted=0,
                )
            except Exception:
                pass
        return 0
    sentinel_path = _arm_sqlite_enqueue_window_sentinel(db_path)
    inserted = 0
    try:
        if diag_cb is not None:
            try:
                diag_cb(
                    "position_close_request_enqueue_window_open",
                    sentinel_path=str(sentinel_path),
                    skip_reason="controlled_kpi_close_enqueue_window",
                    sqlite_persist_skip_targeted=True,
                )
            except Exception:
                pass
            try:
                diag_cb(
                    "position_close_request_enqueue_started",
                    reason=str(reason),
                    symbols=symbols_payload,
                    requested_symbols=requested_symbols,
                    skipped_symbols=skipped_symbols,
                    pending_open_symbols=list(pending_open_symbols or []),
                    symbol_filter_state=symbol_filter_state,
                    symbol_count=len(requested_symbols),
                    inserted=0,
                )
            except Exception:
                pass
        max_attempts = 3
        backoff_sec = (0.05, 0.1)
        last_exc = None
        attempts_used = 0
        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            conn = None
            try:
                conn = sqlite3.connect(str(db_path), timeout=0.2)
                cur = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                inserted = 0
                for sym in symbols_payload:
                    payload = json.dumps({"symbol": str(sym), "reason": str(reason)})
                    cur.execute(
                        "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                        (now_iso, "position_close_request", payload),
                    )
                    inserted += 1
                conn.commit()
                if diag_cb is not None:
                    try:
                        diag_cb(
                            "position_close_request_enqueue_success",
                            attempt=attempt,
                            inserted=inserted,
                            reason=str(reason),
                            symbols=symbols_payload,
                            requested_symbols=requested_symbols,
                            skipped_symbols=skipped_symbols,
                            pending_open_symbols=list(pending_open_symbols or []),
                            symbol_filter_state=symbol_filter_state,
                            symbol_count=len(symbols_payload),
                        )
                    except Exception:
                        pass
                    try:
                        diag_cb(
                            "position_close_request_enqueue_done",
                            reason=str(reason),
                            symbols=symbols_payload,
                            requested_symbols=requested_symbols,
                            skipped_symbols=skipped_symbols,
                            pending_open_symbols=list(pending_open_symbols or []),
                            symbol_filter_state=symbol_filter_state,
                            symbol_count=len(symbols_payload),
                            inserted=inserted,
                        )
                    except Exception:
                        pass
                return inserted
            except sqlite3.OperationalError as exc:
                last_exc = exc
                message = str(exc)
                is_locked = "database is locked" in message.lower()
                try:
                    if conn is not None:
                        conn.rollback()
                except Exception:
                    pass
                if not is_locked:
                    break
                if attempt >= max_attempts:
                    break
                if diag_cb is not None:
                    try:
                        diag_cb(
                            "position_close_request_enqueue_retry",
                            attempt=attempt,
                            max_attempts=max_attempts,
                            error_type=type(exc).__name__,
                            error_message=message,
                        )
                    except Exception:
                        pass
                time.sleep(backoff_sec[attempt - 1] if attempt -
                           1 < len(backoff_sec) else 0.1)
                inserted = 0
            except Exception as exc:
                last_exc = exc
                if diag_cb is not None:
                    try:
                        diag_cb(
                            "position_close_request_enqueue_error",
                            reason=str(reason),
                            symbols=symbols_payload,
                            symbol_count=len(symbols_payload),
                            inserted=inserted,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                    except Exception:
                        pass
                try:
                    if conn is not None:
                        conn.rollback()
                except Exception:
                    pass
                break
            finally:
                if conn is not None:
                    conn.close()
        if diag_cb is not None:
            try:
                if last_exc is not None:
                    diag_cb(
                        "position_close_request_enqueue_error",
                        reason=str(reason),
                        symbols=symbols_payload,
                        symbol_count=len(symbols_payload),
                        inserted=0,
                        error_type=type(last_exc).__name__,
                        error_message=str(last_exc),
                    )
                diag_cb(
                    "position_close_request_enqueue_final_failure",
                    attempts=attempts_used if last_exc is not None else 0,
                    error_type=type(
                        last_exc).__name__ if last_exc is not None else None,
                    error_message=str(last_exc) if last_exc is not None else "",
                    inserted=0,
                    reason=str(reason),
                    symbols=symbols_payload,
                    symbol_count=len(symbols_payload),
                )
            except Exception:
                pass
        return inserted
    finally:
        _clear_sqlite_enqueue_window_sentinel(db_path)
        if diag_cb is not None:
            try:
                diag_cb(
                    "position_close_request_enqueue_window_closed",
                    sentinel_path=str(sentinel_path),
                    skip_reason="controlled_kpi_close_enqueue_window",
                    sqlite_persist_skip_targeted=True,
                )
            except Exception:
                pass


def _pending_open_positions(db_path: Path) -> int | None:
    snapshot = _close_drain_snapshot(db_path)
    if snapshot is None:
        return None
    return int(snapshot.get("pending_positions") or 0)


def _pending_open_symbols(db_path: Path) -> list[str] | None:
    snapshot = _close_drain_snapshot(db_path)
    if snapshot is None:
        return None
    values = snapshot.get("pending_position_symbols")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value or "").strip()]


def _probe_latest_canonical_promotion(db_path: Path) -> dict | None:
    if not db_path.exists():
        return None
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, timestamp, details FROM logs "
            "WHERE event = 'canonical_promotion' ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        payload = _parse_json_payload(row["details"])
        if not isinstance(payload, dict):
            payload = {}
        canonical = payload.get("canonical_bucket") or {}
        if not isinstance(canonical, dict):
            canonical = {}
        symbol = str(
            payload.get("symbol")
            or canonical.get("symbol")
            or canonical.get("raw_symbol")
            or ""
        ).strip()
        strategy = str(
            payload.get("strategy")
            or canonical.get("strategy_identity")
            or canonical.get("raw_strategy")
            or ""
        ).strip()
        side = str(
            payload.get("side")
            or canonical.get("side")
            or canonical.get("raw_side")
            or ""
        ).strip().lower()
        canonical_key = _canonical_bucket_from_payload(payload)
        if not canonical_key and symbol and strategy and side in {"buy", "sell"}:
            canonical_key = f"{symbol.upper()}|{strategy.upper()}|{side}"
        runtime_seq = payload.get("runtime_seq")
        try:
            runtime_seq = int(runtime_seq)
        except Exception:
            runtime_seq = int(row["id"] or 0)
        if not symbol or not strategy or side not in {
                "buy", "sell"} or not canonical_key:
            return None
        return {
            "symbol": symbol.upper(),
            "strategy": strategy,
            "side": side,
            "canonical_key": str(canonical_key),
            "correlation_id": payload.get("correlation_id"),
            "promotion_runtime_seq": runtime_seq,
            "promotion_row_id": int(row["id"] or 0),
            "promotion_ts": str(row["timestamp"] or ""),
        }
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def _enqueue_post_promotion_reeval_request(
    db_path: Path,
    request_payload: dict,
    diag_cb=None,
) -> int | None:
    payload = dict(request_payload or {})
    symbol = str(payload.get("symbol") or "").strip().upper()
    strategy = str(payload.get("strategy") or "").strip()
    side = str(payload.get("side") or "").strip().lower()
    canonical_key = str(payload.get("canonical_key") or "").strip()
    if not symbol or not strategy or side not in {"buy", "sell"} or not canonical_key:
        return None
    sentinel_path = _arm_sqlite_enqueue_window_sentinel(db_path)
    conn = None
    try:
        if diag_cb is not None:
            try:
                diag_cb(
                    "post_promotion_reeval_request_window_open",
                    sentinel_path=str(sentinel_path),
                    skip_reason="controlled_kpi_post_promotion_reeval_enqueue_window",
                    sqlite_persist_skip_targeted=True,
                )
            except Exception:
                pass
        max_attempts = 5
        backoff_sec = (0.05, 0.1, 0.2, 0.4)
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                conn = sqlite3.connect(str(db_path), timeout=0.5)
                conn.execute("PRAGMA busy_timeout = 500")
                cur = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                    (
                        now_iso,
                        "post_promotion_reeval_request",
                        json.dumps(payload, ensure_ascii=True),
                    ),
                )
                row_id = int(cur.lastrowid or 0)
                conn.commit()
                if diag_cb is not None:
                    try:
                        diag_cb(
                            "post_promotion_reeval_requested",
                            promotion_runtime_seq=payload.get("promotion_runtime_seq"),
                            reeval_runtime_seq=row_id,
                            gate_read_after_promotion_runtime_seq=None,
                            reeval_enqueue_attempt=attempt,
                        )
                    except Exception:
                        pass
                return row_id
            except sqlite3.OperationalError as exc:
                last_exc = exc
                try:
                    if conn is not None:
                        conn.rollback()
                except Exception:
                    pass
                message = str(exc)
                is_locked = "database is locked" in message.lower()
                if diag_cb is not None:
                    try:
                        diag_cb(
                            "post_promotion_reeval_request_retry",
                            promotion_runtime_seq=payload.get("promotion_runtime_seq"),
                            reeval_runtime_seq=None,
                            gate_read_after_promotion_runtime_seq=None,
                            reeval_enqueue_attempt=attempt,
                            reeval_enqueue_max_attempts=max_attempts,
                            error_type=type(exc).__name__,
                            error_message=message,
                            sqlite_locked=bool(is_locked),
                        )
                    except Exception:
                        pass
                if (not is_locked) or attempt >= max_attempts:
                    break
                time.sleep(
                    backoff_sec[attempt - 1]
                    if attempt - 1 < len(backoff_sec)
                    else 0.1
                )
            except Exception as exc:
                last_exc = exc
                try:
                    if conn is not None:
                        conn.rollback()
                except Exception:
                    pass
                break
            finally:
                if conn is not None:
                    conn.close()
                    conn = None
        if diag_cb is not None:
            try:
                diag_cb(
                    "post_promotion_reeval_requested",
                    promotion_runtime_seq=payload.get("promotion_runtime_seq"),
                    reeval_runtime_seq=None,
                    gate_read_after_promotion_runtime_seq=None,
                    post_promotion_reeval_result="enqueue_failed",
                    reeval_exit_reason=(
                        f"enqueue_error:{type(last_exc).__name__}"
                        if last_exc is not None
                        else "enqueue_error:unknown"
                    ),
                )
            except Exception:
                pass
        return None
    finally:
        if conn is not None:
            conn.close()
        _clear_sqlite_enqueue_window_sentinel(db_path)
        if diag_cb is not None:
            try:
                diag_cb(
                    "post_promotion_reeval_request_window_closed",
                    sentinel_path=str(sentinel_path),
                    skip_reason="controlled_kpi_post_promotion_reeval_enqueue_window",
                    sqlite_persist_skip_targeted=True,
                )
            except Exception:
                pass


def _enqueue_post_promotion_force_cycle_request(
    db_path: Path,
    request_payload: dict,
    diag_cb=None,
) -> int | None:
    payload = dict(request_payload or {})
    symbol = str(payload.get("symbol") or "").strip().upper()
    strategy = str(payload.get("strategy") or "").strip()
    side = str(payload.get("side") or "").strip().lower()
    canonical_key = str(payload.get("canonical_key") or "").strip()
    if not symbol or not strategy or side not in {"buy", "sell"} or not canonical_key:
        return None
    conn = None
    try:
        if diag_cb is not None:
            try:
                diag_cb(
                    "handoff_parent_enqueue_enter",
                    symbol=symbol,
                    strategy=strategy,
                    side=side,
                    canonical_key=canonical_key,
                    transfer_site_id="parent_enqueue",
                    mailbox_stage="enqueue_enter",
                    handoff_transport_state="enqueueing",
                )
            except Exception:
                pass
        conn = sqlite3.connect(str(db_path), timeout=0.2)
        cur = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
            (
                now_iso,
                "post_promotion_force_cycle_request",
                json.dumps(payload, ensure_ascii=True),
            ),
        )
        row_id = int(cur.lastrowid or 0)
        conn.commit()
        if diag_cb is not None:
            try:
                diag_cb(
                    "handoff_parent_enqueue_done",
                    symbol=symbol,
                    strategy=strategy,
                    side=side,
                    canonical_key=canonical_key,
                    transfer_site_id="parent_enqueue",
                    mailbox_stage="enqueue_done",
                    handoff_transport_state="queued",
                    forced_cycle_request_runtime_seq=row_id,
                )
            except Exception:
                pass
            try:
                diag_cb(
                    "handoff_parent_signal_sent",
                    symbol=symbol,
                    strategy=strategy,
                    side=side,
                    canonical_key=canonical_key,
                    transfer_site_id="parent_enqueue",
                    mailbox_stage="signal_sent",
                    handoff_transport_state="signal_sent",
                    forced_cycle_request_runtime_seq=row_id,
                )
            except Exception:
                pass
        if diag_cb is not None:
            try:
                diag_cb(
                    "forced_cycle_requested",
                    promotion_runtime_seq=payload.get("promotion_runtime_seq"),
                    forced_cycle_request_runtime_seq=row_id,
                    forced_cycle_exit_reason=None,
                )
            except Exception:
                pass
        return row_id
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        if diag_cb is not None:
            try:
                diag_cb(
                    "forced_cycle_failed",
                    promotion_runtime_seq=payload.get("promotion_runtime_seq"),
                    forced_cycle_request_runtime_seq=None,
                    forced_cycle_exit_reason=f"enqueue_error:{type(exc).__name__}",
                    exception_class=type(exc).__name__,
                    exception_message=str(exc),
                )
            except Exception:
                pass
        return None
    finally:
        if conn is not None:
            conn.close()


def _should_request_post_promotion_forced_cycle(
    *,
    post_promotion_reeval_completed: bool,
    post_promotion_reeval_result: str | None,
    post_promotion_forced_cycle_requested: bool,
) -> bool:
    if post_promotion_forced_cycle_requested:
        return False
    if post_promotion_reeval_completed:
        return True
    return str(post_promotion_reeval_result or "").strip() == "request_enqueue_failed"


def _resolve_post_promotion_forced_cycle_trigger(
    *,
    post_promotion_reeval_completed: bool,
    post_promotion_reeval_result: str | None,
) -> dict:
    if post_promotion_reeval_completed:
        return {
            "mode": "after_reeval_completed",
            "request_reason": "post_promotion_forced_cycle",
        }
    if str(post_promotion_reeval_result or "").strip() == "request_enqueue_failed":
        return {
            "mode": "after_reeval_enqueue_failure",
            "request_reason": (
                "post_promotion_forced_cycle_after_"
                "enqueue_failure"
            ),
        }
    return {
        "mode": "after_unknown",
        "request_reason": "post_promotion_forced_cycle",
    }


def _finalize_post_promotion_forced_cycle_trigger_contract(
    *,
    post_promotion_forced_cycle_requested: bool,
    post_promotion_forced_cycle_trigger_mode: str | None,
    post_promotion_forced_cycle_request_reason: str | None,
    post_promotion_reeval_completed: bool,
    post_promotion_reeval_result: str | None,
) -> dict:
    expected = _resolve_post_promotion_forced_cycle_trigger(
        post_promotion_reeval_completed=post_promotion_reeval_completed,
        post_promotion_reeval_result=post_promotion_reeval_result,
    )
    observed_mode = str(post_promotion_forced_cycle_trigger_mode or "").strip()
    observed_reason = str(post_promotion_forced_cycle_request_reason or "").strip()
    contract = {
        "active": bool(post_promotion_forced_cycle_requested),
        "expected_mode": str(expected.get("mode") or ""),
        "expected_request_reason": str(expected.get("request_reason") or ""),
        "observed_mode": observed_mode,
        "observed_request_reason": observed_reason,
        "status": "inactive",
        "ok": True,
        "reason_codes": [],
    }
    if not contract["active"]:
        return contract
    reason_codes = []
    if not observed_mode:
        reason_codes.append("trigger_mode_missing")
    if not observed_reason:
        reason_codes.append("request_reason_missing")
    if observed_mode and observed_mode != contract["expected_mode"]:
        reason_codes.append("trigger_mode_mismatch")
    if observed_reason and observed_reason != contract["expected_request_reason"]:
        reason_codes.append("request_reason_mismatch")
    contract["reason_codes"] = reason_codes
    contract["ok"] = len(reason_codes) == 0
    contract["status"] = "ok" if contract["ok"] else "mismatch"
    return contract


def _close_drain_snapshot(db_path: Path) -> dict | None:
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT event, details FROM logs "
            "WHERE event IN ('position_open','position_close_request','position_close') "  # noqa: E501
            "ORDER BY rowid")
        open_count = 0
        close_request_count_raw = 0
        close_count = 0
        open_by_symbol = Counter()
        close_request_by_symbol = Counter()
        close_by_symbol = Counter()
        for row in cur.fetchall() or []:
            event_name = str(row["event"] or "").strip()
            payload = _parse_json_payload(row["details"])
            symbol = str(
                payload.get("symbol") or (
                    (payload.get("position") or {}).get("symbol") if isinstance(
                        payload.get("position"),
                        dict) else "") or "").strip().upper()
            if event_name == "position_open":
                open_count += 1
                if symbol:
                    open_by_symbol[symbol] += 1
            elif event_name == "position_close_request":
                close_request_count_raw += 1
                if symbol:
                    close_request_by_symbol[symbol] += 1
            elif event_name == "position_close":
                close_count += 1
                if symbol:
                    close_by_symbol[symbol] += 1
        pending_positions = 0
        pending_position_symbols = []
        effective_close_request_count = 0
        effective_close_request_symbols = []
        close_request_backlog = 0
        close_request_backlog_raw = 0
        duplicate_close_request_symbols = []
        symbol_universe = sorted(
            set(open_by_symbol) | set(close_request_by_symbol) | set(close_by_symbol)
        )
        for symbol in symbol_universe:
            opened = int(open_by_symbol.get(symbol) or 0)
            requested = int(close_request_by_symbol.get(symbol) or 0)
            closed = int(close_by_symbol.get(symbol) or 0)
            if opened > closed:
                pending_positions += opened - closed
                pending_position_symbols.append(symbol)
            effective_requested = min(opened, requested)
            if effective_requested > 0:
                effective_close_request_count += effective_requested
                effective_close_request_symbols.append(symbol)
            if requested > closed:
                close_request_backlog_raw += requested - closed
            if effective_requested > closed:
                close_request_backlog += effective_requested - closed
            if requested > opened:
                duplicate_close_request_symbols.append(symbol)
        duplicate_close_request_count = max(
            0, int(close_request_count_raw) - int(effective_close_request_count)
        )
        return {
            "position_open_count": open_count,
            "position_close_request_count": effective_close_request_count,
            "position_close_request_count_raw": close_request_count_raw,
            "position_close_count": close_count,
            "pending_positions": pending_positions,
            "close_request_backlog": close_request_backlog,
            "close_request_backlog_raw": close_request_backlog_raw,
            "duplicate_close_request_count": duplicate_close_request_count,
            "pending_position_symbols": pending_position_symbols,
            "effective_close_request_symbols": effective_close_request_symbols,
            "duplicate_close_request_symbols": duplicate_close_request_symbols,
            "progress_complete": bool(
                pending_positions == 0 and close_request_backlog == 0
            ),
        }
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def _is_successful_shutdown_classification(classification: str | None) -> bool:
    return str(classification or "").strip() in {
        "close_flush_done_pending_positions_zero",
        "real_post_promotion_read_observed",
    }


def _normalize_process_returncode(
    *,
    shutdown_classification: str | None,
    raw_returncode: int | None,
    final_close_drain_snapshot: dict | None,
) -> int:
    normalized = int(raw_returncode if raw_returncode is not None else -1)
    if normalized == 0:
        return 0
    if not _is_successful_shutdown_classification(shutdown_classification):
        return normalized
    if not isinstance(final_close_drain_snapshot, dict):
        return normalized
    if int(final_close_drain_snapshot.get("pending_positions") or 0) != 0:
        return normalized
    if int(final_close_drain_snapshot.get("close_request_backlog") or 0) != 0:
        return normalized
    return 0


def _canonicalize_process_returncode_raw(
    *,
    shutdown_classification: str | None,
    raw_returncode: int | None,
    final_close_drain_snapshot: dict | None,
    process_stop_mode: str | None,
) -> int:
    canonical = int(raw_returncode if raw_returncode is not None else -1)
    if canonical == 0:
        return 0
    if str(process_stop_mode or "").strip() not in {
        "wrapper_terminate_after_success",
        "wrapper_kill_after_success",
    }:
        return canonical
    if (
        _normalize_process_returncode(
            shutdown_classification=shutdown_classification,
            raw_returncode=canonical,
            final_close_drain_snapshot=final_close_drain_snapshot,
        )
        == 0
    ):
        return 0
    return canonical


def _resolve_final_shutdown_state(
    *,
    shutdown_classification: str | None,
    termination_reason: str | None,
    final_close_drain_snapshot: dict | None,
) -> dict:
    candidate_shutdown_classification = (
        str(shutdown_classification or termination_reason or "").strip() or None
    )
    candidate_termination_reason = str(termination_reason or "").strip() or None
    final_shutdown_classification = candidate_shutdown_classification
    final_termination_reason = candidate_termination_reason or candidate_shutdown_classification  # noqa: E501
    final_progress_complete = False
    if isinstance(final_close_drain_snapshot, dict):
        final_progress_complete = bool(
            final_close_drain_snapshot.get("progress_complete")
        ) or (
            int(final_close_drain_snapshot.get("pending_positions") or 0) == 0
            and int(final_close_drain_snapshot.get("close_request_backlog") or 0) == 0
        )
    final_drain_recheck_result = "not_applicable"
    if (
        candidate_shutdown_classification == "close_flush_done_pending_positions_zero"
        and not final_progress_complete
    ):
        final_shutdown_classification = "close_drain_incomplete_pending_positions"
        final_termination_reason = final_shutdown_classification
        final_drain_recheck_result = (
            "success_classification_invalidated_by_final_snapshot"
        )
    if candidate_shutdown_classification in {
        "deterministic_stall_pending_close_drain",
        "close_drain_timeout_pending_positions",
    }:
        if (
            candidate_shutdown_classification
            == "deterministic_stall_pending_close_drain"
        ):
            final_drain_recheck_result = "stall_persisted_after_final_recheck"
        else:
            final_drain_recheck_result = "timeout_persisted_after_final_recheck"
        if final_progress_complete:
            final_shutdown_classification = "close_flush_done_pending_positions_zero"
            final_termination_reason = final_shutdown_classification
            final_drain_recheck_result = "late_close_drain_completion_observed"
    # PAPER_FORCE_CLOSE_ON_EXIT: the bot force-closed all positions before exiting
    # via PAPER_RUN_ONCE.  The process exited cleanly (proc_exited) and the final
    # drain snapshot confirms no positions remain — upgrade to the canonical clean
    # shutdown classification so live_guard accepts the run.
    if candidate_shutdown_classification == "proc_exited" and final_progress_complete:
        final_shutdown_classification = "close_flush_done_pending_positions_zero"
        final_termination_reason = final_shutdown_classification
        final_drain_recheck_result = "late_close_drain_completion_observed"
    return {
        "candidate_shutdown_classification": candidate_shutdown_classification,
        "candidate_termination_reason": candidate_termination_reason,
        "final_shutdown_classification": final_shutdown_classification,
        "final_termination_reason": final_termination_reason,
        "final_progress_complete": bool(final_progress_complete),
        "final_drain_recheck_result": final_drain_recheck_result,
    }


def _canonical_bucket_from_payload(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    direct = str(
        payload.get("canonical_key")
        or payload.get("canonical_bucket_key")
        or ""
    ).strip()
    if direct:
        return direct
    try:
        from scripts.canonical_edge_history_linkage import build_canonical_bucket_key

        canonical = build_canonical_bucket_key(payload)
        bucket = str(canonical.get("canonical_bucket_key") or "").strip()
        return bucket or None
    except Exception:
        return None


def _probe_real_post_promotion_reevaluation(db_path: Path) -> dict:
    result = {
        "promotion_count": 0,
        "promoted_buckets": [],
        "promotion_runtime_seq": None,
        "reeval_runtime_seq": None,
        "real_post_promotion_read_count": 0,
        "real_post_promotion_read_buckets": [],
        "gate_read_after_promotion_runtime_seq": None,
        "timing_replay_only_buckets": [],
        "observed_real_post_promotion_read": False,
    }
    if not db_path.exists():
        return result
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, event, details FROM logs "
            "WHERE event IN ('canonical_promotion','canonical_gate_read','entry_gate_decision_summary','canonical_explicit_post_promotion_eval_invoked') "  # noqa: E501
            "ORDER BY id")
        first_promotion_row_by_bucket = {}
        first_promotion_runtime_seq_by_bucket = {}
        reeval_runtime_seq_by_bucket = {}
        real_post_rows = {}
        real_post_runtime_seq_by_bucket = {}
        replay_only_buckets = set()
        for row in cur.fetchall() or []:
            payload = _parse_json_payload(row["details"])
            bucket = _canonical_bucket_from_payload(payload)
            if not bucket:
                continue
            row_id = int(row["id"] or 0)
            event_name = str(row["event"] or "")
            if event_name == "canonical_promotion":
                first_promotion_row_by_bucket.setdefault(bucket, row_id)
                runtime_seq = payload.get("runtime_seq")
                try:
                    runtime_seq = int(runtime_seq)
                except Exception:
                    runtime_seq = row_id
                first_promotion_runtime_seq_by_bucket.setdefault(bucket, runtime_seq)
                continue
            first_promo_row = first_promotion_row_by_bucket.get(bucket)
            if first_promo_row is None or row_id <= first_promo_row:
                continue
            if event_name == "canonical_explicit_post_promotion_eval_invoked":
                runtime_seq = payload.get("runtime_seq")
                try:
                    runtime_seq = int(runtime_seq)
                except Exception:
                    runtime_seq = row_id
                reeval_runtime_seq_by_bucket.setdefault(bucket, runtime_seq)
                continue
            if event_name != "canonical_gate_read":
                continue
            if payload.get("timing_replay_index") is not None:
                replay_only_buckets.add(bucket)
                continue
            real_post_rows.setdefault(bucket, row_id)
            runtime_seq = payload.get("runtime_seq")
            try:
                runtime_seq = int(runtime_seq)
            except Exception:
                runtime_seq = row_id
            real_post_runtime_seq_by_bucket.setdefault(bucket, runtime_seq)
        result["promotion_count"] = len(first_promotion_row_by_bucket)
        result["promoted_buckets"] = sorted(first_promotion_row_by_bucket)
        if first_promotion_runtime_seq_by_bucket:
            result["promotion_runtime_seq"] = min(
                int(v) for v in first_promotion_runtime_seq_by_bucket.values()
            )
        if reeval_runtime_seq_by_bucket:
            result["reeval_runtime_seq"] = min(
                int(v) for v in reeval_runtime_seq_by_bucket.values()
            )
        result["real_post_promotion_read_count"] = len(real_post_rows)
        result["real_post_promotion_read_buckets"] = sorted(real_post_rows)
        if real_post_runtime_seq_by_bucket:
            result["gate_read_after_promotion_runtime_seq"] = min(
                int(v) for v in real_post_runtime_seq_by_bucket.values()
            )
        result["timing_replay_only_buckets"] = sorted(
            b for b in replay_only_buckets if b not in real_post_rows
        )
        result["observed_real_post_promotion_read"] = bool(real_post_rows)
        return result
    except Exception:
        return result
    finally:
        if conn is not None:
            conn.close()


def _probe_forced_post_promotion_cycle(db_path: Path) -> dict:
    result = {
        "requested": False,
        "started": False,
        "completed": False,
        "failed": False,
        "promotion_runtime_seq": None,
        "forced_cycle_request_runtime_seq": None,
        "forced_cycle_runtime_seq": None,
        "forced_cycle_exit_reason": None,
        "forced_cycle_result_classification": None,
    }
    if not db_path.exists():
        return result
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, event, details FROM logs "
            "WHERE event IN ('post_promotion_force_cycle_request','forced_cycle_requested','forced_cycle_started','forced_cycle_completed','forced_cycle_failed') "  # noqa: E501
            "ORDER BY id")
        for row in cur.fetchall() or []:
            payload = _parse_json_payload(row["details"])
            if not isinstance(payload, dict):
                payload = {}
            event = str(row["event"] or "")
            if event == "post_promotion_force_cycle_request":
                result["requested"] = True
                result["promotion_runtime_seq"] = payload.get(
                    "promotion_runtime_seq") or result["promotion_runtime_seq"]
                result["forced_cycle_request_runtime_seq"] = int(row["id"] or 0)
            elif event == "forced_cycle_requested":
                result["requested"] = True
                result["promotion_runtime_seq"] = payload.get(
                    "promotion_runtime_seq") or result["promotion_runtime_seq"]
                result["forced_cycle_request_runtime_seq"] = int(row["id"] or 0)
            elif event == "forced_cycle_started":
                result["started"] = True
                result["promotion_runtime_seq"] = payload.get(
                    "promotion_runtime_seq") or result["promotion_runtime_seq"]
                result["forced_cycle_runtime_seq"] = int(row["id"] or 0)
            elif event == "forced_cycle_completed":
                result["completed"] = True
                result["promotion_runtime_seq"] = payload.get(
                    "promotion_runtime_seq") or result["promotion_runtime_seq"]
                result["forced_cycle_runtime_seq"] = int(row["id"] or 0)
                result["forced_cycle_exit_reason"] = payload.get(
                    "forced_cycle_exit_reason") or result["forced_cycle_exit_reason"]
                result["forced_cycle_result_classification"] = payload.get(
                    "result_classification") or result["forced_cycle_result_classification"]  # noqa: E501
            elif event == "forced_cycle_failed":
                result["failed"] = True
                result["promotion_runtime_seq"] = payload.get(
                    "promotion_runtime_seq") or result["promotion_runtime_seq"]
                result["forced_cycle_runtime_seq"] = int(row["id"] or 0)
                result["forced_cycle_exit_reason"] = payload.get(
                    "forced_cycle_exit_reason") or result["forced_cycle_exit_reason"]
                result["forced_cycle_result_classification"] = payload.get(
                    "result_classification") or result["forced_cycle_result_classification"]  # noqa: E501
        return result
    except Exception:
        return result
    finally:
        if conn is not None:
            conn.close()


def _probe_post_close_summary_grace(db_path: Path) -> dict:
    result = {
        "post_close_boundary_rowid": None,
        "entry_edge_over_fee_eval_count": 0,
        "post_close_summary_pre_assembly_count": 0,
        "post_close_summary_assembly_enter_count": 0,
        "post_close_summary_payload_built_count": 0,
        "post_close_summary_emit_attempt_count": 0,
        "post_close_summary_emit_done_count": 0,
        "entry_gate_decision_summary_count": 0,
        "risk_decision_count": 0,
        "observed_post_close_eval": False,
        "observed_post_close_summary_complete": False,
        "observed_post_close_summary_emit_done": False,
        "observed_post_close_risk_decision_parity": False,
    }
    if not db_path.exists():
        return result
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(rowid) AS rowid FROM logs WHERE event = ?",
            ("position_close_request",),
        )
        row = cur.fetchone()
        boundary_rowid = None
        if row is not None:
            try:
                boundary_rowid = int(row["rowid"] or 0)
            except Exception:
                boundary_rowid = None
        if not boundary_rowid:
            cur.execute(
                "SELECT MAX(rowid) AS rowid FROM logs WHERE event = ?",
                ("position_close",),
            )
            row = cur.fetchone()
            if row is not None:
                try:
                    boundary_rowid = int(row["rowid"] or 0)
                except Exception:
                    boundary_rowid = None
        if not boundary_rowid:
            return result
        result["post_close_boundary_rowid"] = boundary_rowid
        cur.execute(
            "SELECT event, COUNT(*) AS count FROM logs "
            "WHERE rowid > ? AND event IN ("
            "'entry_edge_over_fee_eval',"
            "'post_close_summary_pre_assembly',"
            "'post_close_summary_assembly_enter',"
            "'post_close_summary_payload_built',"
            "'post_close_summary_emit_attempt',"
            "'post_close_summary_emit_done',"
            "'entry_gate_decision_summary',"
            "'risk_decision'"
            ") GROUP BY event",
            (boundary_rowid,),
        )
        for event_name, count in cur.fetchall() or []:
            event_name = str(event_name or "")
            count_val = int(count or 0)
            if event_name == "entry_edge_over_fee_eval":
                result["entry_edge_over_fee_eval_count"] = count_val
            elif event_name == "post_close_summary_pre_assembly":
                result["post_close_summary_pre_assembly_count"] = count_val
            elif event_name == "post_close_summary_assembly_enter":
                result["post_close_summary_assembly_enter_count"] = count_val
            elif event_name == "post_close_summary_payload_built":
                result["post_close_summary_payload_built_count"] = count_val
            elif event_name == "post_close_summary_emit_attempt":
                result["post_close_summary_emit_attempt_count"] = count_val
            elif event_name == "post_close_summary_emit_done":
                result["post_close_summary_emit_done_count"] = count_val
            elif event_name == "entry_gate_decision_summary":
                result["entry_gate_decision_summary_count"] = count_val
            elif event_name == "risk_decision":
                result["risk_decision_count"] = count_val
        result["observed_post_close_eval"] = bool(
            result["entry_edge_over_fee_eval_count"] > 0
            or result["post_close_summary_pre_assembly_count"] > 0
            or result["post_close_summary_assembly_enter_count"] > 0
            or result["post_close_summary_payload_built_count"] > 0
            or result["post_close_summary_emit_attempt_count"] > 0
            or result["post_close_summary_emit_done_count"] > 0
            or result["entry_gate_decision_summary_count"] > 0
            or result["risk_decision_count"] > 0
        )
        result["observed_post_close_summary_emit_done"] = bool(
            result["post_close_summary_emit_done_count"] > 0
        )
        result["observed_post_close_risk_decision_parity"] = bool(
            result["risk_decision_count"] >= result["entry_gate_decision_summary_count"]
        )
        result["observed_post_close_summary_complete"] = bool(
            result["observed_post_close_summary_emit_done"]
            and result["observed_post_close_risk_decision_parity"]
        )
        return result
    except Exception:
        return result
    finally:
        if conn is not None:
            conn.close()


def _base_env(
    db_path: Path,
    *,
    use_mock: bool,
    market_type: str,
    run_symbols: str,
    paper_auto_open: bool,
    paper_auto_close_sec: int,
    equity_snapshot_sec: int,
    quality_profile: bool,
    alpha_bootstrap_source_db_url: str,
    alpha_bootstrap_source_db_glob: str,
) -> dict:
    env = os.environ.copy()
    env["LIVE"] = "0"
    env["USE_MOCK"] = "1" if use_mock else "0"
    env["ZOL0_TOKEN"] = "controlled_kpi_runner"
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["PYTHONUNBUFFERED"] = "1"
    env["AUTO_MONITOR_SET_ENV_ALLOCATION"] = "0"
    env["MARKET_TYPE"] = str(market_type)
    env["RUN_SYMBOLS"] = str(run_symbols)
    env["PAPER_AUTO_OPEN"] = "1" if paper_auto_open else "0"
    env["PAPER_AUTO_CLOSE_SEC"] = str(int(paper_auto_close_sec))
    env["EQUITY_SNAPSHOT_SEC"] = str(int(equity_snapshot_sec))
    source_url = str(alpha_bootstrap_source_db_url or "").strip()
    source_glob = str(alpha_bootstrap_source_db_glob or "").strip()
    if source_url:
        env["ALPHA_BOOTSTRAP_SOURCE_DB_URL"] = source_url
    else:
        env.pop("ALPHA_BOOTSTRAP_SOURCE_DB_URL", None)
    if source_glob:
        env["ALPHA_BOOTSTRAP_SOURCE_DB_GLOB"] = source_glob
    else:
        env.pop("ALPHA_BOOTSTRAP_SOURCE_DB_GLOB", None)
    if quality_profile:
        env["DATA_QUALITY_GUARD"] = "1"
        env["STRATEGY_GUARD_ENABLE"] = "1"
        env["STRATEGY_GUARD_MIN_TRADES"] = "2"
        env["STRATEGY_GUARD_MIN_PF"] = "1.00"
        env["STRATEGY_GUARD_MIN_WINRATE"] = "0.35"
        env["SIDE_GUARD_ENABLE"] = "1"
        env["SIDE_GUARD_WINDOW"] = "12"
        env["SIDE_GUARD_MIN_TRADES"] = "1"
        env["SIDE_GUARD_MIN_WINRATE"] = "0.34"
        env["SIDE_GUARD_MAX_EXPECTANCY"] = "-0.0001"
        env["SIDE_GUARD_COOLDOWN_SEC"] = "300"
        env["SYMBOL_STRATEGY_GUARD_ENABLE"] = "0"
        env["SYMBOL_STRATEGY_GUARD_WINDOW"] = "10"
        env["SYMBOL_STRATEGY_GUARD_MIN_TRADES"] = "2"
        env["SYMBOL_STRATEGY_GUARD_MIN_WINRATE"] = "0.30"
        env["SYMBOL_STRATEGY_GUARD_MAX_EXPECTANCY"] = "-0.02"
        env["SYMBOL_STRATEGY_GUARD_COOLDOWN_SEC"] = "420"
        env["ALPHA_WHITELIST_ENABLE"] = "0"
        env["ALPHA_WHITELIST_WINDOW"] = "12"
        env["ALPHA_WHITELIST_MIN_TRADES"] = "2"
        env["ALPHA_WHITELIST_MIN_EXPECTANCY"] = "0.0"
        env["ALPHA_WHITELIST_MIN_WINRATE"] = "0.25"
        env["ALPHA_WHITELIST_COLDSTART_ALLOW"] = "1"
        env["ALPHA_WHITELIST_COOLDOWN_SEC"] = "420"
        env["ALPHA_WHITELIST_FALLBACK_ENABLE"] = "1"
        env["ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS"] = "1"
        env["GLOBAL_STRATEGY_ALPHA_ENABLE"] = "0"
        env["GLOBAL_STRATEGY_ALPHA_WINDOW"] = "12"
        env["GLOBAL_STRATEGY_ALPHA_MIN_TRADES"] = "2"
        env["GLOBAL_STRATEGY_ALPHA_MIN_EXPECTANCY"] = "0.0"
        env["GLOBAL_STRATEGY_ALPHA_MIN_WINRATE"] = "0.25"
        env["GLOBAL_STRATEGY_ALPHA_COLDSTART_ALLOW"] = "1"
        env["GLOBAL_STRATEGY_ALPHA_COOLDOWN_SEC"] = "420"
        env["ALPHA_BOOTSTRAP_MAX_TRADES"] = "400"
        env["ENTRY_ALPHA_SELECTOR_ENABLE"] = "0"
        env["ENTRY_ALPHA_SELECTOR_WINDOW"] = "12"
        env["ENTRY_ALPHA_SELECTOR_MIN_TRADES"] = "2"
        env["ENTRY_ALPHA_SELECTOR_MIN_WINRATE"] = "0.25"
        env["ENTRY_ALPHA_SELECTOR_MIN_EXPECTANCY"] = "-0.02"
        env["ENTRY_ALPHA_SELECTOR_BAD_WEIGHT_SCALE"] = "0.40"
        env["ENTRY_ALPHA_SELECTOR_GOOD_WEIGHT_SCALE"] = "1.08"
        env["ENTRY_ALPHA_SELECTOR_DROP_BAD"] = "1"
        env["ENTRY_ALPHA_SELECTOR_KEEP_MIN_SIGNALS"] = "1"
        env["ENTRY_ADAPTIVE_RELAX_ENABLE"] = "0"
        env["ENTRY_ADAPTIVE_RELAX_AFTER_SEC"] = "600"
        env["ENTRY_ADAPTIVE_RELAX_SCORE_MULT"] = "0.80"
        env["ENTRY_ADAPTIVE_RELAX_VOL_MULT"] = "0.90"
        env["ENTRY_ADAPTIVE_RELAX_VOTE_MIN"] = "1"
        env["ENTRY_ADAPTIVE_RELAX_DISABLE_TREND"] = "0"
        env["ENTRY_REQUIRE_TREND_AND_VOL"] = "0"
        env["ENTRY_BUY_REQUIRE_TREND"] = "0"
        env["ENTRY_SELL_REQUIRE_TREND"] = "1"
        env["ENTRY_SIGNAL_SCORE_MIN"] = "0.10"
        env["ENTRY_SIGNAL_SCORE_MIN_BUY"] = "0.15"
        env["ENTRY_BUY_MIN_SIGNAL_SCORE"] = "0.15"
        env["ENTRY_SIGNAL_MIN_VOTES"] = "1"
        env["ENTRY_VOLATILITY_MIN"] = "0.015"
        env["ENTRY_BUY_MIN_VOLATILITY"] = "0.015"
        env["ENTRY_RANGE_BLOCK_VOL"] = "0.02"
        env["DECISION_HYSTERESIS_SCORE"] = "0.05"
        env["DECISION_CHANGE_COOLDOWN_SEC"] = "5"
        env["ENTRY_QUALITY_SCALER_ENABLE"] = "1"
        env["ENTRY_QUALITY_MIN_SCALE"] = "0.20"
        env["ENTRY_QUALITY_MAX_SCALE"] = "0.85"
        env["ENTRY_QUALITY_SCORE_CAP"] = "1.50"
        env["ENTRY_QUALITY_VOTE_CAP"] = "1.50"
        env["LOSS_COOLDOWN_SEC"] = "300"
        env["allocation_pct"] = "0.010"
        env["MAX_OPEN_POSITIONS"] = "1"
        env["EXECUTION_COOLDOWN_SEC"] = "20"
        env["ENTRY_MIN_PROFIT_FEE_MULT"] = "1.25"
        env["ENTRY_MIN_NET_USDT"] = "0.20"
        env["PAPER_AUTO_CLOSE_POLICY"] = "profit_or_hard"
        env["PAPER_AUTO_CLOSE_HARD_SEC"] = str(max(int(paper_auto_close_sec) * 3, 180))
        env["PAPER_AUTO_CLOSE_MIN_PROFIT"] = "0.10"
        env["PAPER_GATE_ENABLE"] = "1"
        env["PAPER_GATE_MIN_CLOSED_TRADES"] = "2"
        env["PAPER_GATE_TARGET_15M"] = "0.20"
        env["PAPER_GATE_COOLDOWN_MIN"] = "10"
        env["WF_CALIBRATION_MIN_MEAN_NETPNL"] = "0.0"
        env["WF_CALIBRATION_MIN_PCT_MEET"] = "0.55"
    env.pop("CONTROLLED_KPI_EXPLICIT_POST_PROMOTION_EVAL_REQUEST", None)
    env.pop("RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL", None)
    env.pop("CONTROLLED_KPI_EXPLICIT_POST_PROMOTION_EVAL_REQUEST", None)
    env.pop("RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL", None)
    env.pop("PAPER_RUN_ONCE", None)
    return env


def _variant_env(
    db_path: Path,
    variant: str,
    *,
    use_mock: bool,
    market_type: str,
    run_symbols: str,
    paper_auto_open: bool,
    paper_auto_close_sec: int,
    equity_snapshot_sec: int,
    quality_profile: bool,
    alpha_bootstrap_source_db_url: str,
    alpha_bootstrap_source_db_glob: str,
    variant_overrides: dict | None = None,
) -> dict:
    env = _base_env(
        db_path,
        use_mock=use_mock,
        market_type=market_type,
        run_symbols=run_symbols,
        paper_auto_open=paper_auto_open,
        paper_auto_close_sec=paper_auto_close_sec,
        equity_snapshot_sec=equity_snapshot_sec,
        quality_profile=quality_profile,
        alpha_bootstrap_source_db_url=alpha_bootstrap_source_db_url,
        alpha_bootstrap_source_db_glob=alpha_bootstrap_source_db_glob,
    )
    if variant == "before":
        env["ENTRY_FILTER_STRICT"] = "0"
        env["ENTRY_IGNORE_HOLD_SIGNALS"] = "0"
        env["ENTRY_MIN_ACTIVE_STRATEGIES"] = "1"
        env["WF_CALIBRATION_ENABLE"] = "0"
        env["PAPER_AUTO_OPEN_STARTUP_ENABLE"] = "0"
        env["MAX_OPEN_POSITIONS"] = "1"
        # Keep risk model aligned with AFTER so compare-before deltas are not inflated
        # by a looser BEFORE sizing/exit profile.
        env["allocation_pct"] = "0.010"
        env["EXIT_STOP_LOSS_USDT"] = "0.18"
        env["EXIT_STOP_LOSS_MODE"] = "net"
        env["EXIT_TAKE_PROFIT_USDT"] = "0.72"
        env["EXIT_TAKE_PROFIT_MODE"] = "net"
        env["ENTRY_MIN_PROFIT_FEE_MULT"] = "1.20"
        env["ENTRY_MIN_NET_USDT"] = "0.12"
        env["ENTRY_MIN_NET_TO_STOP_RATIO"] = "1.10"
        env["CONTROLLED_KPI_EXPLICIT_POST_PROMOTION_EVAL_REQUEST"] = "1"
        env["RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL"] = "1"
        env.setdefault("RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS", "1")
    elif variant == "after":
        env["ENTRY_FILTER_STRICT"] = "1"
        env["ENTRY_IGNORE_HOLD_SIGNALS"] = "1"
        env["ENTRY_MIN_ACTIVE_STRATEGIES"] = "1"
        env["WF_CALIBRATION_ENABLE"] = "0"
        env["SEED_TRADES_ENABLE"] = "0"
        env["PAPER_AUTO_OPEN_STARTUP_ENABLE"] = "0"
        env["PAPER_AUTO_OPEN_FALLBACK_ENABLE"] = "0"
        env["PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST"] = "1"
        env["ALPHA_BOOTSTRAP_REQUIRE_EXTERNAL_SOURCE"] = "1"
        env["PAPER_AUTO_CLOSE_POLICY"] = "profit_or_hard"
        env["PAPER_AUTO_CLOSE_MIN_PROFIT"] = "0.10"
        env["ALPHA_BOOTSTRAP_MAX_TRADES"] = "600"
        env["ALPHA_WHITELIST_ENABLE"] = "1"
        env["ALPHA_WHITELIST_WINDOW"] = "24"
        env["ALPHA_WHITELIST_MIN_TRADES"] = "3"
        env["ALPHA_WHITELIST_MIN_EXPECTANCY"] = "-0.0005"
        env["ALPHA_WHITELIST_MIN_WINRATE"] = "0.40"
        # Default the after profile to the validated natural PAPER semantics.
        # Explicit variant overrides still win later in _variant_env().
        env["ALPHA_WHITELIST_COLDSTART_ALLOW"] = "1"
        env["ALPHA_WHITELIST_COOLDOWN_SEC"] = "1800"
        env["ALPHA_WHITELIST_FALLBACK_ENABLE"] = "1"
        env["ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS"] = "3"
        env["MAX_OPEN_POSITIONS"] = "5"  # relaxed: was 3
        env["ALPHA_REQUIRE_POSITIVE_UNIVERSE"] = "0"  # bootstrap all-neg →62 blocks
        env["ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_TRADES"] = "3"
        env["ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_EXPECTANCY"] = "0.00"
        env["ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_WINRATE"] = "0.35"
        env["ALPHA_UNIVERSE_EXPLORATION_ENABLE"] = "0"
        env["ALPHA_UNIVERSE_EXPLORATION_MIN_TRADES"] = "2"
        env["ALPHA_UNIVERSE_EXPLORATION_MIN_EXPECTANCY"] = "-0.30"
        env["ALPHA_UNIVERSE_EXPLORATION_MIN_WINRATE"] = "0.20"
        env["ALPHA_UNIVERSE_EXPLORATION_COOLDOWN_SEC"] = "300"
        env["ALPHA_UNIVERSE_EXPLORATION_ALLOC_SCALE"] = "0.20"
        env["ALPHA_UNIVERSE_EXPLORATION_MAX_ALLOC_USDT"] = "35"
        env["ALPHA_UNIVERSE_EXPLORATION_NET_TARGET_SCALE"] = "0.35"
        env["ALPHA_MICRO_EXPLORATION_ENABLE"] = "0"
        env["STRATEGY_BIAS_VOTES"] = "0"
        env["MOMENTUM_BIAS_ENABLE"] = "0"
        env["ALPHA_MICRO_EXPLORATION_MAX_SIGNALS"] = "1"
        env["ALPHA_MICRO_EXPLORATION_WEIGHT_SCALE"] = "0.25"
        env["ALPHA_MICRO_EXPLORATION_ALLOC_SCALE"] = "0.20"
        env["ALPHA_MICRO_EXPLORATION_NET_TARGET_SCALE"] = "0.20"
        env["ALPHA_MICRO_EXPLORATION_MIN_EXPECTANCY"] = "0.00"
        env["ALPHA_MICRO_EXPLORATION_MAX_ALLOC_USDT"] = "45"
        env["ALPHA_MICRO_EXPLORATION_IDLE_RELAX_SEC"] = "420"
        env["ALPHA_MICRO_EXPLORATION_IDLE_MIN_EXPECTANCY"] = "-0.30"
        env["ALPHA_MICRO_EXPLORATION_ENTRY_SCORE_MULT"] = "0.65"
        env["ALPHA_MICRO_EXPLORATION_ENTRY_VOL_MULT"] = "0.70"
        env["ALPHA_MICRO_EXPLORATION_ENTRY_VOTE_MIN"] = "1"
        env["ALPHA_MICRO_EXPLORATION_DISABLE_TREND"] = "1"
        env["ALPHA_MICRO_EXPLORATION_DISABLE_RANGE_BLOCK"] = "1"
        env["ALPHA_MICRO_EXPLORATION_EXIT_OVERRIDE_ENABLE"] = "1"
        env["ALPHA_MICRO_EXPLORATION_EXIT_STOP_LOSS_USDT"] = "0.22"
        env["ALPHA_MICRO_EXPLORATION_EXIT_TAKE_PROFIT_USDT"] = "0.70"
        env["GLOBAL_STRATEGY_ALPHA_ENABLE"] = "0"
        env["SYMBOL_STRATEGY_GUARD_ENABLE"] = "1"
        env["SYMBOL_STRATEGY_GUARD_WINDOW"] = "16"
        env["SYMBOL_STRATEGY_GUARD_MIN_TRADES"] = "3"
        env["SYMBOL_STRATEGY_GUARD_MIN_WINRATE"] = "0.40"
        env["SYMBOL_STRATEGY_GUARD_MAX_EXPECTANCY"] = "-0.05"
        env["SYMBOL_STRATEGY_GUARD_COOLDOWN_SEC"] = "1200"
        env["SYMBOL_STRATEGY_PERF_ENABLE"] = "1"
        env["SIDE_GUARD_ENABLE"] = "1"
        env["SIDE_GUARD_WINDOW"] = "12"
        env["SIDE_GUARD_MIN_TRADES"] = "2"
        env["SIDE_GUARD_MIN_WINRATE"] = "0.40"
        env["SIDE_GUARD_MAX_EXPECTANCY"] = "-0.05"
        env["SIDE_GUARD_COOLDOWN_SEC"] = "1200"
        env["ENTRY_REQUIRE_TREND_AND_VOL"] = "0"
        env["ENTRY_ALLOW_BUY"] = "1"
        env["ENTRY_ALLOW_SELL"] = "1"
        env["ENTRY_BUY_REQUIRE_TREND"] = "0"
        env["ENTRY_SELL_REQUIRE_TREND"] = "1"
        env["ENTRY_SIGNAL_SCORE_MIN"] = "0.21"
        env["ENTRY_SIGNAL_SCORE_MIN_BUY"] = "0.24"
        env["ENTRY_BUY_MIN_SIGNAL_SCORE"] = "0.24"
        env["ENTRY_SIGNAL_MIN_VOTES"] = "1"  # reverted: votes=2 cut trades w/o WR gain
        env["ENTRY_MAX_OPPOSITE_VOTES"] = "1"
        env["ENTRY_MIN_VOTE_DOMINANCE"] = "0.55"
        env["ENTRY_MIN_VOTE_DELTA"] = "0"
        env["ENTRY_VOLATILITY_MIN"] = "0.015"
        env["ENTRY_BUY_MIN_VOLATILITY"] = "0.015"
        env["ENTRY_RANGE_BLOCK_VOL"] = "0.012"
        env["ENTRY_MIN_PROFIT_FEE_MULT"] = "1.20"
        env["ENTRY_MIN_NET_USDT"] = "0.12"
        env["ENTRY_MIN_NET_TO_STOP_RATIO"] = "1.10"  # reverted: 1.50 cut trades
        env["ENTRY_SIDE_EXPECTANCY_MIN_TRADES"] = "5"  # cold-start bypass: was 2
        env["allocation_pct"] = "0.010"  # reverted: stop 0.010+alloc 0.020 = noise
        env["ALPHA_REQUIRE_POSITIVE_UNIVERSE"] = "0"  # disabled: 38 blocks, no WR gain
        env["EXIT_STOP_LOSS_USDT"] = "0.012"  # best: 0.008 too tight (mae up to -0.010)
        env["EXIT_STOP_LOSS_MODE"] = "gross"  # not affected by fee magnitude
        env["EXIT_SL_USDT_SIDE_EXPECTANCY_ENABLE"] = "0"  # adaptive SL bad
        env["EXIT_TAKE_PROFIT_USDT"] = "0.72"  # effectively disabled (unreachable)
        env["EXIT_TAKE_PROFIT_MODE"] = "net"
        env["EXIT_PRICE_SLTP_ENABLE"] = "0"
        env["MOMENTUM_EXHAUSTION_FILTER_ENABLE"] = "1"
        env["MOMENTUM_EXHAUSTION_Z_EXTREME"] = "3.0"
        env["MOMENTUM_EXHAUSTION_MAX_EXT_PCT"] = "0.0025"
        env["MOMENTUM_EXHAUSTION_VOL_SPIKE_RATIO"] = "3.0"
        env["MOMENTUM_EXHAUSTION_SPIKE_MIN_Z"] = "2.0"
        env["LOSS_COOLDOWN_SEC"] = "30"   # was 180: 3-min blackout killed trade_count
        env["EXECUTION_COOLDOWN_SEC"] = "15"  # faster re-entry after quality filter
        env["DECISION_CHANGE_COOLDOWN_SEC"] = "8"
        env["DECISION_HYSTERESIS_SCORE"] = "0.08"
        env["ENTRY_ALPHA_SELECTOR_WINDOW"] = "16"
        env["ENTRY_ALPHA_SELECTOR_MIN_TRADES"] = "3"
        env["ENTRY_ALPHA_SELECTOR_MIN_WINRATE"] = "0.40"
        env["ENTRY_ALPHA_SELECTOR_MIN_EXPECTANCY"] = "0.00"
        env["ENTRY_ALPHA_SELECTOR_BAD_WEIGHT_SCALE"] = "0.10"
        env["ENTRY_ALPHA_SELECTOR_GOOD_WEIGHT_SCALE"] = "1.10"
        env["ENTRY_ALPHA_SELECTOR_DROP_BAD"] = "1"
        env["ENTRY_ALPHA_SELECTOR_KEEP_MIN_SIGNALS"] = "0"
        env["ENTRY_ALPHA_SELECTOR_ENABLE"] = "0"  # runtime drop→alpha_univ_neg
        env["ENTRY_ADAPTIVE_RELAX_ENABLE"] = "1"
        env["ENTRY_ADAPTIVE_RELAX_AFTER_SEC"] = "240"
        env["ENTRY_ADAPTIVE_RELAX_SCORE_MULT"] = "0.88"
        env["ENTRY_ADAPTIVE_RELAX_VOL_MULT"] = "0.90"
        env["ENTRY_ADAPTIVE_RELAX_VOTE_MIN"] = "2"
        env["ENTRY_ADAPTIVE_RELAX_DISABLE_TREND"] = "0"
        # --- drain-stall fixes ---
        # Lower opposite-signal score so moderate reversals close positions
        # instead of being blocked by BLOCK_OPPOSITE_SIGNAL_STRENGTH.
        env["OPPOSITE_SIGNAL_SCORE"] = "0.35"      # was default 0.7
        env["OPPOSITE_SIGNAL_MIN_VOTES"] = "2"     # was default 3
        env["OPPOSITE_SIGNAL_MIN_HOLD_SEC"] = "20"  # was default 45
        # Hard-close any position that survives longer than 120 s.
        # 90 s was too aggressive: forced hard-closes poisoned PAPER_GATE.
        env["PAPER_AUTO_CLOSE_SEC"] = "20"    # best: 30s loses MFE to reversal
        env["PAPER_AUTO_CLOSE_HARD_SEC"] = "60"    # was 120: MFE leak
        # Disable the paper gate for KPI runs — hard-closes in the drain window
        # would otherwise trigger net_pnl_15m_negative_twice and block 300+
        # entries per run.
        env["PAPER_GATE_ENABLE"] = "0"             # disable gate in after variant
        # TrendFollowing pre-filter checks metrics.trend_strength which the
        # current signal generator does NOT populate — 57 candidates per 30 min
        # are rejected by a stale format check.  Disable to let them through to
        # the normal entry gate.
        env["ENTRY_TRENDFOLLOWING_FILTER_ENABLE"] = "0"
        # trend_mixed_edge_over_fee_gate fires when history_ready=False
        # which returns edge_net=0.0; set margin to -1 to pass zero-edge.
        env["TREND_MIXED_EDGE_SAFETY_MARGIN_USDT"] = "-1"
        # side_expectancy: runtime exp goes negative after 1 stop-loss → 83 blocks.
        # Set to -1.0 to disable (alpha selector already off, bootstrap filters).
        env["ENTRY_SIDE_EXPECTANCY_MIN"] = "-1.0"
        # post_green: PAPER-only post-green exits keep a bounded giveback trigger.
        env["PAPER_POST_GREEN_GIVEBACK_TRIGGER"] = "0.08"
        env.setdefault("RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS", "1")
    else:
        raise ValueError(f"Unknown variant: {variant}")
    if isinstance(variant_overrides, dict):
        for key, value in variant_overrides.items():
            k = str(key or "").strip()
            if not k:
                continue
            env[k] = str(value)
    return env


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


def _safe_float_value(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        val = float(value)
        if not math.isfinite(val):
            return None
        return val
    except Exception:
        return None


def _parse_metric_timestamp(value):
    if value in (None, ""):
        return None
    txt = str(value).strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(txt)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _seconds_between(start, end):
    start_dt = _parse_metric_timestamp(start)
    end_dt = _parse_metric_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    try:
        return max(0.0, (end_dt - start_dt).total_seconds())
    except Exception:
        return None


def _avg(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return (sum(vals) / len(vals)) if vals else None


def _median(values):
    vals = sorted(
        float(v) for v in values if v is not None and math.isfinite(float(v))
    )
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def _compute_max_drawdown(equity_values):
    if not equity_values:
        return 0.0
    peak = equity_values[0]
    max_dd = 0.0
    for value in equity_values:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _controlled_entry_cutoff_sec(duration_sec: int, paper_auto_close_sec: int) -> int:
    try:
        duration_val = max(1, int(duration_sec))
    except Exception:
        duration_val = 1
    try:
        auto_close_val = max(1, int(paper_auto_close_sec))
    except Exception:
        auto_close_val = 1
    # Keep a bounded terminal no-new-entry window, but never let it swallow
    # short controlled corridors where we still need sequential trades.
    cutoff_floor = max(10, auto_close_val)
    cutoff_target = max(cutoff_floor, auto_close_val * 2)
    cutoff_cap = max(15, int(duration_val * 0.25))
    return max(10, min(cutoff_target, cutoff_cap))


def _collect_metrics(db_path: Path) -> dict:
    empty_exit_metrics = {
        "win_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "expectancy": 0.0,
        "green_to_red_share": None,
        "fee_inversion_share": None,
        "share_ever_profitable": None,
        "exit_reason_distribution": {},
        "time_to_first_MFE": None,
        "time_to_first_MFE_median": None,
        "time_to_first_MFE_count": 0,
        "time_from_peak_to_close": None,
        "time_from_peak_to_close_median": None,
        "time_from_peak_to_close_count": 0,
    }
    if not db_path.exists():
        return {
            "db_exists": False,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
            **empty_exit_metrics,
        }

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    realized = []
    symbol_realized = {}
    exit_reasons = Counter()
    green_to_red_count = 0
    fee_inversion_count = 0
    ever_profitable_count = 0
    time_to_first_mfe_sec = []
    time_from_peak_to_close_sec = []
    decisions_count = 0
    equity_values = []
    event_counts = {}

    try:
        cur.execute("SELECT COUNT(*) FROM decisions")
        decisions_count = int(cur.fetchone()[0] or 0)
    except Exception:
        decisions_count = 0

    try:
        cur.execute("SELECT equity FROM equity ORDER BY id ASC")
        for (eq,) in cur.fetchall():
            try:
                equity_values.append(float(eq))
            except Exception:
                continue
    except Exception:
        equity_values = []

    try:
        cur.execute("SELECT timestamp, event, details FROM logs")
        rows = cur.fetchall()
        for log_ts, event, details_raw in rows:
            event_name = str(event or "")
            if event_name:
                event_counts[event_name] = event_counts.get(event_name, 0) + 1
            if event_name != "position_close":
                continue
            details = _parse_json_payload(details_raw)
            position = (
                details.get("position") if isinstance(details.get("position"), dict)
                else {}
            )
            pnl_decompose = (
                position.get("pnl_decompose")
                if isinstance(position.get("pnl_decompose"), dict)
                else details.get("pnl_decompose")
                if isinstance(details.get("pnl_decompose"), dict)
                else {}
            )
            pnl = details.get("realized_pnl")
            if pnl is None:
                pnl = position.get("realized_pnl")
            if pnl is None:
                pnl = position.get("realized_net")
            if pnl is None:
                pnl = pnl_decompose.get("net_pnl")
            pnl_val = _safe_float_value(pnl)
            if pnl_val is None:
                continue
            realized.append(pnl_val)
            symbol = details.get("symbol")
            if symbol is None:
                symbol = position.get("symbol")
            symbol_key = str(symbol or "UNKNOWN")
            symbol_realized.setdefault(symbol_key, []).append(pnl_val)

            exit_reason = (
                position.get("exit_reason")
                or position.get("close_reason")
                or details.get("exit_reason")
                or details.get("close_reason")
                or "UNKNOWN"
            )
            exit_reasons[str(exit_reason or "UNKNOWN")] += 1

            mfe = _safe_float_value(position.get("mfe"))
            if mfe is None:
                mfe = _safe_float_value(position.get("max_unrealized_pnl"))
            if mfe is None:
                mfe = _safe_float_value(details.get("mfe"))
            gross = _safe_float_value(pnl_decompose.get("gross_fill_pnl_model"))
            if gross is None:
                gross = _safe_float_value(details.get("gross_fill_pnl_model"))

            if mfe is not None and mfe > 0.0:
                ever_profitable_count += 1
                if pnl_val <= 0.0:
                    green_to_red_count += 1
            if gross is not None and gross > 0.0 and pnl_val <= 0.0:
                fee_inversion_count += 1

            open_ts = (
                position.get("timestamp")
                or position.get("opened_at")
                or position.get("open_timestamp")
                or position.get("entry_timestamp")
            )
            close_ts = (
                position.get("close_timestamp")
                or position.get("closed_at")
                or details.get("close_timestamp")
                or log_ts
            )
            first_mfe_ts = (
                position.get("first_positive_mfe_ts")
                or details.get("first_positive_mfe_ts")
            )
            peak_ts = (
                position.get("peak_mfe_ts")
                or position.get("max_unrealized_pnl_ts")
                or details.get("peak_mfe_ts")
                or details.get("max_unrealized_pnl_ts")
            )
            first_mfe_sec = _seconds_between(open_ts, first_mfe_ts)
            if first_mfe_sec is not None:
                time_to_first_mfe_sec.append(first_mfe_sec)
            peak_to_close_sec = _seconds_between(peak_ts, close_ts)
            if peak_to_close_sec is not None:
                time_from_peak_to_close_sec.append(peak_to_close_sec)
    except Exception:
        realized = []
        symbol_realized = {}
        event_counts = {}
        exit_reasons = Counter()
        green_to_red_count = 0
        fee_inversion_count = 0
        ever_profitable_count = 0
        time_to_first_mfe_sec = []
        time_from_peak_to_close_sec = []
    finally:
        conn.close()

    trade_count = len(realized)
    wins = sum(1 for x in realized if x > 0)
    gross_profit = sum(x for x in realized if x > 0)
    gross_loss_abs = abs(sum(x for x in realized if x < 0))
    net_pnl = sum(realized)
    max_dd = _compute_max_drawdown(equity_values)
    winrate = (wins / trade_count) if trade_count > 0 else 0.0
    avg_win = (gross_profit / wins) if wins > 0 else 0.0
    losses = sum(1 for x in realized if x < 0)
    avg_loss = (sum(x for x in realized if x < 0) / losses) if losses > 0 else 0.0
    expectancy = (net_pnl / trade_count) if trade_count > 0 else 0.0
    trade_denom = float(trade_count) if trade_count > 0 else None
    green_to_red_share = (
        green_to_red_count / trade_denom if trade_denom is not None else None
    )
    fee_inversion_share = (
        fee_inversion_count / trade_denom if trade_denom is not None else None
    )
    share_ever_profitable = (
        ever_profitable_count / trade_denom if trade_denom is not None else None
    )
    if gross_loss_abs > 0:
        profit_factor = gross_profit / gross_loss_abs
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    symbol_stats = {}
    for symbol, arr in symbol_realized.items():
        wins_s = sum(1 for x in arr if x > 0)
        losses_s = sum(1 for x in arr if x < 0)
        gp_s = sum(x for x in arr if x > 0)
        gl_s = abs(sum(x for x in arr if x < 0))
        if gl_s > 0:
            pf_s = gp_s / gl_s
        elif gp_s > 0:
            pf_s = float("inf")
        else:
            pf_s = 0.0
        symbol_stats[symbol] = {
            "trade_count": len(arr),
            "net_pnl": sum(arr),
            "winrate": (wins_s / len(arr)) if arr else 0.0,
            "win_rate": (wins_s / len(arr)) if arr else 0.0,
            "avg_win": (gp_s / wins_s) if wins_s > 0 else 0.0,
            "avg_loss": (
                sum(x for x in arr if x < 0) / losses_s
            ) if losses_s > 0 else 0.0,
            "expectancy": (sum(arr) / len(arr)) if arr else 0.0,
            "gross_profit": gp_s,
            "gross_loss_abs": gl_s,
            "profit_factor": pf_s,
            "wins": wins_s,
            "losses": losses_s,
        }

    return {
        "db_exists": True,
        "trade_count": trade_count,
        "net_pnl": net_pnl,
        "winrate": winrate,
        "win_rate": winrate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "max_drawdown": max_dd,
        "profit_factor": profit_factor,
        "gross_profit": gross_profit,
        "gross_loss_abs": gross_loss_abs,
        "green_to_red_share": green_to_red_share,
        "fee_inversion_share": fee_inversion_share,
        "share_ever_profitable": share_ever_profitable,
        "exit_reason_distribution": dict(sorted(exit_reasons.items())),
        "time_to_first_MFE": _avg(time_to_first_mfe_sec),
        "time_to_first_MFE_median": _median(time_to_first_mfe_sec),
        "time_to_first_MFE_count": len(time_to_first_mfe_sec),
        "time_from_peak_to_close": _avg(time_from_peak_to_close_sec),
        "time_from_peak_to_close_median": _median(time_from_peak_to_close_sec),
        "time_from_peak_to_close_count": len(time_from_peak_to_close_sec),
        "decisions_count": decisions_count,
        "equity_points": len(equity_values),
        "symbol_stats": symbol_stats,
        "event_counts": event_counts,
    }


def _load_entry_gate_summary_payloads(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT rowid, timestamp, event, details FROM logs "
            "WHERE event = ? ORDER BY rowid ASC",
            ("entry_gate_decision_summary",),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    payloads = []
    for row in rows or []:
        payload = _parse_json_payload(row["details"])
        if isinstance(payload, dict):
            payloads.append(
                {
                    "rowid": int(row[0]),
                    "timestamp": row[1],
                    "payload": payload,
                }
            )
    return payloads


def _load_diagnostic_trace_rows(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT rowid, timestamp, event, details FROM logs "
            "WHERE event = ? ORDER BY rowid ASC",
            ("diagnostic_gate_trace",),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    out = []
    for row in rows or []:
        payload = _parse_json_payload(row["details"])
        if isinstance(payload, dict):
            out.append(
                {
                    "rowid": int(row[0]),
                    "timestamp": row[1],
                    "payload": payload,
                }
            )
    return out


def _build_diagnostic_runtime_summary(
    *,
    db_path: Path,
    run_id: str,
    started_at_utc: str,
    ended_at_utc: str,
    variant: str,
    symbols: list[str],
    env_flags: dict,
    metrics: dict,
) -> dict:
    trace_rows = _load_diagnostic_trace_rows(db_path)
    summary_rows = _load_entry_gate_summary_payloads(db_path)
    total_trace_events = len(trace_rows)
    total_gate_blocked = 0
    total_gate_skipped = 0
    by_gate = {}
    top_blockers_counter = Counter()

    for row in trace_rows:
        payload = row["payload"]
        gate_name = str(payload.get("gate_name") or "").strip() or "unknown"
        gate_blocked = _coerce_bool(payload.get("gate_blocked"))
        gate_skipped = _coerce_bool(payload.get("gate_skipped"))
        skip_reason = payload.get("skip_reason")
        local_gate_reason_final = str(
            payload.get("local_gate_reason_final") or ""
        ).strip()
        if gate_blocked:
            total_gate_blocked += 1
        if gate_skipped:
            total_gate_skipped += 1
        gate_bucket = by_gate.setdefault(
            gate_name,
            {
                "gate_name": gate_name,
                "blocked_count": 0,
                "skipped_count": 0,
                "pass_through_count": 0,
                "skip_reason_counts": {},
            },
        )
        if gate_blocked:
            gate_bucket["blocked_count"] += 1
        if gate_skipped:
            gate_bucket["skipped_count"] += 1
            if skip_reason:
                gate_bucket["skip_reason_counts"][str(skip_reason)] = (
                    gate_bucket["skip_reason_counts"].get(str(skip_reason), 0) + 1
                )
        if not gate_blocked and not gate_skipped:
            gate_bucket["pass_through_count"] += 1
        if local_gate_reason_final:
            top_blockers_counter[local_gate_reason_final] += 1

    gate_trace_by_gate = sorted(by_gate.values(), key=lambda item: item["gate_name"])
    top_blockers_after_skip = [
        [reason, count]
        for reason, count in top_blockers_counter.most_common(20)
    ]
    admitted = 0
    blocked = 0
    top_local_gate_counter = Counter()
    for row in summary_rows:
        payload = row["payload"]
        if _coerce_bool(payload.get("final_allow")):
            admitted += 1
        else:
            blocked += 1
        local_reason = payload.get("local_gate_reason")
        if local_reason:
            top_local_gate_counter[str(local_reason)] += 1
    admission_outcome_summary = {
        "rows": len(summary_rows),
        "admitted": admitted,
        "blocked": blocked,
        "top_local_gate_reason": [
            [reason, count] for reason, count in top_local_gate_counter.most_common(10)
        ],
    }

    return {
        "run_metadata": {
            "run_id": run_id,
            "started_at": started_at_utc,
            "finished_at": ended_at_utc,
            "mode": "LIVE" if str(env_flags.get("LIVE", "0")) == "1" else "PAPER",
            "diagnostic_mode_enabled": str(env_flags.get("DIAGNOSTIC_MODE", "0"))
            == "1",
            "symbols": symbols,
            "variant": variant,
            "db_path": str(db_path),
        },
        "env_diagnostic_flags": {
            key: env_flags.get(key)
            for key in (
                "DIAGNOSTIC_MODE",
                "DIAG_DISABLE_NET_TARGET_GUARD",
                "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION",
                "DIAG_DISABLE_SIDE_GUARD",
                "DIAG_DISABLE_SIDE_EXPECTANCY",
            )
        },
        "gate_trace_summary": {
            "total_trace_events": total_trace_events,
            "total_gate_blocked": total_gate_blocked,
            "total_gate_skipped": total_gate_skipped,
        },
        "gate_trace_by_gate": gate_trace_by_gate,
        "top_blockers_after_skip": top_blockers_after_skip,
        "admission_outcome_summary": admission_outcome_summary,
        "runner_shutdown_reason": metrics.get("runner_shutdown_reason"),
        "runner_shutdown_ts": metrics.get("runner_shutdown_ts"),
        "runner_termination_trace": metrics.get("runner_termination_trace"),
    }


def _write_diagnostic_runtime_summary(report: dict, run_id: str) -> Path | None:
    try:
        diag_dir = WORKDIR / "artifacts" / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        stamp = str(run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
        out_path = diag_dir / f"diagnostic_runtime_summary_{stamp}.json"
        out_path.write_text(json.dumps(
            report, indent=2, ensure_ascii=True), encoding="utf-8")
        return out_path
    except Exception as exc:
        print(f"WARN: failed to write diagnostic runtime summary: {exc}")
        return None


def _run_variant(
    variant: str,
    duration_sec: int,
    run_id: str,
    *,
    use_mock: bool,
    market_type: str,
    run_symbols: str,
    paper_auto_open: bool,
    paper_auto_close_sec: int,
    equity_snapshot_sec: int,
    quality_profile: bool,
    alpha_bootstrap_source_db_url: str,
    alpha_bootstrap_source_db_glob: str,
    variant_overrides: dict | None = None,
) -> dict:
    db_path = TMP_DIR / f"controlled_kpi_{variant}_{run_id}.db"
    out_log = TMP_DIR / f"controlled_kpi_{variant}_{run_id}.out.log"
    err_log = TMP_DIR / f"controlled_kpi_{variant}_{run_id}.err.log"

    if db_path.exists():
        db_path.unlink()
    _init_db_schema(db_path)

    env = _variant_env(
        db_path,
        variant,
        use_mock=use_mock,
        market_type=market_type,
        run_symbols=run_symbols,
        paper_auto_open=paper_auto_open,
        paper_auto_close_sec=paper_auto_close_sec,
        equity_snapshot_sec=equity_snapshot_sec,
        quality_profile=quality_profile,
        alpha_bootstrap_source_db_url=alpha_bootstrap_source_db_url,
        alpha_bootstrap_source_db_glob=alpha_bootstrap_source_db_glob,
        variant_overrides=variant_overrides,
    )
    enqueue_window_sentinel = _sqlite_enqueue_window_sentinel_path(db_path)
    _clear_sqlite_enqueue_window_sentinel(db_path)
    env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"] = str(enqueue_window_sentinel)
    run_end_ts = time.time() + float(max(1, int(duration_sec)))
    env["CONTROLLED_RUN_END_TS"] = str(run_end_ts)
    try:
        reeval_grace_sec = max(
            0.0,
            float(env.get("RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC", "0") or 0.0),
        )
    except Exception:
        reeval_grace_sec = 0.0
    try:
        post_promotion_observation_enabled = (
            str(env.get("POST_PROMOTION_OBSERVATION_ENABLED", "1")).strip().lower()
            not in {"0", "false", "no", "off", ""}
        )
    except Exception:
        post_promotion_observation_enabled = True
    try:
        post_promotion_observation_max_sec = max(
            1.0,
            float(env.get("POST_PROMOTION_OBSERVATION_MAX_SEC", "15") or 15.0),
        )
    except Exception:
        post_promotion_observation_max_sec = 15.0
    try:
        post_promotion_observation_max_cycles = max(
            1,
            int(env.get("POST_PROMOTION_OBSERVATION_MAX_CYCLES", "3") or 3),
        )
    except Exception:
        post_promotion_observation_max_cycles = 3
    try:
        post_close_summary_grace_ticks = max(
            0,
            int(env.get("RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS", "0") or 0),
        )
    except Exception:
        post_close_summary_grace_ticks = 0
    try:
        post_close_summary_grace_timeout_sec = max(
            20.0,
            float(
                env.get(
                    "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC",
                    str(max(20.0, float(paper_auto_close_sec))),
                )
                or 0.0
            ),
        )
    except Exception:
        post_close_summary_grace_timeout_sec = max(20.0, float(paper_auto_close_sec))
    entry_cutoff_sec = min(
        _controlled_entry_cutoff_sec(duration_sec, paper_auto_close_sec),
        max(10, int(float(duration_sec))),
    )
    env.setdefault(
        "ENTRY_CUTOFF_BEFORE_END_SEC",
        str(entry_cutoff_sec),
    )
    cmd = [
        sys.executable,
        "-u",
        "-c",
        "from core.BotCore import run_bot; run_bot(simulate=True)",
    ]

    start_dt = datetime.now(timezone.utc)
    print(
        f"[{variant}] start={start_dt.isoformat()} target_sec={duration_sec} db={db_path}"  # noqa: E501
    )
    with out_log.open("w", encoding="utf-8") as out_f, err_log.open(
        "w", encoding="utf-8"
    ) as err_f:
        proc = subprocess.Popen(cmd, cwd=str(WORKDIR), env=env,
                                stdout=out_f, stderr=err_f)
        start = time.time()
        last_heartbeat = -1
        close_requested = False
        close_wait_deadline = None
        post_close_deadline = None
        final_drain_deadline = None
        close_symbols = [s.strip() for s in str(run_symbols).split(",") if s.strip()]
        reeval_probe = {
            "promotion_count": 0,
            "promoted_buckets": [],
            "promotion_runtime_seq": None,
            "real_post_promotion_read_count": 0,
            "real_post_promotion_read_buckets": [],
            "gate_read_after_promotion_runtime_seq": None,
            "timing_replay_only_buckets": [],
            "observed_real_post_promotion_read": False,
        }
        runner_diagnostics = []
        drain_tick_after_enqueue = False
        # Always allow one post-close visibility tick so the runner can
        # observe the promoted bucket after the close flush without any
        # research-only flag.
        single_post_close_eval_tick_enabled = True
        single_post_close_eval_tick_armed = False
        single_post_close_eval_tick_consumed = False
        post_close_extra_tick_triggered = False
        post_close_extra_tick_count = 0
        evaluation_phase = "normal"
        post_promotion_window_armed = False
        post_promotion_window_armed_at = None
        post_promotion_window_entered = False
        post_promotion_window_cycle_count = 0
        post_promotion_window_exit_reason = None
        post_promotion_reeval_requested = False
        post_promotion_reeval_request_runtime_seq = None
        post_promotion_reeval_dispatch_entered = False
        post_promotion_reeval_completed = False
        post_promotion_reeval_result = None
        post_promotion_reeval_exit_reason = None
        post_promotion_forced_cycle_requested = False
        post_promotion_forced_cycle_request_runtime_seq = None
        post_promotion_forced_cycle_request_reason = None
        post_promotion_forced_cycle_trigger_mode = None
        post_promotion_forced_cycle_started = False
        post_promotion_forced_cycle_completed = False
        post_promotion_forced_cycle_failed = False
        post_promotion_forced_cycle_result = None
        post_promotion_forced_cycle_exit_reason = None
        post_promotion_execution_lock = False
        post_promotion_close_requests_pending = False
        post_close_summary_grace_enabled = post_close_summary_grace_ticks > 0
        post_close_summary_grace_armed = False
        post_close_summary_grace_armed_at = None
        post_close_summary_grace_deadline = None
        post_close_summary_grace_tick_count = 0
        post_close_summary_grace_release_reason = None
        post_close_summary_tail_entry_gate_baseline = 0
        post_close_summary_tail_emit_done_baseline = 0
        post_close_summary_tail_risk_decision_baseline = 0
        termination_reason = None
        shutdown_classification = None
        last_drain_snapshot = None
        last_drain_progress_ts = None
        process_stop_mode = None
        process_returncode_raw = None
        final_close_drain_snapshot = None
        final_shutdown_recheck = None
        final_close_drain_retry_attempted = False
        close_drain_retry_count = 0
        close_drain_retry_max_attempts = 3
        close_drain_retry_interval_sec = max(5.0, float(paper_auto_close_sec))
        close_drain_last_retry_ts = None

        def _runner_diag(event_name: str, **payload):
            record = {
                "event": event_name,
                "run_ts": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
            runner_diagnostics.append(record)
            print(f"[{variant}] {event_name} {json.dumps(record, sort_keys=True, default=str)}")  # noqa: E501

        try:
            while True:
                if proc.poll() is not None:
                    termination_reason = "proc_exited"
                    shutdown_classification = shutdown_classification or termination_reason  # noqa: E501
                    _runner_diag(
                        "runner_termination",
                        close_requested=close_requested,
                        close_wait_deadline=close_wait_deadline,
                        post_close_deadline=post_close_deadline,
                        final_drain_deadline=final_drain_deadline,
                        pending_positions=_pending_open_positions(db_path),
                        close_drain_snapshot=_close_drain_snapshot(db_path),
                        drain_tick_after_enqueue=drain_tick_after_enqueue,
                        termination_reason=termination_reason,
                    )
                    break
                elapsed = time.time() - start
                elapsed_min = int(elapsed // 60)
                if elapsed_min != last_heartbeat:
                    last_heartbeat = elapsed_min
                    print(f"[{variant}] elapsed_min={elapsed_min} pid={proc.pid}")
                if elapsed >= duration_sec:
                    if not close_requested:
                        pending_post_promo_probe = _probe_real_post_promotion_reevaluation(  # noqa: E501
                            db_path)
                        pending_positions_at_close = _pending_open_positions(
                            db_path
                        )
                        close_flush_deferral_active = (
                            post_promotion_observation_enabled
                            and int(pending_post_promo_probe.get("promotion_count") or 0) > 0  # noqa: E501
                            and not bool(
                                pending_post_promo_probe.get(
                                    "observed_real_post_promotion_read"
                                )
                            )
                            and not post_promotion_forced_cycle_completed
                            and int(pending_positions_at_close or 0) == 0
                        )
                        flush_grace_sec = min(
                            45.0, max(10.0, float(paper_auto_close_sec))
                        )
                        close_requested = True
                        close_wait_deadline = time.time() + flush_grace_sec
                        post_close_deadline = time.time() + flush_grace_sec + max(
                            0.0, reeval_grace_sec
                        )
                        if close_flush_deferral_active:
                            post_promotion_close_requests_pending = True
                            _runner_diag(
                                "runner_close_requests_deferred",
                                deferred_reason="post_promotion_forced_cycle_pending",
                                promotion_runtime_seq=pending_post_promo_probe.get(
                                    "promotion_runtime_seq"
                                ),
                                gate_read_after_promotion_runtime_seq=pending_post_promo_probe.get(  # noqa: E501
                                    "gate_read_after_promotion_runtime_seq"
                                ),
                                close_wait_deadline=close_wait_deadline,
                                post_close_deadline=post_close_deadline,
                                pending_positions=pending_positions_at_close,
                                drain_tick_after_enqueue=drain_tick_after_enqueue,
                                termination_reason=termination_reason,
                            )
                            print(
                                f"[{variant}] close_requests_deferred=1 grace_sec={int(max(0.0, close_wait_deadline - time.time()))}"  # noqa: E501
                            )
                        else:
                            req_count = _enqueue_close_requests(
                                db_path,
                                close_symbols,
                                reason="controlled_kpi_window_end",
                                diag_cb=_runner_diag,
                            )
                            _runner_diag(
                                "runner_close_requests_enqueued",
                                close_requested=close_requested,
                                req_count=req_count,
                                close_wait_deadline=close_wait_deadline,
                                post_close_deadline=post_close_deadline,
                                pending_positions=pending_positions_at_close,
                                drain_tick_after_enqueue=drain_tick_after_enqueue,
                                termination_reason=termination_reason,
                                close_deferral_bypassed=bool(
                                    post_promotion_observation_enabled
                                    and int(
                                        pending_post_promo_probe.get(
                                            "promotion_count"
                                        )
                                        or 0
                                    )
                                    > 0
                                    and not bool(
                                        pending_post_promo_probe.get(
                                            "observed_real_post_promotion_read"
                                        )
                                    )
                                    and not post_promotion_forced_cycle_completed
                                    and int(pending_positions_at_close or 0) > 0
                                ),
                            )
                            print(
                                f"[{variant}] close_requests={req_count} "
                                f"grace_sec={int(max(0.0, close_wait_deadline - time.time()))}"  # noqa: E501
                            )
                            if reeval_grace_sec > 0:
                                print(
                                    f"[{variant}] reeval_grace_enabled={int(reeval_grace_sec)}"  # noqa: E501
                                )
                    elif close_wait_deadline is not None:
                        drain_tick_after_enqueue = True
                        now_ts = time.time()
                        drain_snapshot = _close_drain_snapshot(db_path)
                        final_close_drain_snapshot = (
                            dict(drain_snapshot) if isinstance(
                                drain_snapshot, dict) else None
                        )
                        pending_positions = (
                            int(drain_snapshot.get("pending_positions") or 0)
                            if isinstance(drain_snapshot, dict)
                            else None
                        )
                        close_request_backlog = (
                            int(drain_snapshot.get("close_request_backlog") or 0)
                            if isinstance(drain_snapshot, dict)
                            else None
                        )
                        close_request_backlog_raw = (
                            int(drain_snapshot.get("close_request_backlog_raw") or 0)
                            if isinstance(drain_snapshot, dict)
                            else None
                        )
                        duplicate_close_request_count = (
                            int(drain_snapshot.get("duplicate_close_request_count") or 0)  # noqa: E501
                            if isinstance(drain_snapshot, dict)
                            else None
                        )
                        close_count = (
                            int(drain_snapshot.get("position_close_count") or 0)
                            if isinstance(drain_snapshot, dict)
                            else None
                        )
                        open_count = (
                            int(drain_snapshot.get("position_open_count") or 0)
                            if isinstance(drain_snapshot, dict)
                            else None
                        )
                        close_drain_progress_observed = False
                        if isinstance(drain_snapshot, dict):
                            if last_drain_snapshot is None:
                                last_drain_snapshot = dict(drain_snapshot)
                                last_drain_progress_ts = now_ts
                            else:
                                prev_close_count = int(
                                    last_drain_snapshot.get("position_close_count") or 0
                                )
                                prev_pending_positions = int(
                                    last_drain_snapshot.get("pending_positions") or 0
                                )
                                prev_backlog = int(
                                    last_drain_snapshot.get(
                                        "close_request_backlog") or 0
                                )
                                close_drain_progress_observed = bool(
                                    (close_count is not None and close_count > prev_close_count) or (  # noqa: E501
                                        pending_positions is not None and pending_positions < prev_pending_positions) or (  # noqa: E501
                                        close_request_backlog is not None and close_request_backlog < prev_backlog))  # noqa: E501
                                if close_drain_progress_observed:
                                    last_drain_snapshot = dict(drain_snapshot)
                                    last_drain_progress_ts = now_ts
                                    if final_drain_deadline is not None:
                                        close_drain_extension_sec = max(
                                            20.0,
                                            float(paper_auto_close_sec) * 2.0,
                                        )
                                        final_drain_deadline = max(
                                            float(final_drain_deadline),
                                            float(now_ts)
                                            + float(close_drain_extension_sec),
                                        )
                                        _runner_diag(
                                            "runner_close_drain_deadline_extended",
                                            final_drain_deadline=final_drain_deadline,
                                            close_drain_extension_sec=(
                                                close_drain_extension_sec
                                            ),
                                            pending_positions=pending_positions,
                                            close_request_backlog=close_request_backlog,
                                            close_count=close_count,
                                            open_count=open_count,
                                            drain_tick_after_enqueue=(
                                                drain_tick_after_enqueue
                                            ),
                                            termination_reason=termination_reason,
                                        )
                                    _runner_diag(
                                        "runner_close_drain_progress",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_request_backlog_raw=close_request_backlog_raw,  # noqa: E501
                                        duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                        _runner_diag(
                            "runner_close_wait_tick",
                            close_requested=close_requested,
                            close_wait_deadline=close_wait_deadline,
                            post_close_deadline=post_close_deadline,
                            pending_positions=pending_positions,
                            close_request_backlog=close_request_backlog,
                            close_request_backlog_raw=close_request_backlog_raw,
                            duplicate_close_request_count=duplicate_close_request_count,
                            close_count=close_count,
                            open_count=open_count,
                            drain_tick_after_enqueue=drain_tick_after_enqueue,
                            termination_reason=termination_reason,
                        )
                        if (
                            post_promotion_close_requests_pending
                            and pending_positions is not None
                            and int(pending_positions or 0) > 0
                        ):
                            release_symbols = _pending_open_symbols(db_path) or []
                            if not release_symbols:
                                release_symbols = list(close_symbols)
                            req_count = _enqueue_close_requests(
                                db_path,
                                release_symbols,
                                reason="controlled_kpi_shutdown_pending_positions",
                                diag_cb=_runner_diag,
                            )
                            post_promotion_close_requests_pending = False
                            _runner_diag(
                                "runner_close_requests_released_for_pending_positions",
                                close_requested=close_requested,
                                req_count=req_count,
                                release_symbols=release_symbols,
                                close_wait_deadline=close_wait_deadline,
                                post_close_deadline=post_close_deadline,
                                pending_positions=pending_positions,
                                close_request_backlog=close_request_backlog,
                                close_request_backlog_raw=close_request_backlog_raw,
                                duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                close_count=close_count,
                                open_count=open_count,
                                drain_tick_after_enqueue=drain_tick_after_enqueue,
                                termination_reason=termination_reason,
                            )
                            print(
                                f"[{variant}] "
                                f"close_requests_released_for_pending_positions "
                                f"req_count={req_count} "
                                f"pending_positions={pending_positions}"
                            )
                            continue
                        if (
                            isinstance(drain_snapshot, dict)
                            and pending_positions is not None
                            and pending_positions > 0
                            and close_request_backlog == 0
                            and not post_promotion_close_requests_pending
                            and close_drain_retry_count < close_drain_retry_max_attempts
                        ):
                            retry_due = (
                                close_drain_last_retry_ts is None
                                or (now_ts - float(close_drain_last_retry_ts))
                                >= float(close_drain_retry_interval_sec)
                            )
                            if retry_due:
                                retry_req_count = _enqueue_close_requests(
                                    db_path,
                                    close_symbols,
                                    reason="controlled_kpi_close_drain_retry",
                                    diag_cb=_runner_diag,
                                )
                                close_drain_retry_count += 1
                                close_drain_last_retry_ts = now_ts
                                _runner_diag(
                                    "runner_close_drain_retry_enqueued",
                                    close_requested=close_requested,
                                    close_wait_deadline=close_wait_deadline,
                                    post_close_deadline=post_close_deadline,
                                    pending_positions=pending_positions,
                                    close_request_backlog=close_request_backlog,
                                    close_request_backlog_raw=close_request_backlog_raw,
                                    close_count=close_count,
                                    open_count=open_count,
                                    retry_req_count=retry_req_count,
                                    close_drain_retry_count=close_drain_retry_count,
                                    close_drain_retry_max_attempts=(
                                        close_drain_retry_max_attempts
                                    ),
                                    close_drain_retry_interval_sec=(
                                        close_drain_retry_interval_sec
                                    ),
                                    drain_tick_after_enqueue=drain_tick_after_enqueue,
                                    termination_reason=termination_reason,
                                )
                        if reeval_grace_sec > 0:
                            reeval_probe = _probe_real_post_promotion_reevaluation(
                                db_path
                            )
                        elif post_promotion_observation_enabled:
                            reeval_probe = _probe_real_post_promotion_reevaluation(
                                db_path
                            )
                        if (
                            post_promotion_observation_enabled
                            and not post_promotion_window_armed
                            and int(reeval_probe.get("promotion_count") or 0) > 0
                            and not bool(
                                reeval_probe.get("observed_real_post_promotion_read")
                            )
                        ):
                            post_promotion_window_armed = True
                            post_promotion_window_armed_at = time.time()
                            post_promotion_window_cycle_count = 0
                            post_promotion_window_entered = False
                            post_promotion_window_exit_reason = None
                            _runner_diag(
                                "post_promotion_window_armed",
                                promotion_runtime_seq=reeval_probe.get(
                                    "promotion_runtime_seq"
                                ),
                                gate_read_after_promotion_runtime_seq=reeval_probe.get(
                                    "gate_read_after_promotion_runtime_seq"
                                ),
                                max_seconds=post_promotion_observation_max_sec,
                                max_cycles=post_promotion_observation_max_cycles,
                            )
                        summary_grace_state = None
                        summary_grace_defer_shutdown = False
                        post_promotion_window_defer_shutdown = False
                        if (
                            post_promotion_window_armed
                            and post_promotion_window_exit_reason is None
                            and pending_positions == 0
                        ):
                            if not post_promotion_window_entered:
                                post_promotion_window_entered = True
                                post_promotion_window_armed_at = time.time()
                                _runner_diag(
                                    "post_promotion_window_enter",
                                    promotion_runtime_seq=reeval_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                    max_seconds=post_promotion_observation_max_sec,
                                    max_cycles=post_promotion_observation_max_cycles,
                                )
                            if not post_promotion_reeval_requested:
                                promotion_ctx = _probe_latest_canonical_promotion(
                                    db_path)
                                if isinstance(promotion_ctx, dict):
                                    request_payload = {
                                        "symbol": promotion_ctx.get("symbol"),
                                        "strategy": promotion_ctx.get("strategy"),
                                        "side": promotion_ctx.get("side"),
                                        "canonical_key": promotion_ctx.get("canonical_key"),  # noqa: E501
                                        "correlation_id": promotion_ctx.get("correlation_id"),  # noqa: E501
                                        "promotion_runtime_seq": promotion_ctx.get("promotion_runtime_seq"),  # noqa: E501
                                        "requested_by": "controlled_kpi_runner",
                                        "request_reason": "post_promotion_bounded_reeval",  # noqa: E501
                                    }
                                    req_runtime_seq = _enqueue_post_promotion_reeval_request(  # noqa: E501
                                        db_path, request_payload, diag_cb=_runner_diag, )  # noqa: E501
                                    if req_runtime_seq is not None:
                                        post_promotion_reeval_requested = True
                                        post_promotion_reeval_request_runtime_seq = int(
                                            req_runtime_seq)
                                        post_promotion_reeval_result = "request_enqueued"  # noqa: E501
                                    else:
                                        post_promotion_reeval_result = "request_enqueue_failed"  # noqa: E501
                            if (
                                post_promotion_reeval_requested
                                and not post_promotion_reeval_dispatch_entered
                            ):
                                post_promotion_reeval_dispatch_entered = True
                                _runner_diag(
                                    "post_promotion_reeval_dispatch_enter",
                                    promotion_runtime_seq=reeval_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    reeval_runtime_seq=post_promotion_reeval_request_runtime_seq,  # noqa: E501
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                )
                            post_promotion_window_cycle_count += 1
                            elapsed_window_sec = max(
                                0.0,
                                float(time.time() -
                                      (post_promotion_window_armed_at or time.time())),
                            )
                            if (
                                reeval_probe.get("reeval_runtime_seq") is not None
                                and not post_promotion_reeval_completed
                            ):
                                post_promotion_reeval_completed = True
                                post_promotion_reeval_result = "reevaluation_completed"
                                _runner_diag(
                                    "post_promotion_reeval_completed",
                                    promotion_runtime_seq=reeval_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    reeval_runtime_seq=reeval_probe.get(
                                        "reeval_runtime_seq"
                                    ),
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                    post_promotion_reeval_result=post_promotion_reeval_result,  # noqa: E501
                                )
                            forced_cycle_probe = _probe_forced_post_promotion_cycle(
                                db_path)
                            if _should_request_post_promotion_forced_cycle(
                                post_promotion_reeval_completed=(
                                    post_promotion_reeval_completed
                                ),
                                post_promotion_reeval_result=(
                                    post_promotion_reeval_result
                                ),
                                post_promotion_forced_cycle_requested=(
                                    post_promotion_forced_cycle_requested
                                ),
                            ):
                                promotion_ctx = _probe_latest_canonical_promotion(
                                    db_path)
                                if isinstance(promotion_ctx, dict):
                                    trigger_contract = (
                                        _resolve_post_promotion_forced_cycle_trigger(
                                            post_promotion_reeval_completed=(
                                                post_promotion_reeval_completed
                                            ),
                                            post_promotion_reeval_result=(
                                                post_promotion_reeval_result
                                            ),
                                        )
                                    )
                                    post_promotion_forced_cycle_trigger_mode = str(
                                        trigger_contract.get("mode")
                                        or "after_unknown"
                                    ).strip()
                                    post_promotion_forced_cycle_request_reason = str(
                                        trigger_contract.get("request_reason")
                                        or "post_promotion_forced_cycle"
                                    ).strip()
                                    forced_cycle_request_payload = {
                                        "symbol": promotion_ctx.get("symbol"),
                                        "strategy": promotion_ctx.get("strategy"),
                                        "side": promotion_ctx.get("side"),
                                        "canonical_key": promotion_ctx.get("canonical_key"),  # noqa: E501
                                        "correlation_id": promotion_ctx.get("correlation_id"),  # noqa: E501
                                        "promotion_runtime_seq": promotion_ctx.get("promotion_runtime_seq"),  # noqa: E501
                                        "requested_by": "controlled_kpi_runner",
                                        "request_reason": (
                                            post_promotion_forced_cycle_request_reason
                                        ),
                                    }
                                    forced_cycle_req_runtime_seq = _enqueue_post_promotion_force_cycle_request(  # noqa: E501
                                        db_path, forced_cycle_request_payload, diag_cb=_runner_diag, )  # noqa: E501
                                    if forced_cycle_req_runtime_seq is not None:
                                        post_promotion_forced_cycle_requested = True
                                        post_promotion_forced_cycle_request_runtime_seq = int(  # noqa: E501
                                            forced_cycle_req_runtime_seq)
                                        post_promotion_execution_lock = True
                                        _runner_diag(
                                            "forced_cycle_requested",
                                            promotion_runtime_seq=promotion_ctx.get(
                                                "promotion_runtime_seq"
                                            ),
                                            forced_cycle_request_runtime_seq=post_promotion_forced_cycle_request_runtime_seq,  # noqa: E501
                                            forced_cycle_request_reason=post_promotion_forced_cycle_request_reason,  # noqa: E501
                                            forced_cycle_trigger_mode=post_promotion_forced_cycle_trigger_mode,  # noqa: E501
                                            forced_cycle_exit_reason=None,
                                        )
                                    else:
                                        post_promotion_forced_cycle_failed = True
                                        post_promotion_forced_cycle_result = "enqueue_failed"  # noqa: E501
                                        post_promotion_forced_cycle_exit_reason = "enqueue_failed"  # noqa: E501
                                        _runner_diag(
                                            "forced_cycle_failed",
                                            promotion_runtime_seq=promotion_ctx.get(
                                                "promotion_runtime_seq"
                                            ),
                                            forced_cycle_request_runtime_seq=None,
                                            forced_cycle_request_reason=post_promotion_forced_cycle_request_reason,  # noqa: E501
                                            forced_cycle_trigger_mode=post_promotion_forced_cycle_trigger_mode,  # noqa: E501
                                            forced_cycle_exit_reason="enqueue_failed",
                                        )
                            forced_cycle_probe = _probe_forced_post_promotion_cycle(
                                db_path)
                            if forced_cycle_probe.get(
                                    "started") and not post_promotion_forced_cycle_started:  # noqa: E501
                                post_promotion_forced_cycle_started = True
                                _runner_diag(
                                    "forced_cycle_started",
                                    promotion_runtime_seq=forced_cycle_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    forced_cycle_request_runtime_seq=forced_cycle_probe.get(  # noqa: E501
                                        "forced_cycle_request_runtime_seq"
                                    ),
                                    forced_cycle_runtime_seq=forced_cycle_probe.get(
                                        "forced_cycle_runtime_seq"
                                    ),
                                    forced_cycle_exit_reason=forced_cycle_probe.get(
                                        "forced_cycle_exit_reason"
                                    ),
                                )
                            if forced_cycle_probe.get(
                                    "completed") and not post_promotion_forced_cycle_completed:  # noqa: E501
                                post_promotion_forced_cycle_completed = True
                                post_promotion_forced_cycle_result = forced_cycle_probe.get(  # noqa: E501
                                    "forced_cycle_result_classification"
                                ) or "forced_cycle_completed"
                                post_promotion_forced_cycle_exit_reason = forced_cycle_probe.get(  # noqa: E501
                                    "forced_cycle_exit_reason") or "emit_done"
                                post_promotion_execution_lock = False
                                _runner_diag(
                                    "forced_cycle_completed",
                                    promotion_runtime_seq=forced_cycle_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    forced_cycle_request_runtime_seq=forced_cycle_probe.get(  # noqa: E501
                                        "forced_cycle_request_runtime_seq"
                                    ),
                                    forced_cycle_runtime_seq=forced_cycle_probe.get(
                                        "forced_cycle_runtime_seq"
                                    ),
                                    forced_cycle_exit_reason=post_promotion_forced_cycle_exit_reason,  # noqa: E501
                                    forced_cycle_result_classification=post_promotion_forced_cycle_result,  # noqa: E501
                                )
                            if forced_cycle_probe.get(
                                    "failed") and not post_promotion_forced_cycle_failed:  # noqa: E501
                                post_promotion_forced_cycle_failed = True
                                post_promotion_forced_cycle_result = forced_cycle_probe.get(  # noqa: E501
                                    "forced_cycle_result_classification"
                                ) or "forced_cycle_failed"
                                post_promotion_forced_cycle_exit_reason = forced_cycle_probe.get(  # noqa: E501
                                    "forced_cycle_exit_reason") or "forced_cycle_failed"
                                post_promotion_execution_lock = False
                                _runner_diag(
                                    "forced_cycle_failed",
                                    promotion_runtime_seq=forced_cycle_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    forced_cycle_request_runtime_seq=forced_cycle_probe.get(  # noqa: E501
                                        "forced_cycle_request_runtime_seq"
                                    ),
                                    forced_cycle_runtime_seq=forced_cycle_probe.get(
                                        "forced_cycle_runtime_seq"
                                    ),
                                    forced_cycle_exit_reason=post_promotion_forced_cycle_exit_reason,  # noqa: E501
                                    exception_class=None,
                                    exception_message=None,
                                )
                            if bool(
                                    reeval_probe.get("observed_real_post_promotion_read")):  # noqa: E501
                                post_promotion_window_exit_reason = "first_post_promotion_gate_read_observed"  # noqa: E501
                                post_promotion_reeval_result = "gate_read_observed"
                            elif post_promotion_forced_cycle_completed or post_promotion_forced_cycle_failed:  # noqa: E501
                                post_promotion_window_exit_reason = post_promotion_forced_cycle_exit_reason or "forced_cycle_completed"  # noqa: E501
                                if post_promotion_forced_cycle_failed and not post_promotion_forced_cycle_completed:  # noqa: E501
                                    post_promotion_reeval_result = post_promotion_forced_cycle_result or "forced_cycle_failed"  # noqa: E501
                                elif post_promotion_forced_cycle_completed:
                                    post_promotion_reeval_result = post_promotion_forced_cycle_result or "forced_cycle_completed"  # noqa: E501
                            elif post_promotion_execution_lock:
                                post_promotion_window_defer_shutdown = True
                                _runner_diag(
                                    "runner_shutdown_deferred",
                                    deferred_reason="post_promotion_execution_lock_active",  # noqa: E501
                                    promotion_runtime_seq=forced_cycle_probe.get(
                                        "promotion_runtime_seq"
                                    ) or reeval_probe.get("promotion_runtime_seq"),
                                    reeval_runtime_seq=(
                                        forced_cycle_probe.get(
                                            "forced_cycle_request_runtime_seq")
                                        or post_promotion_reeval_request_runtime_seq
                                    ),
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                    window_cycle=post_promotion_window_cycle_count,
                                    window_elapsed_sec=elapsed_window_sec,
                                    window_max_seconds=post_promotion_observation_max_sec,  # noqa: E501
                                    window_max_cycles=post_promotion_observation_max_cycles,  # noqa: E501
                                )
                            elif (
                                not (
                                    post_promotion_reeval_requested
                                    and not post_promotion_reeval_completed
                                    and not bool(
                                        reeval_probe.get(
                                            "observed_real_post_promotion_read"
                                        )
                                    )
                                )
                                and (
                                    post_promotion_window_cycle_count
                                    >= post_promotion_observation_max_cycles
                                )
                            ):
                                post_promotion_window_exit_reason = "max_cycles_reached"
                                post_promotion_reeval_result = post_promotion_reeval_result or "reevaluation_timeout_no_gate_read"  # noqa: E501
                            elif elapsed_window_sec >= post_promotion_observation_max_sec:  # noqa: E501
                                post_promotion_window_exit_reason = "max_seconds_reached"  # noqa: E501
                                post_promotion_reeval_result = post_promotion_reeval_result or "reevaluation_timeout_no_gate_read"  # noqa: E501
                            else:
                                post_promotion_window_defer_shutdown = True
                                _runner_diag(
                                    "runner_shutdown_deferred",
                                    deferred_reason="post_promotion_window_active",
                                    promotion_runtime_seq=reeval_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    reeval_runtime_seq=(
                                        reeval_probe.get("reeval_runtime_seq")
                                        or post_promotion_reeval_request_runtime_seq
                                    ),
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                    window_cycle=post_promotion_window_cycle_count,
                                    window_elapsed_sec=elapsed_window_sec,
                                    window_max_seconds=post_promotion_observation_max_sec,  # noqa: E501
                                    window_max_cycles=post_promotion_observation_max_cycles,  # noqa: E501
                                )
                            if (
                                post_promotion_close_requests_pending
                                and post_promotion_window_exit_reason is not None
                            ):
                                req_count = _enqueue_close_requests(
                                    db_path,
                                    close_symbols,
                                    reason="controlled_kpi_window_end",
                                    diag_cb=_runner_diag,
                                )
                                post_promotion_close_requests_pending = False
                                _runner_diag(
                                    "runner_close_requests_enqueued",
                                    close_requested=close_requested,
                                    req_count=req_count,
                                    close_wait_deadline=close_wait_deadline,
                                    post_close_deadline=post_close_deadline,
                                    pending_positions=_pending_open_positions(db_path),
                                    drain_tick_after_enqueue=drain_tick_after_enqueue,
                                    termination_reason=termination_reason,
                                )
                                print(
                                    f"[{variant}] close_requests={req_count} "
                                    f"grace_sec={int(max(0.0, close_wait_deadline - time.time()))}"  # noqa: E501
                                )
                                if reeval_grace_sec > 0:
                                    print(
                                        f"[{variant}] reeval_grace_enabled={int(reeval_grace_sec)}"  # noqa: E501
                                    )
                            if post_promotion_window_exit_reason is not None:
                                post_promotion_reeval_exit_reason = (
                                    post_promotion_window_exit_reason
                                )
                                _runner_diag(
                                    "post_promotion_reeval_dispatch_exit",
                                    promotion_runtime_seq=reeval_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    reeval_runtime_seq=(
                                        forced_cycle_probe.get(
                                            "forced_cycle_request_runtime_seq")
                                        or reeval_probe.get("reeval_runtime_seq")
                                        or post_promotion_reeval_request_runtime_seq
                                    ),
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                    post_promotion_reeval_result=post_promotion_reeval_result,  # noqa: E501
                                    reeval_exit_reason=post_promotion_window_exit_reason,  # noqa: E501
                                )
                                _runner_diag(
                                    "post_promotion_window_exit",
                                    promotion_runtime_seq=reeval_probe.get(
                                        "promotion_runtime_seq"
                                    ),
                                    reeval_runtime_seq=(
                                        forced_cycle_probe.get(
                                            "forced_cycle_request_runtime_seq")
                                        or reeval_probe.get("reeval_runtime_seq")
                                        or post_promotion_reeval_request_runtime_seq
                                    ),
                                    gate_read_after_promotion_runtime_seq=reeval_probe.get(  # noqa: E501
                                        "gate_read_after_promotion_runtime_seq"
                                    ),
                                    window_cycle=post_promotion_window_cycle_count,
                                    window_elapsed_sec=elapsed_window_sec,
                                    window_exit_reason=post_promotion_window_exit_reason,  # noqa: E501
                                )
                        if post_close_summary_grace_enabled:
                            summary_grace_state = _probe_post_close_summary_grace(
                                db_path
                            )
                            summary_entry_count = int(
                                summary_grace_state.get(
                                    "entry_gate_decision_summary_count")
                                or 0
                            )
                            summary_emit_done_count = int(
                                summary_grace_state.get(
                                    "post_close_summary_emit_done_count")
                                or 0
                            )
                            summary_risk_decision_count = int(
                                summary_grace_state.get("risk_decision_count") or 0
                            )
                            require_fresh_tail_cycle = bool(
                                single_post_close_eval_tick_consumed
                            )
                            fresh_tail_cycle_complete = bool(
                                summary_emit_done_count
                                > post_close_summary_tail_emit_done_baseline
                                and summary_risk_decision_count
                                > post_close_summary_tail_risk_decision_baseline
                                and summary_entry_count
                                > post_close_summary_tail_entry_gate_baseline
                                and summary_risk_decision_count >= summary_entry_count
                            )
                            summary_complete_for_release = bool(
                                fresh_tail_cycle_complete
                                if require_fresh_tail_cycle
                                else summary_grace_state.get(
                                    "observed_post_close_summary_complete"
                                )
                            )
                            if (
                                post_close_summary_grace_armed
                                or summary_grace_state.get("observed_post_close_eval")
                            ):
                                if not post_close_summary_grace_armed:
                                    post_close_summary_grace_armed = True
                                    post_close_summary_grace_armed_at = time.time()
                                    post_close_summary_grace_deadline = (
                                        post_close_summary_grace_armed_at
                                        + post_close_summary_grace_timeout_sec
                                    )
                                    _runner_diag(
                                        "post_close_summary_grace_armed",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        post_close_summary_grace_ticks=post_close_summary_grace_ticks,  # noqa: E501
                                        post_close_summary_grace_timeout_sec=post_close_summary_grace_timeout_sec,  # noqa: E501
                                        post_close_summary_grace_armed_at=post_close_summary_grace_armed_at,  # noqa: E501
                                        post_close_summary_grace_deadline=post_close_summary_grace_deadline,  # noqa: E501
                                        post_close_eval_count=int(
                                            summary_grace_state.get("entry_edge_over_fee_eval_count") or 0),  # noqa: E501
                                        summary_emit_done_count=summary_emit_done_count,
                                        entry_gate_decision_summary_count=summary_entry_count,  # noqa: E501
                                        risk_decision_count=summary_risk_decision_count,
                                        require_fresh_tail_cycle=require_fresh_tail_cycle,  # noqa: E501
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                                    print(
                                        f"[{variant}] post_close_summary_grace_armed"
                                    )
                                if not summary_complete_for_release:
                                    now = time.time()
                                    if (
                                        post_close_summary_grace_tick_count
                                        < post_close_summary_grace_ticks
                                        and now
                                        < (post_close_summary_grace_deadline or now)
                                    ):
                                        post_close_summary_grace_tick_count += 1
                                        summary_grace_defer_shutdown = True
                                        _runner_diag(
                                            "post_close_summary_grace_tick_consumed",
                                            close_requested=close_requested,
                                            close_wait_deadline=close_wait_deadline,
                                            post_close_deadline=post_close_deadline,
                                            post_close_summary_grace_tick_count=post_close_summary_grace_tick_count,  # noqa: E501
                                            post_close_summary_grace_ticks=post_close_summary_grace_ticks,  # noqa: E501
                                            post_close_summary_grace_timeout_sec=post_close_summary_grace_timeout_sec,  # noqa: E501
                                            post_close_summary_grace_deadline=post_close_summary_grace_deadline,  # noqa: E501
                                            post_close_eval_count=int(
                                                summary_grace_state.get("entry_edge_over_fee_eval_count") or 0),  # noqa: E501
                                            summary_emit_done_count=summary_emit_done_count,  # noqa: E501
                                            entry_gate_decision_summary_count=summary_entry_count,  # noqa: E501
                                            risk_decision_count=summary_risk_decision_count,  # noqa: E501
                                            require_fresh_tail_cycle=require_fresh_tail_cycle,  # noqa: E501
                                            pending_positions=pending_positions,
                                            close_request_backlog=close_request_backlog,
                                            close_count=close_count,
                                            open_count=open_count,
                                            drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                            termination_reason=termination_reason,
                                        )
                                        _runner_diag(
                                            "runner_shutdown_deferred",
                                            close_requested=close_requested,
                                            close_wait_deadline=close_wait_deadline,
                                            post_close_deadline=post_close_deadline,
                                            post_close_summary_grace_tick_count=post_close_summary_grace_tick_count,  # noqa: E501
                                            post_close_summary_grace_ticks=post_close_summary_grace_ticks,  # noqa: E501
                                            post_close_summary_grace_timeout_sec=post_close_summary_grace_timeout_sec,  # noqa: E501
                                            post_close_summary_grace_deadline=post_close_summary_grace_deadline,  # noqa: E501
                                            deferred_reason="post_close_summary_pending",  # noqa: E501
                                            pending_positions=pending_positions,
                                            close_request_backlog=close_request_backlog,
                                            close_count=close_count,
                                            open_count=open_count,
                                            drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                            termination_reason=termination_reason,
                                        )
                                        print(
                                            f"[{variant}] post_close_summary_grace_deferred "  # noqa: E501
                                            f"ticks={post_close_summary_grace_tick_count}"  # noqa: E501
                                        )
                                    elif post_close_summary_grace_release_reason is None:  # noqa: E501
                                        post_close_summary_grace_release_reason = (
                                            "bounded_timeout"
                                            if post_close_summary_grace_deadline is not None  # noqa: E501
                                            and now >= post_close_summary_grace_deadline
                                            else "bounded_tick_limit"
                                        )
                                        _runner_diag(
                                            "post_close_summary_grace_released",
                                            close_requested=close_requested,
                                            close_wait_deadline=close_wait_deadline,
                                            post_close_deadline=post_close_deadline,
                                            post_close_summary_grace_release_reason=post_close_summary_grace_release_reason,  # noqa: E501
                                            post_close_summary_grace_tick_count=post_close_summary_grace_tick_count,  # noqa: E501
                                            post_close_summary_grace_ticks=post_close_summary_grace_ticks,  # noqa: E501
                                            post_close_summary_grace_timeout_sec=post_close_summary_grace_timeout_sec,  # noqa: E501
                                            post_close_summary_grace_deadline=post_close_summary_grace_deadline,  # noqa: E501
                                            post_close_eval_count=int(
                                                summary_grace_state.get("entry_edge_over_fee_eval_count") or 0),  # noqa: E501
                                            summary_emit_done_count=summary_emit_done_count,  # noqa: E501
                                            entry_gate_decision_summary_count=summary_entry_count,  # noqa: E501
                                            risk_decision_count=summary_risk_decision_count,  # noqa: E501
                                            require_fresh_tail_cycle=require_fresh_tail_cycle,  # noqa: E501
                                            pending_positions=pending_positions,
                                            close_request_backlog=close_request_backlog,
                                            close_count=close_count,
                                            open_count=open_count,
                                            drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                            termination_reason=termination_reason,
                                        )
                                        print(
                                            f"[{variant}] post_close_summary_grace_released "  # noqa: E501
                                            f"reason={post_close_summary_grace_release_reason}"  # noqa: E501
                                        )
                                else:
                                    if post_close_summary_grace_release_reason is None:
                                        post_close_summary_grace_release_reason = (
                                            "summary_emit_done"
                                        )
                                        _runner_diag(
                                            "post_close_summary_grace_released",
                                            close_requested=close_requested,
                                            close_wait_deadline=close_wait_deadline,
                                            post_close_deadline=post_close_deadline,
                                            post_close_summary_grace_release_reason=post_close_summary_grace_release_reason,  # noqa: E501
                                            post_close_summary_grace_tick_count=post_close_summary_grace_tick_count,  # noqa: E501
                                            post_close_summary_grace_ticks=post_close_summary_grace_ticks,  # noqa: E501
                                            post_close_summary_grace_timeout_sec=post_close_summary_grace_timeout_sec,  # noqa: E501
                                            post_close_summary_grace_deadline=post_close_summary_grace_deadline,  # noqa: E501
                                            post_close_eval_count=int(
                                                summary_grace_state.get("entry_edge_over_fee_eval_count") or 0),  # noqa: E501
                                            summary_emit_done_count=summary_emit_done_count,  # noqa: E501
                                            entry_gate_decision_summary_count=summary_entry_count,  # noqa: E501
                                            risk_decision_count=summary_risk_decision_count,  # noqa: E501
                                            require_fresh_tail_cycle=require_fresh_tail_cycle,  # noqa: E501
                                            pending_positions=pending_positions,
                                            close_request_backlog=close_request_backlog,
                                            close_count=close_count,
                                            open_count=open_count,
                                            drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                            termination_reason=termination_reason,
                                        )
                                        print(
                                            f"[{variant}] post_close_summary_grace_released "  # noqa: E501
                                            f"reason={post_close_summary_grace_release_reason}"  # noqa: E501
                                        )
                        if (
                            single_post_close_eval_tick_enabled
                            and not single_post_close_eval_tick_consumed
                            and pending_positions == 0
                            and close_count is not None
                            and close_count > 0
                        ):
                            if not single_post_close_eval_tick_armed:
                                single_post_close_eval_tick_armed = True
                                post_close_extra_tick_triggered = True
                                post_close_extra_tick_count = 1
                                evaluation_phase = "post_close_extra_tick"
                                _runner_diag(
                                    "post_close_extra_tick_triggered",
                                    close_requested=close_requested,
                                    close_wait_deadline=close_wait_deadline,
                                    post_close_deadline=post_close_deadline,
                                    pending_positions=pending_positions,
                                    close_request_backlog=close_request_backlog,
                                    close_count=close_count,
                                    open_count=open_count,
                                    drain_tick_after_enqueue=drain_tick_after_enqueue,
                                    termination_reason=termination_reason,
                                )
                            print(f"[{variant}] post_close_extra_tick_triggered")
                            if post_close_summary_grace_enabled:
                                summary_grace_state = _probe_post_close_summary_grace(
                                    db_path
                                )
                                post_close_summary_grace_armed = True
                                post_close_summary_grace_armed_at = time.time()
                                post_close_summary_grace_deadline = (
                                    post_close_summary_grace_armed_at
                                    + post_close_summary_grace_timeout_sec
                                )
                                post_close_summary_grace_tick_count = 0
                                post_close_summary_grace_release_reason = None
                                post_close_summary_tail_entry_gate_baseline = int(
                                    summary_grace_state.get(
                                        "entry_gate_decision_summary_count"
                                    )
                                    or 0
                                )
                                post_close_summary_tail_emit_done_baseline = int(
                                    summary_grace_state.get(
                                        "post_close_summary_emit_done_count"
                                    )
                                    or 0
                                )
                                post_close_summary_tail_risk_decision_baseline = int(
                                    summary_grace_state.get("risk_decision_count") or 0
                                )
                            single_post_close_eval_tick_consumed = True
                            _runner_diag(
                                "post_close_extra_tick_consumed",
                                close_requested=close_requested,
                                close_wait_deadline=close_wait_deadline,
                                post_close_deadline=post_close_deadline,
                                pending_positions=pending_positions,
                                close_request_backlog=close_request_backlog,
                                close_count=close_count,
                                open_count=open_count,
                                drain_tick_after_enqueue=drain_tick_after_enqueue,
                                termination_reason=termination_reason,
                            )
                            print(f"[{variant}] post_close_extra_tick_consumed")
                        else:
                            skip_reason = (
                                "post_close_extra_tick_disabled"
                                if not single_post_close_eval_tick_enabled
                                else (
                                    "post_close_extra_tick_already_consumed"
                                    if single_post_close_eval_tick_consumed
                                    else "post_close_extra_tick_not_applicable"
                                )
                            )
                            _runner_diag(
                                "post_close_extra_tick_skipped_reason",
                                close_requested=close_requested,
                                close_wait_deadline=close_wait_deadline,
                                post_close_deadline=post_close_deadline,
                                pending_positions=pending_positions,
                                close_request_backlog=close_request_backlog,
                                close_count=close_count,
                                open_count=open_count,
                                drain_tick_after_enqueue=drain_tick_after_enqueue,
                                termination_reason=termination_reason,
                                skip_reason=skip_reason,
                            )
                            if pending_positions == 0:
                                if summary_grace_defer_shutdown:
                                    pass
                                elif post_promotion_window_defer_shutdown:
                                    pass
                                elif (
                                    post_promotion_window_exit_reason
                                    == "first_post_promotion_gate_read_observed"
                                    or reeval_probe.get(
                                        "observed_real_post_promotion_read"
                                    )
                                ):
                                    termination_reason = (
                                        "real_post_promotion_read_observed"
                                    )
                                    shutdown_classification = termination_reason
                                    _runner_diag(
                                        "runner_pre_shutdown_marker",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                                    _runner_diag(
                                        "runner_termination",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                                    print(
                                        f"[{variant}] reevaluation_observed "
                                        f"buckets={','.join(reeval_probe.get('real_post_promotion_read_buckets') or [])}"  # noqa: E501
                                    )
                                    break
                                elif reeval_grace_sec <= 0:
                                    termination_reason = (
                                        "close_flush_done_pending_positions_zero"
                                    )
                                    shutdown_classification = termination_reason
                                    _runner_diag(
                                        "runner_pre_shutdown_marker",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                                    _runner_diag(
                                        "runner_termination",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                                    print(
                                        f"[{variant}] close_flush_done pending_positions=0"  # noqa: E501
                                    )
                                    break
                        if (
                            not summary_grace_defer_shutdown
                            and post_close_deadline is not None
                            and now_ts >= post_close_deadline
                        ):
                            if final_drain_deadline is None:
                                final_drain_deadline = now_ts + max(
                                    60.0,
                                    float(paper_auto_close_sec) * 3.0,
                                )
                                shutdown_classification = (
                                    "post_close_deadline_soft_warning"
                                )
                                _runner_diag(
                                    "runner_close_drain_soft_warning",
                                    close_requested=close_requested,
                                    close_wait_deadline=close_wait_deadline,
                                    post_close_deadline=post_close_deadline,
                                    final_drain_deadline=final_drain_deadline,
                                    pending_positions=pending_positions,
                                    close_request_backlog=close_request_backlog,
                                    close_request_backlog_raw=close_request_backlog_raw,
                                    duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                    close_count=close_count,
                                    open_count=open_count,
                                    drain_tick_after_enqueue=drain_tick_after_enqueue,
                                    termination_reason=termination_reason,
                                )
                                print(
                                    f"[{variant}] post_close_deadline_soft_warning "
                                    f"pending_positions={pending_positions} "
                                    f"backlog={close_request_backlog}"
                                )
                            elif now_ts >= final_drain_deadline:
                                drain_progress_grace_sec = max(
                                    10.0, min(45.0, float(paper_auto_close_sec))
                                )
                                progress_age_sec = (
                                    None if last_drain_progress_ts is None else max(
                                        0.0, now_ts - float(last_drain_progress_ts)))
                                if pending_positions == 0:
                                    termination_reason = (
                                        "close_flush_done_pending_positions_zero"
                                    )
                                elif (
                                    progress_age_sec is not None
                                    and progress_age_sec < drain_progress_grace_sec
                                ):
                                    final_drain_deadline = now_ts + drain_progress_grace_sec  # noqa: E501
                                    _runner_diag(
                                        "runner_shutdown_deferred",
                                        close_requested=close_requested,
                                        close_wait_deadline=close_wait_deadline,
                                        post_close_deadline=post_close_deadline,
                                        final_drain_deadline=final_drain_deadline,
                                        deferred_reason="close_drain_progress_observed",
                                        progress_age_sec=progress_age_sec,
                                        pending_positions=pending_positions,
                                        close_request_backlog=close_request_backlog,
                                        close_request_backlog_raw=close_request_backlog_raw,  # noqa: E501
                                        duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                        close_count=close_count,
                                        open_count=open_count,
                                        drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                        termination_reason=termination_reason,
                                    )
                                    print(
                                        f"[{variant}] close_drain_progress_observed "
                                        f"pending_positions={pending_positions} "
                                        f"backlog={close_request_backlog} "
                                        f"raw_backlog={close_request_backlog_raw}"
                                    )
                                    continue
                                elif (
                                    isinstance(last_drain_snapshot, dict)
                                    and close_count is not None
                                    and close_count
                                    == int(
                                        last_drain_snapshot.get(
                                            "position_close_count"
                                        )
                                        or 0
                                    )
                                    and pending_positions is not None
                                    and pending_positions
                                    == int(
                                        last_drain_snapshot.get("pending_positions")
                                        or 0
                                    )
                                    and close_request_backlog is not None
                                    and close_request_backlog
                                    == int(
                                        last_drain_snapshot.get(
                                            "close_request_backlog"
                                        )
                                        or 0
                                    )
                                ):
                                    if (
                                        not final_close_drain_retry_attempted
                                        and int(pending_positions or 0) > 0
                                        and (
                                            int(close_request_backlog or 0) > 0
                                            or post_promotion_close_requests_pending
                                        )
                                    ):
                                        post_promotion_close_requests_pending = False
                                        retry_symbols = _pending_open_symbols(
                                            db_path) or []
                                        if not retry_symbols:
                                            retry_symbols = list(close_symbols)
                                        retry_count = _enqueue_close_requests(
                                            db_path,
                                            retry_symbols,
                                            reason="controlled_kpi_final_drain_retry",
                                            diag_cb=_runner_diag,
                                        )
                                        final_close_drain_retry_attempted = True
                                        final_drain_deadline = now_ts + max(
                                            20.0,
                                            min(60.0, float(paper_auto_close_sec) * 2.0),  # noqa: E501
                                        )
                                        _runner_diag(
                                            "runner_close_drain_retry_enqueued",
                                            retry_symbols=retry_symbols,
                                            retry_count=retry_count,
                                            close_requested=close_requested,
                                            close_wait_deadline=close_wait_deadline,
                                            post_close_deadline=post_close_deadline,
                                            final_drain_deadline=final_drain_deadline,
                                            pending_positions=pending_positions,
                                            close_request_backlog=close_request_backlog,
                                            close_request_backlog_raw=close_request_backlog_raw,  # noqa: E501
                                            duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                            close_count=close_count,
                                            open_count=open_count,
                                            drain_tick_after_enqueue=drain_tick_after_enqueue,  # noqa: E501
                                            termination_reason=termination_reason,
                                        )
                                        print(
                                            f"[{variant}] close_drain_retry_enqueued "
                                            f"retry_count={retry_count} "
                                            f"pending_positions={pending_positions} "
                                            f"backlog={close_request_backlog}"
                                        )
                                        continue
                                    termination_reason = (
                                        "deterministic_stall_pending_close_drain"
                                    )
                                else:
                                    termination_reason = (
                                        "close_drain_timeout_pending_positions"
                                    )
                                shutdown_classification = termination_reason
                                _runner_diag(
                                    "runner_pre_shutdown_marker",
                                    close_requested=close_requested,
                                    close_wait_deadline=close_wait_deadline,
                                    post_close_deadline=post_close_deadline,
                                    final_drain_deadline=final_drain_deadline,
                                    pending_positions=pending_positions,
                                    close_request_backlog=close_request_backlog,
                                    close_request_backlog_raw=close_request_backlog_raw,
                                    duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                    close_count=close_count,
                                    open_count=open_count,
                                    drain_tick_after_enqueue=drain_tick_after_enqueue,
                                    termination_reason=termination_reason,
                                )
                                _runner_diag(
                                    "runner_termination",
                                    close_requested=close_requested,
                                    close_wait_deadline=close_wait_deadline,
                                    post_close_deadline=post_close_deadline,
                                    final_drain_deadline=final_drain_deadline,
                                    pending_positions=pending_positions,
                                    close_request_backlog=close_request_backlog,
                                    close_request_backlog_raw=close_request_backlog_raw,
                                    duplicate_close_request_count=duplicate_close_request_count,  # noqa: E501
                                    close_count=close_count,
                                    open_count=open_count,
                                    drain_tick_after_enqueue=drain_tick_after_enqueue,
                                    termination_reason=termination_reason,
                                )
                                if reeval_grace_sec > 0:
                                    print(
                                        f"[{variant}] reeval_grace_expired "
                                        f"observed={int(bool(reeval_probe.get('observed_real_post_promotion_read')))} "  # noqa: E501
                                        f"promotions={int(reeval_probe.get('promotion_count') or 0)} "  # noqa: E501
                                        f"real_reads={int(reeval_probe.get('real_post_promotion_read_count') or 0)}"  # noqa: E501
                                    )
                                print(
                                    f"[{variant}] close_drain_stall_classified "
                                    f"classification={termination_reason} "
                                    f"pending_positions={pending_positions} "
                                    f"backlog={close_request_backlog}"
                                )
                                break
                time.sleep(2)
        finally:
            if proc.poll() is None:
                final_close_drain_snapshot = _close_drain_snapshot(db_path)
                final_shutdown_recheck = _resolve_final_shutdown_state(
                    shutdown_classification=shutdown_classification,
                    termination_reason=termination_reason,
                    final_close_drain_snapshot=final_close_drain_snapshot,
                )
                shutdown_classification = (
                    final_shutdown_recheck.get("final_shutdown_classification")
                    or shutdown_classification
                    or termination_reason
                )
                termination_reason = (
                    final_shutdown_recheck.get("final_termination_reason")
                    or termination_reason
                )
                if (
                    final_shutdown_recheck.get("final_drain_recheck_result")
                    != "not_applicable"
                ):
                    _runner_diag(
                        "runner_shutdown_final_drain_recheck",
                        candidate_shutdown_classification=final_shutdown_recheck.get(
                            "candidate_shutdown_classification"
                        ),
                        candidate_termination_reason=final_shutdown_recheck.get(
                            "candidate_termination_reason"
                        ),
                        final_drain_recheck_result=final_shutdown_recheck.get(
                            "final_drain_recheck_result"
                        ),
                        final_progress_complete=final_shutdown_recheck.get(
                            "final_progress_complete"
                        ),
                        final_emitted_termination_reason=termination_reason,
                        close_drain_snapshot=final_close_drain_snapshot,
                    )
                if _is_successful_shutdown_classification(
                    shutdown_classification or termination_reason
                ):
                    process_stop_mode = "await_clean_exit_after_success"
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process_stop_mode = "wrapper_terminate_after_success"
                        proc.terminate()
                        try:
                            proc.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            process_stop_mode = "wrapper_kill_after_success"
                            proc.kill()
                            proc.wait(timeout=20)
                else:
                    termination_reason = termination_reason or "runner_finally_terminate"  # noqa: E501
                    shutdown_classification = shutdown_classification or termination_reason  # noqa: E501
                    process_stop_mode = "wrapper_terminate_after_failure"
                    _runner_diag(
                        "runner_pre_shutdown_marker",
                        close_requested=close_requested,
                        close_wait_deadline=close_wait_deadline,
                        post_close_deadline=post_close_deadline,
                        final_drain_deadline=final_drain_deadline,
                        pending_positions=_pending_open_positions(db_path),
                        close_drain_snapshot=final_close_drain_snapshot,
                        drain_tick_after_enqueue=drain_tick_after_enqueue,
                        termination_reason=termination_reason,
                    )
                    _runner_diag(
                        "runner_termination",
                        close_requested=close_requested,
                        close_wait_deadline=close_wait_deadline,
                        post_close_deadline=post_close_deadline,
                        final_drain_deadline=final_drain_deadline,
                        pending_positions=_pending_open_positions(db_path),
                        close_drain_snapshot=final_close_drain_snapshot,
                        drain_tick_after_enqueue=drain_tick_after_enqueue,
                        termination_reason=termination_reason,
                    )
                    proc.terminate()
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process_stop_mode = "wrapper_kill_after_failure"
                        proc.kill()
                        proc.wait(timeout=20)
            if final_close_drain_snapshot is None:
                final_close_drain_snapshot = _close_drain_snapshot(db_path)
            if final_shutdown_recheck is None:
                final_shutdown_recheck = _resolve_final_shutdown_state(
                    shutdown_classification=shutdown_classification,
                    termination_reason=termination_reason,
                    final_close_drain_snapshot=final_close_drain_snapshot,
                )
            shutdown_classification = (
                final_shutdown_recheck.get("final_shutdown_classification")
                or shutdown_classification
                or termination_reason
            )
            termination_reason = (
                final_shutdown_recheck.get("final_termination_reason")
                or termination_reason
            )
            if (
                shutdown_classification == "close_flush_done_pending_positions_zero"
                and bool(reeval_probe.get("observed_real_post_promotion_read"))
            ):
                shutdown_classification = "real_post_promotion_read_observed"
                termination_reason = shutdown_classification
            process_returncode_raw = _canonicalize_process_returncode_raw(
                shutdown_classification=shutdown_classification or termination_reason,
                raw_returncode=(
                    int(proc.returncode) if proc.returncode is not None else -1
                ),
                final_close_drain_snapshot=final_close_drain_snapshot,
                process_stop_mode=process_stop_mode,
            )

    end_dt = datetime.now(timezone.utc)
    metrics = _collect_metrics(db_path)
    log_health = _analyze_process_logs(out_log, err_log)
    env_diagnostic_flags = {
        key: env.get(key)
        for key in (
            "DIAGNOSTIC_MODE",
            "DIAG_DISABLE_NET_TARGET_GUARD",
            "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION",
            "DIAG_DISABLE_SIDE_GUARD",
            "DIAG_DISABLE_SIDE_EXPECTANCY",
            "LIVE",
        )
    }
    env_effective_flags = {
        key: env.get(key)
        for key in (
            "ALPHA_WHITELIST_ENABLE",
            "ALPHA_WHITELIST_COLDSTART_ALLOW",
            "ALPHA_WHITELIST_FALLBACK_ENABLE",
            "SEED_TRADES_ENABLE",
            "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST",
            "ALPHA_BOOTSTRAP_REQUIRE_EXTERNAL_SOURCE",
            "LOSS_COOLDOWN_SEC",
            "ENTRY_SYMBOL_STRATEGY_BLOCKLIST",
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST",
            "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST",
            "DIAG_DISABLE_SIDE_EXPECTANCY",
            "DIAG_DISABLE_NET_TARGET_GUARD",
            "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC",
            "POST_PROMOTION_OBSERVATION_ENABLED",
            "POST_PROMOTION_OBSERVATION_MAX_SEC",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES",
        )
    }
    print(
        f"[{variant}] end={end_dt.isoformat()} actual_sec={int((end_dt - start_dt).total_seconds())} "  # noqa: E501
        f"trades={metrics.get('trade_count')} net_pnl={metrics.get('net_pnl')}"
    )
    forced_cycle_trigger_contract = (
        _finalize_post_promotion_forced_cycle_trigger_contract(
            post_promotion_forced_cycle_requested=bool(
                post_promotion_forced_cycle_requested
            ),
            post_promotion_forced_cycle_trigger_mode=(
                post_promotion_forced_cycle_trigger_mode
            ),
            post_promotion_forced_cycle_request_reason=(
                post_promotion_forced_cycle_request_reason
            ),
            post_promotion_reeval_completed=bool(post_promotion_reeval_completed),
            post_promotion_reeval_result=post_promotion_reeval_result,
        )
    )
    metrics.update(
        {
            "variant": variant,
            "db_path": str(db_path),
            "out_log": str(out_log),
            "err_log": str(err_log),
            "started_at_utc": start_dt.isoformat(),
            "ended_at_utc": end_dt.isoformat(),
            "duration_sec_target": duration_sec,
            "duration_sec_actual": int((end_dt - start_dt).total_seconds()),
            "log_health": log_health,
            "diagnostic_env_flags": env_diagnostic_flags,
            "effective_env_values": env_effective_flags,
            "reevaluation_probe": reeval_probe,
            "research_post_promotion_reeval_grace_sec": reeval_grace_sec,
            "research_post_close_summary_grace_ticks": post_close_summary_grace_ticks,
            "research_post_close_summary_grace_timeout_sec": post_close_summary_grace_timeout_sec,  # noqa: E501
            "post_close_summary_grace_release_reason": post_close_summary_grace_release_reason,  # noqa: E501
            "post_promotion_observation_enabled": bool(post_promotion_observation_enabled),  # noqa: E501
            "post_promotion_observation_max_sec": float(post_promotion_observation_max_sec),  # noqa: E501
            "post_promotion_observation_max_cycles": int(post_promotion_observation_max_cycles),  # noqa: E501
            "post_promotion_window_armed": bool(post_promotion_window_armed),
            "post_promotion_window_cycle_count": int(post_promotion_window_cycle_count),
            "post_promotion_window_exit_reason": post_promotion_window_exit_reason,
            "post_promotion_reeval_requested": bool(post_promotion_reeval_requested),
            "post_promotion_reeval_dispatch_entered": bool(post_promotion_reeval_dispatch_entered),  # noqa: E501
            "post_promotion_reeval_completed": bool(post_promotion_reeval_completed),
            "post_promotion_reeval_result": post_promotion_reeval_result,
            "post_promotion_reeval_exit_reason": post_promotion_reeval_exit_reason
            or post_promotion_window_exit_reason,
            "post_promotion_reeval_runtime_seq": (
                reeval_probe.get("reeval_runtime_seq")
                or post_promotion_reeval_request_runtime_seq
            ),
            "post_promotion_forced_cycle_trigger_mode": post_promotion_forced_cycle_trigger_mode,  # noqa: E501
            "post_promotion_forced_cycle_request_reason": post_promotion_forced_cycle_request_reason,  # noqa: E501
            "post_promotion_forced_cycle_trigger_contract": forced_cycle_trigger_contract,  # noqa: E501
            "shutdown_classification": shutdown_classification
            or termination_reason
            or "unknown",
            "post_close_extra_tick_triggered": bool(post_close_extra_tick_triggered),
            "post_close_extra_tick_count": int(post_close_extra_tick_count),
            "evaluation_phase": evaluation_phase,
            "runner_shutdown_reason": shutdown_classification
            or termination_reason
            or "unknown",
            "runner_shutdown_ts": end_dt.isoformat(),
            "runner_termination_trace": runner_diagnostics,
            "runner_diagnostics": runner_diagnostics,
            "process_stop_mode": process_stop_mode,
            "final_close_drain_snapshot": final_close_drain_snapshot,
            "process_returncode_raw": process_returncode_raw,
            "process_returncode": _normalize_process_returncode(
                shutdown_classification=shutdown_classification or termination_reason,
                raw_returncode=process_returncode_raw,
                final_close_drain_snapshot=final_close_drain_snapshot,
            ),
        }
    )
    return metrics


def _format_metrics_line(tag: str, m: dict) -> str:
    pf = m["profit_factor"]
    pf_str = "inf" if pf == float("inf") else f"{pf:.4f}"
    log_health = m.get("log_health") or {}
    return (
        f"{tag}: trades={
            m['trade_count']}, net_pnl={
            m['net_pnl']:.6f}, " f"winrate={
                m['winrate'] *
                100:.2f}%, max_dd={
                    m['max_drawdown'] *
                    100:.2f}%, " f"profit_factor={pf_str}, decisions={
                        m['decisions_count']}, equity_points={
                            m['equity_points']}, " f"log_errors={
                                log_health.get(
                                    'error_count',
                                    0)}")


def _block_mock_ohlcv_kucoin_paper_startup(
    *,
    use_mock: bool,
    market_type: str,
    symbols: list[str],
        timeframe: str | int) -> None:
    if not use_mock:
        return
    symbol_txt = str(symbols[0] if symbols else "<unknown>").strip() or "<unknown>"
    market_type_txt = str(market_type or "").strip() or "<unset>"
    timeframe_txt = str(timeframe or "").strip() or "<unknown>"
    raise SystemExit(
        "MOCK_OHLCV_BLOCKED_KUCOIN_PAPER: controlled_kpi_run aborted before launch "
        "because --use-mock would activate MarketDataFetcher.get_ohlcv() deterministic "
        "mock candles (close=100+i+0.1, volume=1000), which feed _quote_snapshot(...) "
        "as tick_stream_synth/static synthetic pricing. "
        f"market_type={market_type_txt} symbol={symbol_txt} interval={timeframe_txt} "
        "blocked_source=MarketDataFetcher.get_ohlcv.mock_branch"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant-only",
        type=str,
        default="both",
        choices=["both", "before", "after"],
        help="Run both variants or just one variant",
    )
    parser.add_argument("--before-min", type=int, default=30)
    parser.add_argument("--after-min", type=int, default=30)
    parser.add_argument(
        "--symbols",
        type=str,
        default="ETHUSDTM,BTCUSDTM,SOLUSDTM,XRPUSDTM,ADAUSDTM,BNBUSDTM",
        help="Comma-separated symbol list",
    )
    parser.add_argument(
        "--market-type",
        type=str,
        default="futures",
        help="spot|futures",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1",
        help="KuCoin timeframe (e.g. 1, 5, 15)",
    )
    parser.add_argument(
        "--use-mock",
        action="store_true",
        help="Use deterministic mock data instead of exchange feed",
    )
    parser.add_argument(
        "--paper-auto-open",
        action="store_true",
        help="Enable simulation auto-open helper",
    )
    parser.add_argument("--paper-auto-close-sec", type=int, default=60)
    parser.add_argument("--equity-snapshot-sec", type=int, default=10)
    parser.add_argument(
        "--quality-profile",
        action="store_true",
        help="Enable conservative quality-first entry/risk profile",
    )
    parser.add_argument(
        "--alpha-bootstrap-source-db-url",
        type=str,
        default="sqlite:///tmp/alpha_history_auto_recent.db",
        help="External sqlite DB URL/path for alpha bootstrap (e.g. sqlite:///tmp/history.db)",  # noqa: E501
    )
    parser.add_argument(
        "--alpha-bootstrap-source-db-glob",
        type=str,
        default="tmp/alpha_history_auto_recent.db",
        help="Glob for external sqlite DB files used for alpha bootstrap",
    )
    parser.add_argument(
        "--alpha-bootstrap-auto-refresh",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rebuild bootstrap alpha DB from recent controlled run DBs before run.",
    )
    parser.add_argument(
        "--alpha-bootstrap-build-output",
        type=str,
        default="tmp/alpha_history_auto_recent.db",
        help="Output DB path for auto-refreshed alpha bootstrap history.",
    )
    parser.add_argument(
        "--alpha-bootstrap-build-glob",
        type=str,
        default="zol0.db,tmp/controlled_kpi_after_*.db,tmp/controlled_kpi_before_*.db",
        help="Source DB glob(s) for alpha bootstrap auto-refresh.",
    )
    parser.add_argument("--alpha-bootstrap-build-max-sources", type=int, default=35)
    parser.add_argument("--alpha-bootstrap-build-max-per-source", type=int, default=320)
    parser.add_argument("--alpha-bootstrap-build-max-total", type=int, default=3000)
    parser.add_argument("--alpha-bootstrap-build-min-abs-pnl", type=float, default=0.0)
    parser.add_argument("--alpha-bootstrap-build-min-pair-trades", type=int, default=10)
    parser.add_argument("--alpha-bootstrap-build-min-pair-winrate",
                        type=float, default=0.40)
    parser.add_argument(
        "--alpha-bootstrap-build-min-pair-expectancy", type=float, default=0.000
    )
    parser.add_argument(
        "--alpha-bootstrap-build-fallback-top-pairs", type=int, default=0
    )
    parser.add_argument(
        "--alpha-bootstrap-build-fallback-positive-side-pairs",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--alpha-bootstrap-build-min-side-trades",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--alpha-bootstrap-build-min-side-winrate",
        type=float,
        default=0.45,
    )
    parser.add_argument(
        "--alpha-bootstrap-build-min-side-expectancy",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--alpha-bootstrap-build-report-json",
        type=str,
        default="tmp/alpha_history_auto_recent_report.json",
        help="Optional JSON report path for alpha bootstrap auto-refresh.",
    )
    parser.add_argument(
        "--alpha-bootstrap-accepted-scorecard",
        type=str,
        default=DEFAULT_ALPHA_BOOTSTRAP_ACCEPTED_SCORECARD,
        help=(
            "Exact accepted scorecard JSON used to restrict alpha bootstrap "
            "sources to accepted after run IDs."
        ),
    )
    parser.add_argument(
        "--before-env",
        action="append",
        default=[],
        help="Override env for BEFORE variant (KEY=VALUE), repeatable",
    )
    parser.add_argument(
        "--after-env",
        action="append",
        default=[],
        help="Override env for AFTER variant (KEY=VALUE), repeatable",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Explicit UTC run id stamp used for output artifact names.",
    )
    args = parser.parse_args()
    before_overrides = _parse_env_overrides(args.before_env)
    after_overrides = _parse_env_overrides(args.after_env)
    before_overrides_cli = dict(before_overrides)
    after_overrides_cli = dict(after_overrides)
    cli_alpha_bootstrap_source_url_override = str(
        after_overrides_cli.get("ALPHA_BOOTSTRAP_SOURCE_DB_URL")
        or before_overrides_cli.get("ALPHA_BOOTSTRAP_SOURCE_DB_URL")
        or ""
    ).strip()
    cli_alpha_bootstrap_source_glob_override = str(
        after_overrides_cli.get("ALPHA_BOOTSTRAP_SOURCE_DB_GLOB")
        or before_overrides_cli.get("ALPHA_BOOTSTRAP_SOURCE_DB_GLOB")
        or ""
    ).strip()
    cli_alpha_bootstrap_source_override_requested = bool(
        cli_alpha_bootstrap_source_url_override
        or cli_alpha_bootstrap_source_glob_override
    )
    if cli_alpha_bootstrap_source_url_override:
        args.alpha_bootstrap_source_db_url = cli_alpha_bootstrap_source_url_override
    if cli_alpha_bootstrap_source_glob_override:
        args.alpha_bootstrap_source_db_glob = cli_alpha_bootstrap_source_glob_override
    if cli_alpha_bootstrap_source_override_requested:
        # An explicit source override is an operator directive and should not be
        # replaced by the exact-scorecard prebuilt contract or the auto-refresh path.
        args.alpha_bootstrap_auto_refresh = False

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        raise SystemExit("No symbols provided")
    run_symbols = ",".join(symbols)
    active_run_symbols = {
        str(symbol or "").strip().upper()
        for symbol in symbols
        if str(symbol or "").strip()
    }
    _block_mock_ohlcv_kucoin_paper_startup(
        use_mock=bool(args.use_mock),
        market_type=str(args.market_type),
        symbols=symbols,
        timeframe=args.timeframe,
    )

    data_check = _run_data_integrity_checks(
        symbols=symbols,
        market_type=args.market_type,
        use_mock=args.use_mock,
        timeframe=args.timeframe,
    )
    if data_check.get("skipped"):
        print("DATA_CHECK: skipped (USE_MOCK=1)")
    else:
        for sym, info in data_check.get("results", {}).items():
            print(
                f"DATA_CHECK {sym}: ok={
                    info.get('ok')} count={
                    info.get('count')} " f"monotonic={
                    info.get('monotonic_ts')} stale_sec={
                    info.get('stale_sec')}")

    alpha_bootstrap_exact_contract = _resolve_alpha_bootstrap_exact_source_contract(
        args.alpha_bootstrap_accepted_scorecard
    )
    alpha_refresh = None
    if (
        alpha_bootstrap_exact_contract.get("active")
        and not cli_alpha_bootstrap_source_override_requested
    ):
        if (
            str(alpha_bootstrap_exact_contract.get("source_mode") or "")
            in ("prebuilt_alpha_history_db", "prebuilt_alpha_history_manifest")
        ):
            prebuilt_db_path = Path(
                str(
                    alpha_bootstrap_exact_contract.get(
                        "prebuilt_alpha_history_db_path"
                    )
                    or ""
                )
            ).resolve()
            prebuilt_report_path_txt = str(
                alpha_bootstrap_exact_contract.get(
                    "prebuilt_alpha_history_report_path"
                )
                or ""
            ).strip()
            prebuilt_report_path = (
                Path(prebuilt_report_path_txt).resolve()
                if prebuilt_report_path_txt
                else None
            )
            prebuilt_report = {}
            prebuilt_report_path_exists = (
                prebuilt_report_path is not None
                and prebuilt_report_path.exists()
            )
            if prebuilt_report_path_exists:
                try:
                    prebuilt_report = json.loads(
                        prebuilt_report_path.read_text(encoding="utf-8")
                    )
                except Exception:
                    prebuilt_report = {}
            prebuilt_source_posix = prebuilt_db_path.as_posix()
            args.alpha_bootstrap_source_db_url = (
                f"sqlite:///{prebuilt_source_posix}"
            )
            args.alpha_bootstrap_source_db_glob = prebuilt_source_posix
            prebuilt_glob_token = prebuilt_source_posix
            try:
                prebuilt_glob_token = prebuilt_db_path.relative_to(WORKDIR).as_posix()
            except Exception:
                pass
            prebuilt_refresh_enabled = bool(
                args.alpha_bootstrap_auto_refresh and args.paper_auto_open
            )
            if prebuilt_refresh_enabled:
                args.alpha_bootstrap_build_glob = _merge_csv_tokens_preserving_order(
                    prebuilt_glob_token,
                    args.alpha_bootstrap_build_glob,
                )
            else:
                args.alpha_bootstrap_auto_refresh = False
                args.alpha_bootstrap_build_glob = prebuilt_source_posix
                alpha_refresh = {
                    "enabled": True,
                    "ran": True,
                    "success": True,
                    "returncode": 0,
                    "output_path": str(prebuilt_db_path),
                    "output_exists": bool(
                        prebuilt_db_path.exists()
                        and prebuilt_db_path.stat().st_size > 0
                    ),
                    "report_path": (
                        str(prebuilt_report_path)
                        if (
                            prebuilt_report_path is not None
                            and prebuilt_report_path.exists()
                        )
                        else None
                    ),
                    "report": prebuilt_report,
                    "stdout_tail": "PREBUILT_ALPHA_HISTORY_DB",
                    "stderr_tail": "",
                }
        else:
            exact_patterns = (
                alpha_bootstrap_exact_contract.get("exact_after_db_patterns") or []
            )
            args.alpha_bootstrap_build_glob = ",".join(
                exact_patterns or [EXACT_ALPHA_BOOTSTRAP_EMPTY_SENTINEL]
            )
            args.alpha_bootstrap_build_max_sources = max(
                1, len(alpha_bootstrap_exact_contract.get("accepted_run_ids") or [])
            )
            planned_alpha_output_path = (
                WORKDIR / str(args.alpha_bootstrap_build_output)
            ).resolve()
            planned_alpha_report_path = (
                WORKDIR / str(args.alpha_bootstrap_build_report_json)
            ).resolve()
            for stale_path in (planned_alpha_output_path, planned_alpha_report_path):
                try:
                    if stale_path.exists():
                        stale_path.unlink()
                except Exception:
                    pass
            planned_alpha_output_posix = planned_alpha_output_path.as_posix()
            args.alpha_bootstrap_source_db_url = (
                f"sqlite:///{planned_alpha_output_posix}"
            )
            args.alpha_bootstrap_source_db_glob = planned_alpha_output_posix
        scorecard_path = alpha_bootstrap_exact_contract.get("scorecard_path")
        resolved_scorecard_path = alpha_bootstrap_exact_contract.get(
            "resolved_scorecard_path"
        )
        manifest_path = alpha_bootstrap_exact_contract.get("prebuilt_manifest_path")
        source_mode = alpha_bootstrap_exact_contract.get("source_mode")
        accepted_count = len(
            alpha_bootstrap_exact_contract.get("accepted_run_ids") or []
        )
        existing_count = len(
            alpha_bootstrap_exact_contract.get("existing_run_ids") or []
        )
        nonzero_count = len(alpha_bootstrap_exact_contract.get("nonzero_run_ids") or [])
        missing_count = len(alpha_bootstrap_exact_contract.get("missing_run_ids") or [])
        reasons_txt = (
            ",".join(alpha_bootstrap_exact_contract.get("reason_codes") or [])
            or "-"
        )
        print(
            "ALPHA_BOOTSTRAP_EXACT_SOURCE_CONTRACT: "
            f"scorecard='{scorecard_path}' "
            f"resolved_scorecard='{resolved_scorecard_path}' "
            f"manifest='{manifest_path}' "
            f"source_mode={source_mode} "
            f"accepted={accepted_count} "
            f"existing={existing_count} "
            f"nonzero={nonzero_count} "
            f"missing={missing_count} "
            f"reasons={reasons_txt}"
        )

    if alpha_refresh is None:
        alpha_refresh = _refresh_alpha_bootstrap_history(
            enabled=bool(args.alpha_bootstrap_auto_refresh),
            output_rel=str(args.alpha_bootstrap_build_output),
            glob_patterns=str(args.alpha_bootstrap_build_glob),
            max_sources=int(args.alpha_bootstrap_build_max_sources),
            max_per_source=int(args.alpha_bootstrap_build_max_per_source),
            max_total=int(args.alpha_bootstrap_build_max_total),
            min_abs_pnl=float(args.alpha_bootstrap_build_min_abs_pnl),
            min_pair_trades=int(args.alpha_bootstrap_build_min_pair_trades),
            min_pair_winrate=float(args.alpha_bootstrap_build_min_pair_winrate),
            min_pair_expectancy=float(args.alpha_bootstrap_build_min_pair_expectancy),
            fallback_top_pairs=int(args.alpha_bootstrap_build_fallback_top_pairs),
            report_json_rel=str(args.alpha_bootstrap_build_report_json),
            fallback_positive_side_pairs=int(
                args.alpha_bootstrap_build_fallback_positive_side_pairs
            ),
            min_side_trades=int(args.alpha_bootstrap_build_min_side_trades),
            min_side_winrate=float(args.alpha_bootstrap_build_min_side_winrate),
            min_side_expectancy=float(
                args.alpha_bootstrap_build_min_side_expectancy
            ),
        )
    if (
        cli_alpha_bootstrap_source_override_requested
        and not _coerce_bool(alpha_refresh.get("ran"))
    ):
        alpha_refresh = _probe_alpha_bootstrap_source_db(
            source_db_url=args.alpha_bootstrap_source_db_url,
            source_db_glob=args.alpha_bootstrap_source_db_glob,
        )
    alpha_refresh["exact_source_contract"] = alpha_bootstrap_exact_contract
    alpha_refresh = _finalize_alpha_bootstrap_refresh_contract(alpha_refresh)
    if alpha_refresh.get("ran"):
        print(
            "ALPHA_BOOTSTRAP_REFRESH: "
            f"success={int(bool(alpha_refresh.get('success')))} "
            f"status={alpha_refresh.get('status')} "
            f"returncode={alpha_refresh.get('returncode')} "
            f"output='{alpha_refresh.get('output_path')}' "
            f"reasons={','.join(alpha_refresh.get('reason_codes') or []) or '-'}"
        )
        if str(alpha_refresh.get("stdout_tail") or "").strip():
            print("ALPHA_BOOTSTRAP_REFRESH_STDOUT:")
            print(alpha_refresh.get("stdout_tail"))
        if str(alpha_refresh.get("stderr_tail") or "").strip():
            print("ALPHA_BOOTSTRAP_REFRESH_STDERR:")
            print(alpha_refresh.get("stderr_tail"))
    if alpha_refresh.get("success"):
        refreshed_path = Path(str(alpha_refresh.get("output_path"))).resolve()
        refreshed_posix = refreshed_path.as_posix()
        args.alpha_bootstrap_source_db_url = f"sqlite:///{refreshed_posix}"
        args.alpha_bootstrap_source_db_glob = refreshed_posix
    elif (
        alpha_bootstrap_exact_contract.get("active")
        and not cli_alpha_bootstrap_source_override_requested
    ):
        missing_source_path = (WORKDIR / EXACT_ALPHA_BOOTSTRAP_EMPTY_SENTINEL).resolve()
        try:
            if missing_source_path.exists() and missing_source_path.is_file():
                missing_source_path.unlink()
        except Exception:
            pass
        missing_source_posix = missing_source_path.as_posix()
        args.alpha_bootstrap_source_db_url = f"sqlite:///{missing_source_posix}"
        args.alpha_bootstrap_source_db_glob = missing_source_posix
        alpha_refresh["source_fail_closed"] = True
        alpha_refresh["source_fail_closed_path"] = str(missing_source_path)
        fail_closed_whitelist_overrides = {
            "ALPHA_WHITELIST_ENABLE": "0",
            "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
            "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
            "ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS": "0",
        }
        applied_fail_closed_overrides = []
        for key, value in fail_closed_whitelist_overrides.items():
            if key in after_overrides_cli:
                continue
            after_overrides[key] = value
            applied_fail_closed_overrides.append(key)
        alpha_refresh["source_fail_closed_env_overrides"] = sorted(
            applied_fail_closed_overrides
        )

    alpha_bootstrap_runtime_contract = _derive_alpha_bootstrap_runtime_contract(
        alpha_refresh
    )
    alpha_refresh["runtime_contract"] = dict(alpha_bootstrap_runtime_contract)
    runtime_contract_status = alpha_bootstrap_runtime_contract.get("status")
    runtime_contract_fail_closed = int(
        bool(alpha_bootstrap_runtime_contract.get("source_fail_closed"))
    )
    runtime_contract_refresh_status = (
        alpha_bootstrap_runtime_contract.get("refresh_status") or "-"
    )
    runtime_contract_reasons = (
        ",".join(alpha_bootstrap_runtime_contract.get("reason_codes") or []) or "-"
    )
    print(
        "ALPHA_BOOTSTRAP_RUNTIME_CONTRACT: "
        f"status={runtime_contract_status} "
        f"source_fail_closed={runtime_contract_fail_closed} "
        f"refresh_status={runtime_contract_refresh_status} "
        f"reasons={runtime_contract_reasons}"
    )

    auto_after_overrides = {}
    strict_bucket_gate = {
        "overrides": {},
        "positive_side_allowlist": [],
        "toxic_pair_blocklist": [],
        "toxic_side_blocklist": [],
        "cost_burden_side_blocklist": [],
    }
    alpha_refresh_report = (
        alpha_refresh.get("report")
        if isinstance(alpha_refresh, dict)
        else {}
    )
    if isinstance(alpha_refresh_report, dict):
        scoped_alpha_refresh_report = dict(alpha_refresh_report)
        positive_side_fallback_used = _coerce_bool(
            alpha_refresh_report.get("positive_side_fallback_used")
        )
        # ---- Faza 4C: BOOTSTRAP STALENESS WARNING ----
        if positive_side_fallback_used:
            try:
                import re as _re_stale
                import datetime as _dt_stale
                _stale_dates = []
                for _ss in (alpha_refresh_report.get("source_stats_top") or []):
                    if isinstance(_ss, (list, tuple)) and _ss:
                        _sm = _re_stale.search(r"(\d{8})", str(_ss[0]))
                        if _sm:
                            _stale_dates.append(
                                _dt_stale.datetime.strptime(
                                    _sm.group(1), "%Y%m%d"
                                ).date()
                            )
                if _stale_dates:
                    _corpus_age_days = (
                        _dt_stale.date.today() - max(_stale_dates)
                    ).days
                    if _corpus_age_days > 7:
                        print(
                            "BOOTSTRAP_STALENESS_CRITICAL: "
                            f"positive_side_fallback_used=True AND "
                            f"corpus_age_days={_corpus_age_days} (>7). "
                            "Bootstrap is operating on stale data. "
                            "Run scripts/refresh_bootstrap_corpus_from_recent_paper.py"
                            " to refresh. bootstrap_staleness_critical=True"
                        )
            except Exception:
                pass
        if active_run_symbols:
            scoped_alpha_refresh_report["pair_stats_top"] = [
                row
                for row in (alpha_refresh_report.get("pair_stats_top") or [])
                if isinstance(row, dict)
                and str(row.get("symbol") or "").strip().upper() in active_run_symbols
            ]
            scoped_alpha_refresh_report["pair_side_stats_top"] = [
                row
                for row in (alpha_refresh_report.get("pair_side_stats_top") or [])
                if isinstance(row, dict)
                and str(row.get("symbol") or "").strip().upper() in active_run_symbols
            ]
        merge_csv_keys = {
            "ENTRY_SYMBOL_BLOCKLIST",
            "ENTRY_SYMBOL_ALLOWLIST",
            "ENTRY_SYMBOL_STRATEGY_BLOCKLIST",
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST",
            "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST",
            "ENTRY_STRATEGY_SIDE_ALLOWLIST",
            "ENTRY_STRATEGY_SIDE_BLOCKLIST",
            "ENTRY_STRATEGY_ALLOWLIST",
            "DISABLE_STRATEGIES",
        }
        strict_bucket_gate = _derive_profitability_bucket_gate(
            scoped_alpha_refresh_report,
            active_run_symbols=active_run_symbols,
        )
        strict_bucket_overrides = dict(strict_bucket_gate.get("overrides") or {})
        for key, value in strict_bucket_overrides.items():
            if key in after_overrides_cli:
                continue
            if key in merge_csv_keys and key in after_overrides:
                merged = _merge_csv_values(after_overrides.get(key), value)
                if merged:
                    after_overrides[key] = merged
                else:
                    after_overrides.pop(key, None)
            else:
                after_overrides.setdefault(key, str(value))
        positive_side_allowlist_txt = (
            ",".join(strict_bucket_gate.get("positive_side_allowlist") or [])
            or "-"
        )
        toxic_pair_blocklist_txt = (
            ",".join(strict_bucket_gate.get("toxic_pair_blocklist") or []) or "-"
        )
        toxic_side_blocklist_txt = (
            ",".join(strict_bucket_gate.get("toxic_side_blocklist") or []) or "-"
        )
        thresholds_txt = (
            f"side_trades>={STRICT_ALPHA_SIDE_MIN_TRADES},"
            f"side_wr>={STRICT_ALPHA_SIDE_MIN_WINRATE:.2f},"
            f"side_exp>{STRICT_ALPHA_SIDE_MIN_EXPECTANCY:.4f}"
        )
        print(
            "ALPHA_BOOTSTRAP_STRICT_BUCKET_GATING: "
            f"positive_side_allowlist={positive_side_allowlist_txt} "
            f"toxic_pair_blocklist={toxic_pair_blocklist_txt} "
            f"toxic_side_blocklist={toxic_side_blocklist_txt} "
            f"overrides={len(strict_bucket_overrides)} "
            f"thresholds={thresholds_txt}"
        )
        if (
            positive_side_fallback_used
            and not runtime_contract_fail_closed
            and not strict_bucket_gate.get("positive_side_allowlist")
            and "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST"
            not in after_overrides_cli
            and not _split_csv_tokens(
                after_overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST")
            )
        ):
            after_overrides["PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST"] = "0"
            if "ENTRY_EDGE_COLDSTART_MODE" not in after_overrides_cli:
                after_overrides["ENTRY_EDGE_COLDSTART_MODE"] = "fail_open"
        robust_side_blocks = set()
        robust_negative_strategies = set()
        strategy_rollup = {}
        for row in scoped_alpha_refresh_report.get("pair_side_stats_top") or []:
            if not isinstance(row, dict):
                continue
            try:
                symbol_name = str(row.get("symbol") or "").strip().upper()
                strategy_name = str(row.get("strategy") or "").strip()
                side_name = str(row.get("side") or "").strip().lower()
            except Exception:
                continue
            if side_name in ("long",):
                side_name = "buy"
            elif side_name in ("short",):
                side_name = "sell"
            if (
                not symbol_name
                or not strategy_name
                or side_name not in ("buy", "sell")
            ):
                continue
            try:
                trade_count = int(row.get("trade_count") or 0)
            except Exception:
                trade_count = 0
            try:
                expectancy = float(row.get("expectancy") or 0.0)
            except Exception:
                expectancy = 0.0
            try:
                winrate = float(row.get("winrate") or 0.0)
            except Exception:
                winrate = 0.0
            st_bucket = strategy_rollup.setdefault(
                strategy_name,
                {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
            )
            st_bucket["trade_count"] += max(0, int(trade_count))
            st_bucket["wins_weighted"] += min(1.0, max(0.0, float(winrate))) * max(
                0, int(trade_count)
            )
            st_bucket["net_pnl"] += float(expectancy) * max(0, int(trade_count))
            robust_bad_side = (
                trade_count >= 7 and expectancy <= -0.06 and winrate <= 0.35
            ) or (
                trade_count >= 4 and expectancy <= -0.08 and winrate <= 0.30
            )
            if robust_bad_side:
                robust_side_blocks.add(f"{symbol_name}:{strategy_name}:{side_name}")
        for strategy_name, st_bucket in strategy_rollup.items():
            trades_s = int(st_bucket.get("trade_count") or 0)
            if trades_s < 16:
                continue
            net_s = float(st_bucket.get("net_pnl") or 0.0)
            wins_s = float(st_bucket.get("wins_weighted") or 0.0)
            exp_s = net_s / trades_s if trades_s > 0 else 0.0
            wr_s = wins_s / trades_s if trades_s > 0 else 0.0
            if (exp_s <= -0.12 and wr_s <= 0.20) or (
                exp_s <= -0.09 and wr_s <= 0.12
            ):
                robust_negative_strategies.add(str(strategy_name))
        if robust_side_blocks:
            after_overrides.setdefault(
                "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST",
                ",".join(sorted(robust_side_blocks)),
            )
        if robust_negative_strategies:
            try:
                existing_disabled = {
                    x.strip()
                    for x in str(
                        after_overrides.get("DISABLE_STRATEGIES", "")
                    ).split(",")
                    if x.strip()
                }
            except Exception:
                existing_disabled = set()
            merged_disabled = sorted(existing_disabled | robust_negative_strategies)
            if merged_disabled:
                after_overrides.setdefault(
                    "DISABLE_STRATEGIES",
                    ",".join(merged_disabled),
                )
        side_blocks_txt = ",".join(sorted(robust_side_blocks)) or "-"
        strategy_disables_txt = ",".join(sorted(robust_negative_strategies)) or "-"
        print(
            "ALPHA_BOOTSTRAP_SIDE_GUARD: "
            f"side_blocks={side_blocks_txt} "
            f"strategy_disables={strategy_disables_txt}"
        )
        try:
            pairs_selected = int(alpha_refresh_report.get("pairs_selected") or 0)
        except Exception:
            pairs_selected = 0
        try:
            rows_inserted = int(alpha_refresh_report.get("rows_inserted") or 0)
        except Exception:
            rows_inserted = 0
        selected_pair_count = 0
        selected_pair_trades = 0
        selected_pair_weighted_expectancy = 0.0
        selected_pair_weighted_winrate = 0.0
        selected_positive_pair_count = 0
        for row in alpha_refresh_report.get("pair_stats_top") or []:
            if not isinstance(row, dict) or not bool(row.get("selected")):
                continue
            symbol_name = str(row.get("symbol") or "").strip().upper()
            if active_run_symbols and symbol_name not in active_run_symbols:
                continue
            selected_pair_count += 1
            try:
                trade_count = max(0, int(row.get("trade_count") or 0))
            except Exception:
                trade_count = 0
            try:
                expectancy = float(row.get("expectancy") or 0.0)
            except Exception:
                expectancy = 0.0
            try:
                winrate = float(row.get("winrate") or 0.0)
            except Exception:
                winrate = 0.0
            selected_pair_trades += trade_count
            selected_pair_weighted_expectancy += expectancy * trade_count
            selected_pair_weighted_winrate += winrate * trade_count
            if trade_count >= 2 and expectancy >= 0.0 and winrate >= 0.40:
                selected_positive_pair_count += 1
        selected_pair_avg_expectancy = (
            selected_pair_weighted_expectancy / selected_pair_trades
            if selected_pair_trades > 0
            else 0.0
        )
        selected_pair_avg_winrate = (
            selected_pair_weighted_winrate / selected_pair_trades
            if selected_pair_trades > 0
            else 0.0
        )
        selected_quality_degraded = bool(
            pairs_selected > 0
            and selected_pair_trades > 0
            and (
                selected_positive_pair_count <= 0
                or selected_pair_avg_expectancy < -0.005
                or (
                    selected_pair_trades >= 8
                    and selected_pair_avg_winrate < 0.38
                )
            )
        )
        disable_alpha_whitelist_for_degraded_bootstrap = bool(
            selected_quality_degraded
            and selected_pair_trades > 0
            and selected_positive_pair_count <= 0
            and selected_pair_avg_expectancy < 0.0
        )
        if disable_alpha_whitelist_for_degraded_bootstrap:
            strict_block_tokens_by_key = {
                "ENTRY_SYMBOL_STRATEGY_BLOCKLIST": (
                    strict_bucket_gate.get("toxic_pair_blocklist") or []
                ),
                "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": (
                    (strict_bucket_gate.get("toxic_side_blocklist") or [])
                    + (strict_bucket_gate.get("cost_burden_side_blocklist") or [])
                ),
            }
            for env_key, blocked_tokens in strict_block_tokens_by_key.items():
                if env_key in after_overrides_cli:
                    continue
                blocked_token_set = {
                    str(token or "").strip().upper()
                    for token in blocked_tokens
                    if str(token or "").strip()
                }
                if not blocked_token_set:
                    continue
                retained_tokens = [
                    token
                    for token in _split_csv_tokens(after_overrides.get(env_key))
                    if str(token).strip().upper() not in blocked_token_set
                ]
                if retained_tokens:
                    after_overrides[env_key] = ",".join(retained_tokens)
                else:
                    after_overrides.pop(env_key, None)
            for env_key in (
                "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST",
                "ENTRY_STRATEGY_SIDE_BLOCKLIST",
            ):
                if env_key in after_overrides_cli:
                    continue
                after_overrides.pop(env_key, None)
        fallback_reasons = []
        if pairs_selected <= 0:
            fallback_reasons.append("no_pairs_selected")
        if rows_inserted <= 0:
            fallback_reasons.append("no_rows_inserted")
        if selected_quality_degraded:
            fallback_reasons.append("selected_quality_degraded")
        if runtime_contract_fail_closed:
            fallback_reasons.append("runtime_contract_fail_closed")
        fallback_allowlist_allowed = bool(
            pairs_selected > 0 and rows_inserted > 0
        )
        print(
            "ALPHA_BOOTSTRAP_SELECTION_QUALITY: "
            f"pairs_selected={pairs_selected} rows_inserted={rows_inserted} "
            f"selected_pairs={selected_pair_count} selected_trades={selected_pair_trades} "  # noqa: E501
            f"selected_positive_pairs={selected_positive_pair_count} "
            f"selected_avg_exp={selected_pair_avg_expectancy:.4f} "
            f"selected_avg_wr={selected_pair_avg_winrate:.2f} "
            f"quality_degraded={int(bool(selected_quality_degraded))}"
        )
        if fallback_reasons:
            negative_symbols = set()
            negative_symbol_strategy_pairs = set()
            negative_symbol_strategy_side_pairs = set()
            mild_symbols = set()
            ranked_symbols = []
            ranked_positive_symbols = []
            best_positive_trade_count = 0
            strategy_stats = {}
            symbol_stats = {}
            strategy_side_stats = {}
            strategy_side_ranked_candidates = []
            fallback_strategy_side_pairs = []
            pair_rows = []
            pair_side_bad_counts = {}
            pair_side_total_counts = {}
            side_aggregate = {
                "buy": {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                "sell": {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
            }
            for row in alpha_refresh_report.get("pair_stats_top") or []:
                if not isinstance(row, dict):
                    continue
                try:
                    symbol_name = str(row.get("symbol") or "").strip().upper()
                except Exception:
                    symbol_name = ""
                if (
                    not symbol_name
                    or (active_run_symbols and symbol_name not in active_run_symbols)
                ):
                    continue
                try:
                    trade_count = int(row.get("trade_count") or 0)
                except Exception:
                    trade_count = 0
                try:
                    expectancy = float(row.get("expectancy") or 0.0)
                except Exception:
                    expectancy = 0.0
                try:
                    winrate = float(row.get("winrate") or 0.0)
                except Exception:
                    winrate = 0.0
                try:
                    strategy_name = str(row.get("strategy") or "").strip()
                except Exception:
                    strategy_name = ""
                pair_rows.append(
                    {
                        "symbol": symbol_name,
                        "strategy": strategy_name,
                        "trade_count": trade_count,
                        "expectancy": expectancy,
                        "winrate": winrate,
                    }
                )
                sym_bucket = symbol_stats.setdefault(
                    symbol_name,
                    {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                )
                sym_bucket["trade_count"] += max(0, int(trade_count))
                sym_bucket["wins_weighted"] += min(1.0, max(0.0, float(winrate))) * max(
                    0, int(trade_count)
                )
                sym_bucket["net_pnl"] += float(expectancy) * max(0, int(trade_count))
                if strategy_name:
                    stats_bucket = strategy_stats.setdefault(
                        strategy_name,
                        {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                    )
                    stats_bucket["trade_count"] += max(0, int(trade_count))
                    wr_capped = min(1.0, max(0.0, float(winrate)))
                    stats_bucket["wins_weighted"] += wr_capped * max(
                        0, int(trade_count)
                    )
                    stats_bucket["net_pnl"] += float(expectancy) * max(
                        0, int(trade_count)
                    )
                if trade_count >= 5 and expectancy <= -0.15:
                    negative_symbols.add(symbol_name)
            for row in alpha_refresh_report.get("pair_side_stats_top") or []:
                if not isinstance(row, dict):
                    continue
                try:
                    symbol_name = str(row.get("symbol") or "").strip().upper()
                except Exception:
                    symbol_name = ""
                try:
                    strategy_name = str(row.get("strategy") or "").strip()
                except Exception:
                    strategy_name = ""
                try:
                    side_name = str(row.get("side") or "").strip().lower()
                except Exception:
                    side_name = ""
                if side_name in ("long",):
                    side_name = "buy"
                elif side_name in ("short",):
                    side_name = "sell"
                if (
                    not symbol_name
                    or not strategy_name
                    or side_name not in ("buy", "sell")
                    or (active_run_symbols and symbol_name not in active_run_symbols)
                ):
                    continue
                try:
                    trade_count = int(row.get("trade_count") or 0)
                except Exception:
                    trade_count = 0
                try:
                    expectancy = float(row.get("expectancy") or 0.0)
                except Exception:
                    expectancy = 0.0
                try:
                    winrate = float(row.get("winrate") or 0.0)
                except Exception:
                    winrate = 0.0
                pair_key = f"{symbol_name}:{strategy_name}"
                pair_side_total_counts[pair_key] = (
                    int(pair_side_total_counts.get(pair_key, 0)) + 1
                )
                side_stats_key = f"{strategy_name}:{side_name}"
                side_stats_bucket = strategy_side_stats.setdefault(
                    side_stats_key,
                    {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                )
                side_stats_bucket["trade_count"] += max(0, int(trade_count))
                side_stats_bucket["wins_weighted"] += min(
                    1.0, max(0.0, float(winrate))
                ) * max(0, int(trade_count))
                side_stats_bucket["net_pnl"] += float(expectancy) * max(
                    0, int(trade_count)
                )
                side_bucket = side_aggregate.setdefault(
                    side_name,
                    {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                )
                side_bucket["trade_count"] += max(0, int(trade_count))
                side_bucket["wins_weighted"] += min(
                    1.0, max(0.0, float(winrate))
                ) * max(0, int(trade_count))
                side_bucket["net_pnl"] += float(expectancy) * max(
                    0, int(trade_count)
                )
                side_bad = (
                    trade_count >= 5 and expectancy <= -0.03
                )
                if (
                    not side_bad
                    and trade_count >= 3
                    and expectancy <= -0.06
                    and winrate <= 0.40
                ):
                    side_bad = True
                if (
                    not side_bad
                    and trade_count >= 3
                    and expectancy <= -0.10
                    and winrate <= 0.20
                ):
                    side_bad = True
                if side_bad:
                    pair_side_bad_counts[pair_key] = (
                        int(pair_side_bad_counts.get(pair_key, 0)) + 1
                    )
                    negative_symbol_strategy_side_pairs.add(
                        f"{pair_key}:{side_name}"
                    )
            negative_strategy_side_pairs = set()
            known_strategy_side_pairs = set()
            positive_strategy_side_ranked = []
            for key, side_stats_bucket in strategy_side_stats.items():
                try:
                    strategy_name, side_name = str(key).split(":", 1)
                except Exception:
                    continue
                trades_side = int(side_stats_bucket.get("trade_count") or 0)
                if trades_side <= 0:
                    continue
                if side_name in ("buy", "sell") and trades_side >= 3:
                    known_strategy_side_pairs.add(f"{strategy_name}:{side_name}")
                net_side = float(side_stats_bucket.get("net_pnl") or 0.0)
                wins_side = float(side_stats_bucket.get("wins_weighted") or 0.0)
                expectancy_side = net_side / trades_side if trades_side > 0 else 0.0
                winrate_side = wins_side / trades_side if trades_side > 0 else 0.0
                if side_name in ("buy", "sell") and trades_side >= 3:
                    strategy_side_ranked_candidates.append(
                        (
                            expectancy_side,
                            winrate_side,
                            trades_side,
                            f"{strategy_name}:{side_name}",
                        )
                    )
                if (
                    side_name in ("buy", "sell")
                    and trades_side >= 6
                    and expectancy_side >= 0.0
                    and winrate_side >= 0.45
                ):
                    positive_strategy_side_ranked.append(
                        (
                            expectancy_side,
                            winrate_side,
                            trades_side,
                            f"{strategy_name}:{side_name}",
                        )
                    )
                if (
                    trades_side >= 12
                    and expectancy_side <= -0.05
                    and winrate_side <= 0.35
                ) or (
                    trades_side >= 6
                    and expectancy_side <= -0.08
                    and winrate_side <= 0.20
                ):
                    negative_strategy_side_pairs.add(
                        f"{strategy_name}:{side_name}"
                    )
            positive_strategy_side_ranked.sort(reverse=True)
            positive_strategy_side_pairs = [
                x[3] for x in positive_strategy_side_ranked[:4]
            ]
            strategy_side_ranked_candidates.sort(reverse=True)
            if not positive_strategy_side_pairs:
                for exp_side, wr_side, trades_side, key in strategy_side_ranked_candidates:  # noqa: E501
                    if trades_side < 3:
                        continue
                    if exp_side < -0.05:
                        continue
                    if wr_side < 0.22:
                        continue
                    fallback_strategy_side_pairs.append(key)
                    if len(fallback_strategy_side_pairs) >= 2:
                        break
                if not fallback_strategy_side_pairs and strategy_side_ranked_candidates:
                    fallback_strategy_side_pairs = [
                        str(strategy_side_ranked_candidates[0][3] or "").strip()
                    ]
            negative_strategies = set()
            for strategy_name, stats_bucket in strategy_stats.items():
                trades_s = int(stats_bucket.get("trade_count") or 0)
                if trades_s < 8:
                    continue
                net_s = float(stats_bucket.get("net_pnl") or 0.0)
                wins_s = float(stats_bucket.get("wins_weighted") or 0.0)
                expectancy_s = net_s / trades_s if trades_s > 0 else 0.0
                winrate_s = wins_s / trades_s if trades_s > 0 else 0.0
                if (
                    expectancy_s <= -0.07 and winrate_s <= 0.20
                ) or (
                    expectancy_s <= -0.10 and winrate_s <= 0.30
                ):
                    negative_strategies.add(strategy_name)
            positive_strategies_ranked = []
            for strategy_name, stats_bucket in strategy_stats.items():
                trades_s = int(stats_bucket.get("trade_count") or 0)
                if trades_s < 6:
                    continue
                net_s = float(stats_bucket.get("net_pnl") or 0.0)
                wins_s = float(stats_bucket.get("wins_weighted") or 0.0)
                expectancy_s = net_s / trades_s if trades_s > 0 else 0.0
                winrate_s = wins_s / trades_s if trades_s > 0 else 0.0
                if expectancy_s >= 0.0 and winrate_s >= 0.42:
                    positive_strategies_ranked.append(
                        (expectancy_s, winrate_s, trades_s, strategy_name)
                    )
            positive_strategies_ranked.sort(reverse=True)
            positive_strategies = [x[3] for x in positive_strategies_ranked[:3]]

            active_side_aggregate = {
                "buy": {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                "sell": {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
            }
            for key, bucket in strategy_side_stats.items():
                try:
                    strategy_name, side_name = str(key).split(":", 1)
                except Exception:
                    continue
                if strategy_name in negative_strategies:
                    continue
                if side_name not in ("buy", "sell"):
                    continue
                target = active_side_aggregate.setdefault(
                    side_name,
                    {"trade_count": 0, "wins_weighted": 0.0, "net_pnl": 0.0},
                )
                target["trade_count"] += int(bucket.get("trade_count") or 0)
                target["wins_weighted"] += float(bucket.get("wins_weighted") or 0.0)
                target["net_pnl"] += float(bucket.get("net_pnl") or 0.0)
            active_buy_trades = int(
                active_side_aggregate.get("buy", {}).get("trade_count") or 0
            )
            active_sell_trades = int(
                active_side_aggregate.get("sell", {}).get("trade_count") or 0
            )
            if (active_buy_trades + active_sell_trades) < 6:
                active_side_aggregate = side_aggregate

            buy_bucket = active_side_aggregate.get("buy") or {}
            sell_bucket = active_side_aggregate.get("sell") or {}
            buy_trades = int(buy_bucket.get("trade_count") or 0)
            sell_trades = int(sell_bucket.get("trade_count") or 0)
            buy_net = float(buy_bucket.get("net_pnl") or 0.0)
            sell_net = float(sell_bucket.get("net_pnl") or 0.0)
            buy_wins = float(buy_bucket.get("wins_weighted") or 0.0)
            sell_wins = float(sell_bucket.get("wins_weighted") or 0.0)
            buy_expectancy = (buy_net / buy_trades) if buy_trades > 0 else 0.0
            sell_expectancy = (sell_net / sell_trades) if sell_trades > 0 else 0.0
            buy_winrate = (buy_wins / buy_trades) if buy_trades > 0 else 0.0
            sell_winrate = (sell_wins / sell_trades) if sell_trades > 0 else 0.0

            preferred_side = "both"
            side_confidence = "low"
            if buy_trades >= 6 and buy_expectancy >= 0.0 and buy_winrate >= 0.45:
                if (
                    sell_trades < 6
                    or (
                        buy_expectancy >= sell_expectancy + 0.02
                        and buy_winrate >= sell_winrate
                    )
                ):
                    preferred_side = "buy"
                    side_confidence = "high"
            if (
                preferred_side == "both"
                and sell_trades >= 6
                and sell_expectancy >= 0.0
                and sell_winrate >= 0.45
            ):
                if (
                    buy_trades < 6
                    or (
                        sell_expectancy >= buy_expectancy + 0.02
                        and sell_winrate >= buy_winrate
                    )
                ):
                    preferred_side = "sell"
                    side_confidence = "high"
            if preferred_side == "both":
                buy_bad = (
                    buy_trades >= 6 and buy_expectancy <= -0.06 and buy_winrate <= 0.35
                )
                sell_bad = (
                    sell_trades >= 6
                    and sell_expectancy <= -0.06
                    and sell_winrate <= 0.35
                )
                if buy_bad and not sell_bad and sell_trades >= 3:
                    preferred_side = "sell"
                    side_confidence = "medium"
                elif sell_bad and not buy_bad and buy_trades >= 3:
                    preferred_side = "buy"
                    side_confidence = "medium"
            side_bias_note = "-"
            if (
                side_confidence == "low"
                and buy_trades >= 6
                and sell_trades >= 6
            ):
                exp_gap = sell_expectancy - buy_expectancy
                wr_gap = sell_winrate - buy_winrate
                if exp_gap >= 0.03 and wr_gap >= 0.00:
                    preferred_side = "sell"
                    side_bias_note = "low_confidence_sell_bias"
                elif exp_gap <= -0.03 and wr_gap <= 0.00:
                    preferred_side = "buy"
                    side_bias_note = "low_confidence_buy_bias"
            for pair_row in pair_rows:
                symbol_name = str(pair_row.get("symbol") or "").strip().upper()
                if not symbol_name:
                    continue
                strategy_name = str(pair_row.get("strategy") or "").strip()
                try:
                    trade_count = int(pair_row.get("trade_count") or 0)
                except Exception:
                    trade_count = 0
                try:
                    expectancy = float(pair_row.get("expectancy") or 0.0)
                except Exception:
                    expectancy = 0.0
                try:
                    winrate = float(pair_row.get("winrate") or 0.0)
                except Exception:
                    winrate = 0.0
                if (
                    strategy_name
                    and trade_count >= 7
                    and expectancy <= -0.04
                    and winrate <= 0.50
                ):
                    pair_key = f"{symbol_name}:{strategy_name}"
                    total_side = int(pair_side_total_counts.get(pair_key, 0))
                    bad_side = int(pair_side_bad_counts.get(pair_key, 0))
                    if total_side <= 0 or bad_side >= total_side:
                        negative_symbol_strategy_pairs.add(pair_key)
                if (
                    strategy_name
                    and trade_count >= 8
                    and expectancy <= -0.10
                    and winrate <= 0.40
                ):
                    negative_symbol_strategy_pairs.add(
                        f"{symbol_name}:{strategy_name}"
                    )
                ranked_symbols.append((expectancy, winrate, trade_count, symbol_name))
                if trade_count >= 2 and expectancy >= -0.03 and winrate >= 0.35:
                    mild_symbols.add(symbol_name)
                if expectancy > 0:
                    ranked_positive_symbols.append(
                        (expectancy, trade_count, symbol_name))
            symbol_ranked = []
            for symbol_name, sym_bucket in symbol_stats.items():
                symbol_trades = int(sym_bucket.get("trade_count") or 0)
                if symbol_trades <= 0:
                    continue
                symbol_net = float(sym_bucket.get("net_pnl") or 0.0)
                symbol_wins = float(sym_bucket.get("wins_weighted") or 0.0)
                symbol_expectancy = symbol_net / symbol_trades
                symbol_winrate = symbol_wins / symbol_trades
                symbol_ranked.append(
                    (symbol_expectancy, symbol_winrate, symbol_trades, symbol_name)
                )
                if (
                    (symbol_trades >= 8 and symbol_expectancy <= -0.05)
                    or (
                        symbol_trades >= 12
                        and symbol_expectancy <= -0.03
                        and symbol_winrate <= 0.45
                    )
                ):
                    negative_symbols.add(symbol_name)
            if symbol_ranked and len(negative_symbols) >= max(1,
                                                              len(symbol_ranked) - 1):
                symbol_ranked.sort(reverse=True)
                keep_count = 2 if len(symbol_ranked) >= 3 else 1
                keep_symbols = {x[3] for x in symbol_ranked[:keep_count]}
                negative_symbols = {
                    s for s in negative_symbols if s not in keep_symbols}
            bootstrap_total_trades = 0
            for pair_row in pair_rows:
                try:
                    bootstrap_total_trades += max(
                        0, int(pair_row.get("trade_count") or 0)
                    )
                except Exception:
                    continue
            bootstrap_confident = bool(bootstrap_total_trades >= 60)
            if ranked_positive_symbols:
                ranked_positive_symbols.sort(reverse=True)
                best_positive_trade_count = int(ranked_positive_symbols[0][1] or 0)
                mild_symbols.add(str(ranked_positive_symbols[0][2] or "").upper())
            if len(mild_symbols) < 2 and ranked_symbols:
                ranked_symbols.sort(reverse=True)
                for expectancy, _, trade_count, symbol_name in ranked_symbols:
                    if symbol_name in mild_symbols:
                        continue
                    if trade_count < 1:
                        continue
                    if expectancy < -0.06:
                        continue
                    mild_symbols.add(symbol_name)
                    if len(mild_symbols) >= 2:
                        break
            if not mild_symbols:
                ranked_symbols.sort(reverse=True)
                for expectancy, winrate, trade_count, symbol_name in ranked_symbols:
                    if trade_count < 1:
                        continue
                    if expectancy < -0.10:
                        continue
                    mild_symbols.add(symbol_name)
                    if len(mild_symbols) >= 2:
                        break
            if not mild_symbols:
                fallback_symbol = ""
                if ranked_symbols:
                    ranked_symbols.sort(reverse=True)
                    fallback_symbol = str(ranked_symbols[0][3] or "").strip().upper()
                mild_symbols.add(fallback_symbol or "SOLUSDTM")
            apply_symbol_allowlist = (
                bootstrap_confident
                and side_confidence in ("high", "medium")
                and best_positive_trade_count >= 4
                and len(mild_symbols) >= 2
            )
            allow_buy = "1"
            allow_sell = "1"
            side_gap = sell_expectancy - buy_expectancy
            medium_lock_allowed = bool(bootstrap_total_trades >= 30)
            if preferred_side == "buy" and side_confidence in ("high", "medium"):
                if side_confidence == "high" or medium_lock_allowed:
                    allow_sell = "0"
            elif preferred_side == "sell" and side_confidence in ("high", "medium"):
                if side_confidence == "high" or medium_lock_allowed:
                    allow_buy = "0"
            if (
                side_confidence == "low"
                and buy_trades >= 8
                and sell_trades >= 8
                and bootstrap_total_trades >= 40
            ):
                if side_gap >= 0.03 and sell_winrate >= buy_winrate:
                    allow_buy = "0"
                    side_bias_note = "low_confidence_sell_lock"
                elif side_gap <= -0.03 and buy_winrate >= sell_winrate:
                    allow_sell = "0"
                    side_bias_note = "low_confidence_buy_lock"
            if disable_alpha_whitelist_for_degraded_bootstrap:
                allow_buy = "1"
                allow_sell = "1"
            if runtime_contract_fail_closed:
                allow_buy = "1"
                allow_sell = "1"
            sell_require_trend = (
                "0" if (allow_sell == "1" and allow_buy == "0") else "1"
            )
            buy_score_min = ("0.20" if bootstrap_confident else "0.23")
            if side_bias_note == "low_confidence_sell_bias":
                buy_score_min = "0.23"
            elif side_bias_note == "low_confidence_buy_bias":
                buy_score_min = "0.18"
            if allow_buy == "0":
                buy_require_trend = "1"
            elif bootstrap_confident and not (
                side_confidence == "low" and buy_expectancy < sell_expectancy
            ):
                buy_require_trend = "0"
            else:
                buy_require_trend = "1"
            signal_min_votes = ("1" if bootstrap_confident else "2")
            min_vote_dominance = ("0.52" if bootstrap_confident else "0.56")
            if side_bias_note in (
                "low_confidence_sell_lock",
                    "low_confidence_buy_lock"):
                signal_min_votes = "2"
                min_vote_dominance = "0.56"
                buy_score_min = "0.23" if allow_buy == "1" else buy_score_min
            if (buy_trades + sell_trades) >= 16 and side_confidence in ("high", "medium"):  # noqa: E501
                side_expectancy_min = "0.006"
            elif (buy_trades + sell_trades) >= 10:
                side_expectancy_min = "0.003"
            else:
                side_expectancy_min = "0.000"
            if (
                (buy_trades + sell_trades) >= 20
                and buy_expectancy < 0.0
                and sell_expectancy < 0.0
            ):
                side_expectancy_min = "0.030"
            universe_exploration_enable = (
                "1"
                if (
                    (not bootstrap_confident)
                    and bootstrap_total_trades < 20
                    and side_confidence == "low"
                )
                else "0"
            )
            micro_exploration_enable = (
                "1"
                if (
                    (not bootstrap_confident)
                    and bootstrap_total_trades < 16
                    and side_confidence == "low"
                )
                else "0"
            )
            auto_after_overrides = {
                "ALPHA_WHITELIST_COLDSTART_ALLOW": "1",
                "ALPHA_WHITELIST_FALLBACK_ENABLE": "1",
                "ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS": "1",
                "ALPHA_REQUIRE_POSITIVE_UNIVERSE": "0",
                "ALPHA_UNIVERSE_EXPLORATION_ENABLE": universe_exploration_enable,
                "ALPHA_UNIVERSE_EXPLORATION_MIN_TRADES": "2",
                "ALPHA_UNIVERSE_EXPLORATION_MIN_EXPECTANCY": "0.00",
                "ALPHA_UNIVERSE_EXPLORATION_MIN_WINRATE": "0.40",
                "ALPHA_UNIVERSE_EXPLORATION_ALLOC_SCALE": "0.20",
                "ENTRY_MIN_NET_USDT": "0.10",
                "ENTRY_MIN_PROFIT_FEE_MULT": "1.20",
                "ENTRY_MIN_NET_TO_STOP_RATIO": "1.10",
                "ENTRY_SIDE_EXPECTANCY_MIN": side_expectancy_min,
                "ENTRY_SIDE_EXPECTANCY_MIN_TRADES": "2",
                "ENTRY_SIGNAL_SCORE_MIN": "0.18",
                "ENTRY_SIGNAL_SCORE_MIN_BUY": buy_score_min,
                "ENTRY_BUY_MIN_SIGNAL_SCORE": buy_score_min,
                "ENTRY_ALLOW_BUY": allow_buy,
                "ENTRY_ALLOW_SELL": allow_sell,
                "ENTRY_REQUIRE_STRATEGY_NAME": "1",
                "ENTRY_BUY_REQUIRE_TREND": buy_require_trend,
                "ENTRY_SELL_REQUIRE_TREND": sell_require_trend,
                "ENTRY_SIGNAL_MIN_VOTES": signal_min_votes,
                "ENTRY_MAX_OPPOSITE_VOTES": "1",
                "ENTRY_MIN_VOTE_DOMINANCE": min_vote_dominance,
                "ENTRY_MIN_VOTE_DELTA": "0",
                "SIDE_GUARD_MIN_TRADES": "2",
                "SIDE_GUARD_MIN_WINRATE": "0.42",
                "SIDE_GUARD_MAX_EXPECTANCY": "-0.02",
                "SIDE_GUARD_COOLDOWN_SEC": "1800",
                "LOSS_COOLDOWN_SEC": "240",
                "allocation_pct": ("0.008" if bootstrap_confident else "0.006"),
                "ENTRY_CUTOFF_BEFORE_END_SEC": str(
                    min(180, max(60, (args.after_min * 60 * 25) // 100))
                ),
                "PAPER_AUTO_CLOSE_HARD_SEC": str(
                    max(
                        (args.after_min * 60 * 40) // 100,
                        int(args.paper_auto_close_sec) * 2,
                        300,
                    )
                ),
                "PAPER_AUTO_CLOSE_MIN_PROFIT": "0.04",
                "PAPER_POST_GREEN_GIVEBACK_TRIGGER": "0.12",
                "ENTRY_REGIME_QUALITY_GATE_ENABLE": "1",
                "ENTRY_REGIME_QUALITY_GATE_BLOCKLIST": "TrendFollowing:buy:bearish",
                "MOMENTUM_SIGNAL_SCORE_THRESHOLD": "0.35",
                "MOMENTUM_EXHAUSTION_FILTER_ENABLE": "1",
                "MOMENTUM_EXHAUSTION_Z_EXTREME": "2.8",
                "MOMENTUM_EXHAUSTION_MAX_EXT_PCT": "0.0022",
                "MOMENTUM_EXHAUSTION_VOL_SPIKE_RATIO": "2.8",
                "MOMENTUM_EXHAUSTION_SPIKE_MIN_Z": "1.8",
                "ALPHA_MICRO_EXPLORATION_ENABLE": micro_exploration_enable,
                "EXIT_SL_USDT_SIDE_EXPECTANCY_ENABLE": "1",
                "EXIT_SL_USDT_EXPECTANCY_REF": "0.025",
                "EXIT_SL_USDT_EXPECTANCY_MIN_MULT": "0.70",
                "EXIT_SL_USDT_EXPECTANCY_MAX_MULT": "1.00",
                "MOMENTUM_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0006",
                "MOMENTUM_MIXED_NEVER_GREEN_HARD_FLOOR_USDT": "0.0008",
            }
            if (
                disable_alpha_whitelist_for_degraded_bootstrap
                or (
                    runtime_contract_fail_closed
                    and bool(strict_bucket_gate.get("positive_side_allowlist"))
                )
            ):
                auto_after_overrides["ALPHA_WHITELIST_ENABLE"] = "0"
            if not bootstrap_confident:
                auto_after_overrides["ENTRY_MIN_NET_USDT"] = "0.08"
                auto_after_overrides["ENTRY_MIN_PROFIT_FEE_MULT"] = "1.15"
                try:
                    side_expectancy_floor = max(0.002, float(side_expectancy_min))
                except Exception:
                    side_expectancy_floor = 0.002
                auto_after_overrides["ENTRY_SIDE_EXPECTANCY_MIN"] = (
                    f"{side_expectancy_floor:.3f}"
                )
            # Keep the validated AFTER cold-start bypass unless the operator
            # explicitly overrides it at the CLI. Bootstrap heuristics were
            # reintroducing a 0.03/2 trade gate and collapsing natural entries.
            if "ENTRY_SIDE_EXPECTANCY_MIN" not in after_overrides_cli:
                auto_after_overrides["ENTRY_SIDE_EXPECTANCY_MIN"] = "-1.0"
            if "ENTRY_SIDE_EXPECTANCY_MIN_TRADES" not in after_overrides_cli:
                auto_after_overrides["ENTRY_SIDE_EXPECTANCY_MIN_TRADES"] = "5"
            if not fallback_allowlist_allowed:
                # Missing/empty strict bootstrap evidence may only add fail-closed
                # blockers below. It must not relax entry gates or seed allowlists.
                auto_after_overrides = {}
                explicit_side_allowlist_configured = bool(
                    _split_csv_tokens(
                        after_overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST")
                    )
                )
                if (
                    rows_inserted <= 0
                    and not runtime_contract_fail_closed
                    and bool(args.paper_auto_open)
                ):
                    if not explicit_side_allowlist_configured:
                        if "SEED_TRADES_ENABLE" not in after_overrides_cli:
                            auto_after_overrides["SEED_TRADES_ENABLE"] = "1"
                        if "SEED_TRADES_LIMIT" not in after_overrides_cli:
                            auto_after_overrides["SEED_TRADES_LIMIT"] = "1"
                        if (
                            "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST"
                            not in after_overrides_cli
                        ):
                            auto_after_overrides[
                                "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST"
                            ] = "0"
                        if "ENTRY_EDGE_COLDSTART_MODE" not in after_overrides_cli:
                            auto_after_overrides["ENTRY_EDGE_COLDSTART_MODE"] = (
                                "fail_open"
                            )
                        if "DIAGNOSTIC_MODE" not in after_overrides_cli:
                            auto_after_overrides["DIAGNOSTIC_MODE"] = "1"
                        if (
                            "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION"
                            not in after_overrides_cli
                        ):
                            auto_after_overrides[
                                "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION"
                            ] = "1"
            strict_positive_side_tokens = set()
            strict_positive_symbols = set()
            strict_positive_pairs = set()
            strict_positive_strategies = set()
            for token in strict_bucket_gate.get("positive_side_allowlist") or []:
                canonical = _canonical_symbol_strategy_side_token(token)
                if not canonical:
                    continue
                strict_positive_side_tokens.add(canonical)
                symbol_key, strategy_key, _ = canonical.split(":", 2)
                strict_positive_symbols.add(symbol_key)
                strict_positive_pairs.add(f"{symbol_key}:{strategy_key}")
                strict_positive_strategies.add(strategy_key)
            if strict_positive_symbols and negative_symbols:
                negative_symbols = {
                    str(symbol_name).strip().upper()
                    for symbol_name in negative_symbols
                    if str(symbol_name).strip().upper() not in strict_positive_symbols
                }
            negative_symbols = _narrow_negative_symbols_from_side_evidence(
                negative_symbols,
                alpha_refresh_report,
                active_run_symbols=active_run_symbols,
            )
            if strict_positive_pairs and negative_symbol_strategy_pairs:
                filtered_symbol_strategy_pairs = set()
                for pair_key in negative_symbol_strategy_pairs:
                    canonical_pair = _canonical_symbol_strategy_pair_token(pair_key)
                    if canonical_pair and canonical_pair in strict_positive_pairs:
                        continue
                    filtered_symbol_strategy_pairs.add(pair_key)
                negative_symbol_strategy_pairs = filtered_symbol_strategy_pairs
            if strict_positive_side_tokens and negative_symbol_strategy_side_pairs:
                filtered_symbol_strategy_side_pairs = set()
                for pair_side_key in negative_symbol_strategy_side_pairs:
                    canonical_side = _canonical_symbol_strategy_side_token(
                        pair_side_key
                    )
                    if canonical_side and canonical_side in strict_positive_side_tokens:
                        continue
                    filtered_symbol_strategy_side_pairs.add(pair_side_key)
                negative_symbol_strategy_side_pairs = (
                    filtered_symbol_strategy_side_pairs
                )
            if runtime_contract_fail_closed and strict_positive_strategies:
                positive_strategies = [
                    strategy_name
                    for strategy_name in positive_strategies
                    if str(strategy_name).strip().upper()
                    not in strict_positive_strategies
                ]
            if negative_symbols:
                auto_after_overrides["ENTRY_SYMBOL_BLOCKLIST"] = ",".join(
                    sorted(negative_symbols)
                )
            if (
                fallback_allowlist_allowed
                and mild_symbols
                and apply_symbol_allowlist
            ):
                allow_symbols = sorted(set(mild_symbols) - set(negative_symbols))
                if not allow_symbols:
                    allow_symbols = sorted(set(mild_symbols))
                auto_after_overrides["ENTRY_SYMBOL_ALLOWLIST"] = ",".join(
                    allow_symbols
                )
            if negative_symbol_strategy_pairs:
                auto_after_overrides["ENTRY_SYMBOL_STRATEGY_BLOCKLIST"] = ",".join(
                    sorted(negative_symbol_strategy_pairs)
                )
            if (
                negative_symbol_strategy_side_pairs
                and not disable_alpha_whitelist_for_degraded_bootstrap
                and not runtime_contract_fail_closed
            ):
                auto_after_overrides["ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST"] = ",".join(
                    sorted(negative_symbol_strategy_side_pairs)
                )
            if (
                negative_strategy_side_pairs
                and bootstrap_total_trades >= 24
                and not disable_alpha_whitelist_for_degraded_bootstrap
                and not runtime_contract_fail_closed
            ):
                candidate_block = set(negative_strategy_side_pairs)
                blocks_all_known = bool(
                    known_strategy_side_pairs
                    and candidate_block.issuperset(known_strategy_side_pairs)
                )
                if blocks_all_known and not positive_strategy_side_pairs:
                    ranked_known_sides = []
                    for side_key in known_strategy_side_pairs:
                        stats_bucket = strategy_side_stats.get(side_key) or {}
                        trades_side = int(stats_bucket.get("trade_count") or 0)
                        if trades_side <= 0:
                            continue
                        net_side = float(stats_bucket.get("net_pnl") or 0.0)
                        wins_side = float(stats_bucket.get("wins_weighted") or 0.0)
                        ranked_known_sides.append(
                            (
                                net_side / trades_side,
                                wins_side / trades_side,
                                trades_side,
                                side_key,
                            )
                        )
                    ranked_known_sides.sort(reverse=True)
                    keep_count = 2 if len(ranked_known_sides) >= 3 else 1
                    keep_side_keys = {x[3] for x in ranked_known_sides[:keep_count]}
                    candidate_block = {
                        x for x in candidate_block if x not in keep_side_keys
                    }
                if candidate_block:
                    auto_after_overrides["ENTRY_STRATEGY_SIDE_BLOCKLIST"] = ",".join(
                        sorted(candidate_block)
                    )
            if fallback_allowlist_allowed and positive_strategy_side_pairs:
                auto_after_overrides["ENTRY_STRATEGY_SIDE_ALLOWLIST"] = ",".join(
                    sorted(set(positive_strategy_side_pairs))
                )
            elif (
                fallback_allowlist_allowed
                and fallback_strategy_side_pairs
                and bootstrap_total_trades >= 20
                and side_confidence in ("high", "medium")
                and (buy_expectancy >= 0.0 or sell_expectancy >= 0.0)
            ):
                auto_after_overrides["ENTRY_STRATEGY_SIDE_ALLOWLIST"] = ",".join(
                    sorted(set(fallback_strategy_side_pairs))
                )
            if fallback_allowlist_allowed and positive_strategies:
                auto_after_overrides["ENTRY_STRATEGY_ALLOWLIST"] = ",".join(
                    sorted(set(positive_strategies))
                )
            if negative_strategies and bootstrap_confident and positive_strategies:
                try:
                    existing_disabled = {
                        x.strip()
                        for x in str(
                            after_overrides.get("DISABLE_STRATEGIES", "")
                        ).split(",")
                        if x.strip()
                    }
                except Exception:
                    existing_disabled = set()
                known_strategies = {
                    str(s).strip()
                    for s, b in strategy_stats.items()
                    if str(s).strip() and int((b or {}).get("trade_count") or 0) >= 4
                }
                disabled_target = set(existing_disabled) | set(negative_strategies)
                remaining_known = (
                    known_strategies - disabled_target if known_strategies else set()
                )
                if remaining_known or not known_strategies:
                    auto_after_overrides["DISABLE_STRATEGIES"] = ",".join(
                        sorted(disabled_target)
                    )
            exact_symbol_side_allowlist_active = bool(
                _split_csv_tokens(
                    after_overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST")
                )
            )
            for key, value in auto_after_overrides.items():
                k = str(key)
                v = str(value)
                if (
                    exact_symbol_side_allowlist_active
                    and k == "ENTRY_STRATEGY_SIDE_ALLOWLIST"
                ):
                    continue
                # Respect explicit CLI overrides from the operator.
                if k in after_overrides_cli:
                    continue
                if k in merge_csv_keys and k in after_overrides:
                    merged = _merge_csv_values(after_overrides.get(k), v)
                    if merged:
                        after_overrides[k] = merged
                    else:
                        after_overrides.pop(k, None)
                else:
                    after_overrides.setdefault(k, v)
            print(
                "ALPHA_BOOTSTRAP_FALLBACK_MODE: "
                f"pairs_selected={pairs_selected} rows_inserted={rows_inserted} "
                f"reasons={','.join(fallback_reasons)} "
                f"selected_avg_exp={selected_pair_avg_expectancy:.4f} "
                f"selected_avg_wr={selected_pair_avg_winrate:.2f} "
                f"bootstrap_trades={bootstrap_total_trades} bootstrap_confident={int(bool(bootstrap_confident))} "  # noqa: E501
                f"fallback_allowlist_allowed={int(bool(fallback_allowlist_allowed))} "
                f"preferred_side={preferred_side} side_confidence={side_confidence} "
                f"side_bias={side_bias_note} "
                f"buy_trades={buy_trades} buy_exp={buy_expectancy:.4f} buy_wr={buy_winrate:.2f} "  # noqa: E501
                f"sell_trades={sell_trades} sell_exp={sell_expectancy:.4f} sell_wr={sell_winrate:.2f} "  # noqa: E501
                f"allowlist={','.join(sorted(mild_symbols)) or '-'} "
                f"allowlist_applied={int(bool(apply_symbol_allowlist))} "
                f"blocklist={','.join(sorted(negative_symbols)) or '-'} "
                f"pair_blocklist={','.join(sorted(negative_symbol_strategy_pairs)) or '-'} "  # noqa: E501
                f"pair_side_blocklist={','.join(sorted(negative_symbol_strategy_side_pairs)) or '-'} "  # noqa: E501
                f"strategy_side_blocklist={','.join(sorted(negative_strategy_side_pairs)) or '-'} "  # noqa: E501
                f"strategy_side_allowlist_applied={auto_after_overrides.get('ENTRY_STRATEGY_SIDE_ALLOWLIST', '-') or '-'} "  # noqa: E501
                f"strategy_allowlist={','.join(sorted(positive_strategies)) or '-'} "
                f"disable_strategies={','.join(sorted(negative_strategies)) or '-'} "
                f"auto_after_overrides={len(auto_after_overrides)}"
            )
            # ---- Faza 1A/1B/1C: REGIME DEADLOCK DETECTION ----
            try:
                _rdd_sss = strategy_side_stats
            except NameError:
                _rdd_sss = {}
            _resolve_regime_deadlock_expansion(
                after_overrides=after_overrides,
                after_overrides_cli=after_overrides_cli,
                strategy_side_stats=_rdd_sss,
                positive_side_fallback_used=positive_side_fallback_used,
                active_run_symbols=active_run_symbols,
            )

    run_id = _resolve_run_id(args.run_id)
    positive_side_allowlist_contract = _derive_positive_side_allowlist_contract(
        strict_bucket_gate
    )
    entry_admission_contract = _derive_entry_admission_contract(
        variant_only=args.variant_only,
        symbols=symbols,
        paper_auto_open=bool(args.paper_auto_open),
        after_overrides=after_overrides,
        alpha_bootstrap_runtime_contract=alpha_bootstrap_runtime_contract,
        strict_bucket_gate=strict_bucket_gate,
    )
    print(
        "ENTRY_ADMISSION_CONTRACT: "
        f"status={entry_admission_contract.get('status')} "
        f"classification={entry_admission_contract.get('validation_classification')} "
        f"profit_valid={int(bool(entry_admission_contract.get('profit_valid')))} "
        f"invalid_reason={entry_admission_contract.get('invalid_reason') or '-'} "
        "allowlist_contract_type="
        f"{entry_admission_contract.get('allowlist_contract_type') or '-'} "
        "one_sided_allowlist_detected="
        f"{int(bool(entry_admission_contract.get('one_sided_allowlist_detected')))} "
        f"reasons={','.join(entry_admission_contract.get('reason_codes') or []) or '-'}"
    )
    if str(entry_admission_contract.get("status") or "").upper() == "FAIL_CLOSED":
        contract_path = _write_entry_admission_contract_artifact(
            run_id=run_id,
            contract=entry_admission_contract,
        )
        reason_txt = (
            ",".join(entry_admission_contract.get("reason_codes") or [])
            or "ENTRY_ADMISSION_FAIL_CLOSED"
        )
        print(f"ENTRY_ADMISSION_CONTRACT_JSON={contract_path}")
        raise SystemExit(
            "CONTROLLED_KPI_ENTRY_ADMISSION_CONTRACT_FAIL "
            "controlled_kpi_entry_admission_contract_failed "
            f"artifact={contract_path} reasons={reason_txt}"
        )
    print(
        "ALPHA_BOOTSTRAP_SOURCE: "
        f"url='{args.alpha_bootstrap_source_db_url}' "
        f"glob='{args.alpha_bootstrap_source_db_glob}'"
    )
    run_before = args.variant_only in ("both", "before")
    run_after = args.variant_only in ("both", "after")
    results_by_variant = {}
    before = None
    after = None
    if run_before:
        before = _run_variant(
            "before",
            args.before_min * 60,
            run_id,
            use_mock=args.use_mock,
            market_type=args.market_type,
            run_symbols=run_symbols,
            paper_auto_open=args.paper_auto_open,
            paper_auto_close_sec=args.paper_auto_close_sec,
            equity_snapshot_sec=args.equity_snapshot_sec,
            quality_profile=args.quality_profile,
            alpha_bootstrap_source_db_url=args.alpha_bootstrap_source_db_url,
            alpha_bootstrap_source_db_glob=args.alpha_bootstrap_source_db_glob,
            variant_overrides=before_overrides,
        )
        results_by_variant["before"] = before
    if run_after:
        after = _run_variant(
            "after",
            args.after_min * 60,
            run_id,
            use_mock=args.use_mock,
            market_type=args.market_type,
            run_symbols=run_symbols,
            paper_auto_open=args.paper_auto_open,
            paper_auto_close_sec=args.paper_auto_close_sec,
            equity_snapshot_sec=args.equity_snapshot_sec,
            quality_profile=args.quality_profile,
            alpha_bootstrap_source_db_url=args.alpha_bootstrap_source_db_url,
            alpha_bootstrap_source_db_glob=args.alpha_bootstrap_source_db_glob,
            variant_overrides=after_overrides,
        )
        results_by_variant["after"] = after

    primary_summary_bundle = {}
    for variant_name in ("after", "before"):
        variant_metrics = results_by_variant.get(variant_name)
        summary_bundle = _build_entry_gate_summary_artifact(
            run_id=run_id,
            variant_metrics=variant_metrics,
        )
        if not summary_bundle:
            continue
        variant_metrics.update(summary_bundle)
        if not primary_summary_bundle:
            primary_summary_bundle = dict(summary_bundle)

    delta = {}
    if before is not None and after is not None:
        delta = {
            "net_pnl_delta": after["net_pnl"] - before["net_pnl"],
            "winrate_delta_pct_points": (after["winrate"] - before["winrate"]) * 100.0,
            "max_drawdown_delta_pct_points": (after["max_drawdown"] - before["max_drawdown"])  # noqa: E501
            * 100.0,
            "profit_factor_delta": (
                (after["profit_factor"] - before["profit_factor"])
                if all(
                    x not in (float("inf"), float("-inf"))
                    for x in (before["profit_factor"], after["profit_factor"])
                )
                else None
            ),
            "trade_count_delta": after["trade_count"] - before["trade_count"],
            "decisions_count_delta": after["decisions_count"] - before["decisions_count"],  # noqa: E501
        }

    report = {
        "run_id": run_id,
        "params": {
            "variant_only": args.variant_only,
            "symbols": symbols,
            "market_type": args.market_type,
            "timeframe": args.timeframe,
            "use_mock": args.use_mock,
            "paper_auto_open": args.paper_auto_open,
            "paper_auto_close_sec": args.paper_auto_close_sec,
            "equity_snapshot_sec": args.equity_snapshot_sec,
            "quality_profile": args.quality_profile,
            "before_min": args.before_min,
            "after_min": args.after_min,
            "alpha_bootstrap_source_db_url": args.alpha_bootstrap_source_db_url,
            "alpha_bootstrap_source_db_glob": args.alpha_bootstrap_source_db_glob,
            "alpha_bootstrap_auto_refresh": bool(
                args.alpha_bootstrap_auto_refresh),
            "alpha_bootstrap_build_output": args.alpha_bootstrap_build_output,
            "alpha_bootstrap_build_glob": args.alpha_bootstrap_build_glob,
            "alpha_bootstrap_build_max_sources": args.alpha_bootstrap_build_max_sources,
            "alpha_bootstrap_build_max_per_source": args.alpha_bootstrap_build_max_per_source,  # noqa: E501
            "alpha_bootstrap_build_max_total": args.alpha_bootstrap_build_max_total,
            "alpha_bootstrap_build_min_abs_pnl": args.alpha_bootstrap_build_min_abs_pnl,
            "alpha_bootstrap_build_min_pair_trades": args.alpha_bootstrap_build_min_pair_trades,  # noqa: E501
            "alpha_bootstrap_build_min_pair_winrate": args.alpha_bootstrap_build_min_pair_winrate,  # noqa: E501
            "alpha_bootstrap_build_min_pair_expectancy": args.alpha_bootstrap_build_min_pair_expectancy,  # noqa: E501
            "alpha_bootstrap_build_fallback_top_pairs": args.alpha_bootstrap_build_fallback_top_pairs,  # noqa: E501
            "alpha_bootstrap_build_fallback_positive_side_pairs": args.alpha_bootstrap_build_fallback_positive_side_pairs,  # noqa: E501
            "alpha_bootstrap_build_min_side_trades": args.alpha_bootstrap_build_min_side_trades,  # noqa: E501
            "alpha_bootstrap_build_min_side_winrate": args.alpha_bootstrap_build_min_side_winrate,  # noqa: E501
            "alpha_bootstrap_build_min_side_expectancy": args.alpha_bootstrap_build_min_side_expectancy,  # noqa: E501
            "alpha_bootstrap_build_report_json": args.alpha_bootstrap_build_report_json,
            "alpha_bootstrap_accepted_scorecard": (
                args.alpha_bootstrap_accepted_scorecard
            ),
            "before_env_overrides_cli": before_overrides_cli,
            "after_env_overrides_cli": after_overrides_cli,
            "auto_after_overrides": auto_after_overrides,
            "before_env_overrides": before_overrides,
            "after_env_overrides": after_overrides,
        },
        "alpha_bootstrap_refresh": alpha_refresh,
        "alpha_bootstrap_runtime_contract": alpha_bootstrap_runtime_contract,
        "alpha_bootstrap_strict_bucket_gate": strict_bucket_gate,
        "positive_side_allowlist_contract": positive_side_allowlist_contract,
        "entry_admission_contract": entry_admission_contract,
        "profit_valid": bool(entry_admission_contract.get("profit_valid")),
        "invalid_reason": str(entry_admission_contract.get("invalid_reason") or ""),
        "allowlist_contract_type": str(
            entry_admission_contract.get("allowlist_contract_type") or "none"
        ),
        "one_sided_allowlist_detected": bool(
            entry_admission_contract.get("one_sided_allowlist_detected")
        ),
        "data_check": data_check,
        "variants_run": list(
            results_by_variant.keys()),
        "summary_json": primary_summary_bundle.get("summary_json", ""),
        "entry_gate_report_path": primary_summary_bundle.get(
            "entry_gate_report_path", ""
        ),
        "summary": primary_summary_bundle.get("summary", {}),
        "before": before,
        "after": after,
        "delta": delta,
    }

    json_path = RESULTS_DIR / f"controlled_kpi_{run_id}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)

    csv_path = RESULTS_DIR / f"controlled_kpi_{run_id}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "variant",
                "trade_count",
                "net_pnl",
                "winrate",
                "max_drawdown",
                "profit_factor",
                "gross_profit",
                "gross_loss_abs",
                "decisions_count",
                "equity_points",
                "duration_sec_actual",
                "db_path",
            ]
        )
        ordered_rows = []
        if before is not None:
            ordered_rows.append(before)
        if after is not None:
            ordered_rows.append(after)
        for row in ordered_rows:
            writer.writerow(
                [
                    row["variant"],
                    row["trade_count"],
                    row["net_pnl"],
                    row["winrate"],
                    row["max_drawdown"],
                    row["profit_factor"],
                    row["gross_profit"],
                    row["gross_loss_abs"],
                    row["decisions_count"],
                    row["equity_points"],
                    row["duration_sec_actual"],
                    row["db_path"],
                ]
            )

    diagnostic_summary_paths = []
    for variant_metrics in (before, after):
        if not isinstance(variant_metrics, dict):
            continue
        env_flags = variant_metrics.get("diagnostic_env_flags") or {}
        if str(env_flags.get("DIAGNOSTIC_MODE") or "0") != "1":
            continue
        summary = _build_diagnostic_runtime_summary(
            db_path=Path(str(variant_metrics.get("db_path") or "")),
            run_id=run_id,
            started_at_utc=str(variant_metrics.get("started_at_utc") or ""),
            ended_at_utc=str(variant_metrics.get("ended_at_utc") or ""),
            variant=str(variant_metrics.get("variant") or ""),
            symbols=_parse_symbols(args.symbols),
            env_flags=env_flags,
            metrics=variant_metrics,
        )
        out_path = _write_diagnostic_runtime_summary(
            summary, f"{run_id}_{variant_metrics.get('variant')}")
        if out_path is not None:
            diagnostic_summary_paths.append(str(out_path))

    if before is not None:
        print(_format_metrics_line("BEFORE", before))
    if after is not None:
        print(_format_metrics_line("AFTER", after))
    if delta:
        delta_msg = (
            "DELTA: "
            f"net_pnl={delta['net_pnl_delta']:.6f}, "
            f"winrate_pp={delta['winrate_delta_pct_points']:.2f}, "
            f"max_dd_pp={delta['max_drawdown_delta_pct_points']:.2f}, "
            f"profit_factor_delta={delta['profit_factor_delta']}, "
            f"trade_count_delta={delta['trade_count_delta']}, "
            f"decisions_count_delta={delta['decisions_count_delta']}"
        )
        print(delta_msg)
    print(f"REPORT_JSON={json_path}")
    print(f"REPORT_CSV={csv_path}")
    if diagnostic_summary_paths:
        print("DIAGNOSTIC_REPORT_JSON=" + ",".join(diagnostic_summary_paths))

    failed_returncodes = []
    for variant_name, variant_metrics in results_by_variant.items():
        if not isinstance(variant_metrics, dict):
            continue
        process_returncode = int(variant_metrics.get("process_returncode", 0) or 0)
        if process_returncode == 0:
            continue
        log_health = variant_metrics.get("log_health") or {}
        sample_errors = log_health.get("sample_errors") or []
        reason = str(sample_errors[0] if sample_errors else "subprocess_failed")
        print(
            "RUN_FAILURE: "
            f"variant={variant_name} returncode={process_returncode} "
            f"reason={reason}"
        )
        failed_returncodes.append(process_returncode)
    if failed_returncodes:
        raise SystemExit(failed_returncodes[0] or 1)


if __name__ == "__main__":
    main()
