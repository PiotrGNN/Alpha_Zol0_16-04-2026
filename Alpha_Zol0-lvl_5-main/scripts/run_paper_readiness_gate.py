import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
TMP_DIR = WORKDIR / "tmp"
RESULTS_DIR = WORKDIR / "results"
ANALYSIS_DIR = WORKDIR / "analysis"
DIAGNOSTICS_DIR = WORKDIR / "artifacts" / "diagnostics"
PAPER_REPORT_DIR = WORKDIR / "reports" / "paper_readiness"
EVIDENCE_CONTRACT_VERSION = "paper_readiness_v2"
STRICT_BOOTSTRAP_MANIFEST_NAME = "zol0_profitability_audit_strict_bootstrap_manifest.json"
STRICT_CORPUS_STATUS_CURRENT_NAME = "zol0_strict_bucket_gate_fresh_corpus_status_current.json"
FORBIDDEN_SHARED_ARTIFACT_NAMES = {
    "x.db",
    "x.json",
    "x.csv",
    "x_summary.json",
}
DEFAULT_GATE_AFTER_ENV_OVERRIDES = {
    "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST": "0",
}
ETH_MOMENTUM_BUY_AFTER_ENV_PRESET = "eth_momentum_buy_after"


def _eth_momentum_buy_after_env_overrides() -> dict[str, str]:
    missing_source_path = (
        WORKDIR / "tmp" / "alpha_bootstrap_missing_eth_momentum_buy_gate.db"
    ).resolve()
    missing_source_posix = missing_source_path.as_posix()
    return {
        "ALPHA_BOOTSTRAP_SOURCE_DB_URL": f"sqlite:///{missing_source_posix}",
        "ALPHA_BOOTSTRAP_SOURCE_DB_GLOB": missing_source_posix,
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": "ETHUSDTM:MOMENTUM:buy",
        "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "ETHUSDTM:TRENDFOLLOWING:buy",
        "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST": "1",
        "ALPHA_WHITELIST_ENABLE": "0",
        "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
        "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
        "ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS": "0",
    }


def _resolve_run_after_env_overrides(run_item: dict) -> dict[str, str]:
    resolved = {}
    preset_name = str(run_item.get("after_env_preset") or "").strip()
    if preset_name == ETH_MOMENTUM_BUY_AFTER_ENV_PRESET:
        resolved.update(_eth_momentum_buy_after_env_overrides())

    explicit = run_item.get("after_env_overrides") or {}
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            key_txt = str(key or "").strip()
            if not key_txt:
                continue
            resolved[key_txt] = str(value)
    return resolved


def _build_gate_after_env_args(after_env_overrides: dict | None = None) -> list[str]:
    merged = dict(DEFAULT_GATE_AFTER_ENV_OVERRIDES)
    if isinstance(after_env_overrides, dict):
        for key, value in after_env_overrides.items():
            key_txt = str(key or "").strip()
            if not key_txt:
                continue
            merged[key_txt] = str(value)

    args = []
    for key in sorted(merged):
        args.extend(["--after-env", f"{key}={merged[key]}"])
    return args


RUN_MATRIX = [
    {
        "run_id": "paper_gate_run_a_eth",
        "symbols": "ETHUSDTM",
        "summary_hours": 1,
        "after_env_preset": ETH_MOMENTUM_BUY_AFTER_ENV_PRESET,
    },
    {
        "run_id": "paper_gate_run_b_btc_sol",
        "symbols": "BTCUSDTM,SOLUSDTM",
        "summary_hours": 1,
    },
    {
        "run_id": "paper_gate_run_c_btc",
        "symbols": "BTCUSDTM",
        "summary_hours": 2,
    },
    {
        "run_id": "paper_gate_run_d_xrp",
        "symbols": "XRPUSDTM",
        "summary_hours": 2,
    },
]


def _paper_env():
    env = os.environ.copy()
    env["LIVE"] = "0"
    env["BOT_MODE"] = "paper"
    env["PAPER_RUN_ONCE"] = "1"
    env["USE_MOCK"] = "0"
    env["ZOL0_ALLOW_MOCK"] = "0"
    env["ZOL0_TOKEN"] = env.get("ZOL0_TOKEN") or "testtoken"
    return env


def _dedupe_codes(codes: list[str]) -> list[str]:
    out = []
    seen = set()
    for code in codes:
        txt = str(code or "").strip()
        if not txt or txt in seen:
            continue
        out.append(txt)
        seen.add(txt)
    return out


def _safe_float(value, default=None):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _resolve_repo_path(path_text: str | Path) -> Path:
    txt = str(path_text or "").strip()
    if not txt:
        return (WORKDIR / "__codex_missing_artifact_path__").resolve()
    path = Path(txt)
    if not path.is_absolute():
        path = (WORKDIR / path).resolve()
    return path


def _normalize_artifact_key(path: Path) -> str:
    return str(path.resolve()).lower()


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _scope_bool_false(value) -> bool:
    if isinstance(value, bool):
        return value is False
    return str(value or "").strip().lower() in {"0", "false", "no", ""}


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


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _preferred_or_latest_file(
    *,
    directory: Path,
    preferred_names: list[str],
    glob_patterns: list[str],
) -> Path | None:
    for name in preferred_names:
        candidate = directory / name
        if candidate.exists():
            return candidate

    matches = []
    for pattern in glob_patterns:
        matches.extend(directory.glob(pattern))
    if not matches:
        return None
    unique_matches = {path.resolve() for path in matches if path.exists()}
    if not unique_matches:
        return None
    return sorted(unique_matches, key=lambda p: p.stat().st_mtime)[-1]


def _glob_candidate_files(*, directory: Path, glob_patterns: list[str]) -> list[Path]:
    matches = []
    for pattern in glob_patterns:
        matches.extend(directory.glob(pattern))
    unique_matches = {path.resolve() for path in matches if path.exists()}
    return sorted(unique_matches, key=lambda p: p.stat().st_mtime, reverse=True)


def _scorecard_uses_forced_startup_allowlist(payload: dict) -> bool:
    metadata = payload.get("metadata") or {}
    selection = metadata.get("selection") or {}
    sources = metadata.get("sources") or {}
    accepted_manifest_path = str(
        sources.get("accepted_corpus_manifest_path")
        or selection.get("accepted_manifest_path")
        or ""
    ).strip()
    if not accepted_manifest_path:
        return False

    manifest_path = _resolve_repo_path(accepted_manifest_path)
    if not manifest_path.exists():
        return False

    try:
        manifest_payload = _load_json(manifest_path)
    except Exception:
        return False

    entries = list(manifest_payload.get("entries") or [])
    if not entries:
        return False

    inspected_runs = 0
    forced_runs = 0
    for entry in entries:
        bundled = entry.get("bundled_artifacts") or {}
        result_json = bundled.get("result_json") or {}
        result_path_txt = str(result_json.get("path") or "").strip()
        if not result_path_txt:
            continue
        result_path = _resolve_repo_path(result_path_txt)
        if not result_path.exists():
            continue
        try:
            result_payload = _load_json(result_path)
        except Exception:
            continue

        params = result_payload.get("params") or {}
        after_env_overrides = params.get("after_env_overrides") or {}
        allowlist = str(
            after_env_overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST") or ""
        ).strip()
        startup_enable = str(
            after_env_overrides.get("PAPER_AUTO_OPEN_STARTUP_ENABLE") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        inspected_runs += 1
        if allowlist and startup_enable:
            forced_runs += 1

    return inspected_runs > 0 and forced_runs == inspected_runs


def _select_corpus_scorecard_path() -> Path | None:
    glob_patterns = [
        "zol0_profitability_audit_scorecard*.json",
        "zol0_profitability_audit_*_scorecard.json",
    ]
    candidates = _glob_candidate_files(
        directory=ANALYSIS_DIR,
        glob_patterns=glob_patterns,
    )
    for candidate in candidates:
        try:
            payload = _load_json(candidate)
        except Exception:
            continue
        global_kpis = payload.get("global_kpis") or {}
        total_trade_count = _safe_int(global_kpis.get("total_trade_count"), 0)
        metadata = payload.get("metadata") or {}
        selection = metadata.get("selection") or {}
        sources = metadata.get("sources") or {}
        selection_source = str(selection.get("selection_source") or "").strip()
        accepted_manifest_path = str(
            sources.get("accepted_corpus_manifest_path")
            or selection.get("accepted_manifest_path")
            or ""
        ).strip()
        if (
            selection_source == "accepted_manifest"
            and accepted_manifest_path
            and total_trade_count > 0
        ):
            if _scorecard_uses_forced_startup_allowlist(payload):
                continue
            return candidate
    return _preferred_or_latest_file(
        directory=ANALYSIS_DIR,
        preferred_names=[
            "zol0_profitability_audit_scorecard.json",
            "zol0_profitability_audit_scorecard_locked_20260409_034428.json",
        ],
        glob_patterns=glob_patterns,
    )


def _parse_report_json_path(stdout_text: str) -> Path:
    for line in (stdout_text or "").splitlines():
        if line.startswith("REPORT_JSON="):
            return _resolve_repo_path(line.split("=", 1)[1].strip())
    raise RuntimeError("controlled_kpi_run_missing_report_json")


def _parse_entry_admission_contract_json_path(text: str) -> Path | None:
    for line in (text or "").splitlines():
        if "ENTRY_ADMISSION_CONTRACT_JSON=" in line:
            raw = line.split("ENTRY_ADMISSION_CONTRACT_JSON=", 1)[1].strip()
            if raw:
                return _resolve_repo_path(raw)
        if "artifact=" in line:
            raw = line.split("artifact=", 1)[1].split()[0].strip()
            if raw:
                return _resolve_repo_path(raw)
    return None


def _classify_run_exception(exc: Exception) -> str:
    text = str(exc or "").strip()
    if "MOCK_OHLCV_BLOCKED_KUCOIN_PAPER" in text:
        return "MOCK_OHLCV_BLOCKED_KUCOIN_PAPER"
    if "controlled_kpi_entry_admission_contract_failed" in text:
        return "ENTRY_ADMISSION_CONTRACT_FAIL"
    if "controlled_kpi_run_missing_report_json" in text:
        return "CONTROLLED_KPI_REPORT_JSON_MISSING"
    if "report_entry_gate_decision_summary failed" in text:
        return "SUMMARY_GENERATION_FAILED"
    if "controlled_kpi_run failed" in text:
        return "CONTROLLED_KPI_RUN_FAILED"
    return "READINESS_RUN_EXCEPTION"


def _resolve_alpha_bootstrap_runtime_contract(report: dict) -> dict:
    payload = report if isinstance(report, dict) else {}

    explicit = payload.get("alpha_bootstrap_runtime_contract")
    if isinstance(explicit, dict):
        explicit_status = str(explicit.get("status") or "").strip().upper()
        if explicit_status in {"PASS", "FAIL_CLOSED"}:
            explicit_reasons = _dedupe_codes(list(explicit.get("reason_codes") or []))
            if (
                explicit_status == "FAIL_CLOSED"
                and "source_fail_closed" not in explicit_reasons
            ):
                explicit_reasons = ["source_fail_closed"] + explicit_reasons
            return {
                "status": explicit_status,
                "source": "explicit_alpha_bootstrap_runtime_contract",
                "reason_codes": explicit_reasons,
            }

    refresh = payload.get("alpha_bootstrap_refresh")
    if isinstance(refresh, dict):
        refresh_fail_closed = bool(refresh.get("source_fail_closed"))
        refresh_status = "FAIL_CLOSED" if refresh_fail_closed else "PASS"
        refresh_reasons = []
        if refresh_fail_closed:
            refresh_reasons.append("source_fail_closed")
        refresh_reasons.extend(list(refresh.get("reason_codes") or []))
        return {
            "status": refresh_status,
            "source": "fallback_alpha_bootstrap_refresh",
            "reason_codes": _dedupe_codes(refresh_reasons),
        }

    params = payload.get("params")
    after_env = params.get("after_env_overrides") if isinstance(params, dict) else {}
    if isinstance(after_env, dict):
        fail_closed_env = {
            "ALPHA_WHITELIST_ENABLE": "0",
            "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
            "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
            "ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS": "0",
        }
        if all(
            str(after_env.get(key) or "").strip() == expected
            for key, expected in fail_closed_env.items()
        ):
            return {
                "status": "FAIL_CLOSED",
                "source": "fallback_after_env_overrides",
                "reason_codes": ["source_fail_closed_inferred_from_after_env"],
            }

    return {
        "status": "PASS",
        "source": "fallback_default_pass",
        "reason_codes": [],
    }


def _resolve_forced_cycle_trigger_contract(after_report: dict) -> dict:
    payload = after_report if isinstance(after_report, dict) else {}

    explicit = payload.get("post_promotion_forced_cycle_trigger_contract")
    if isinstance(explicit, dict):
        active = bool(explicit.get("active"))
        explicit_ok = bool(explicit.get("ok", True))
        explicit_status = str(explicit.get("status") or "").strip().lower()
        explicit_reasons = _dedupe_codes(list(explicit.get("reason_codes") or []))

        if not active:
            return {
                "status": "INACTIVE",
                "source": "explicit_post_promotion_forced_cycle_trigger_contract",
                "reason_codes": [],
            }

        if explicit_status == "ok" and explicit_ok:
            return {
                "status": "OK",
                "source": "explicit_post_promotion_forced_cycle_trigger_contract",
                "reason_codes": [],
            }

        reasons = list(explicit_reasons)
        if not reasons:
            reasons = ["forced_cycle_trigger_contract_mismatch"]
        return {
            "status": "MISMATCH",
            "source": "explicit_post_promotion_forced_cycle_trigger_contract",
            "reason_codes": _dedupe_codes(reasons),
        }

    requested = bool(payload.get("post_promotion_forced_cycle_requested"))
    observed_mode = str(
        payload.get("post_promotion_forced_cycle_trigger_mode") or ""
    ).strip()
    observed_reason = str(
        payload.get("post_promotion_forced_cycle_request_reason") or ""
    ).strip()

    if not requested:
        if observed_mode or observed_reason:
            return {
                "status": "MISMATCH",
                "source": "fallback_after_report_fields",
                "reason_codes": [
                    "forced_cycle_trigger_fields_present_without_request"
                ],
            }
        return {
            "status": "INACTIVE",
            "source": "fallback_after_report_fields",
            "reason_codes": [],
        }

    expected_mode = "after_unknown"
    expected_reason = "post_promotion_forced_cycle"
    if bool(payload.get("post_promotion_reeval_completed")):
        expected_mode = "after_reeval_completed"
        expected_reason = "post_promotion_forced_cycle"
    elif (
        str(payload.get("post_promotion_reeval_result") or "").strip()
        == "request_enqueue_failed"
    ):
        expected_mode = "after_reeval_enqueue_failure"
        expected_reason = "post_promotion_forced_cycle_after_enqueue_failure"

    reason_codes = []
    if not observed_mode:
        reason_codes.append("forced_cycle_trigger_mode_missing")
    if not observed_reason:
        reason_codes.append("forced_cycle_request_reason_missing")
    if observed_mode and observed_mode != expected_mode:
        reason_codes.append("forced_cycle_trigger_mode_mismatch")
    if observed_reason and observed_reason != expected_reason:
        reason_codes.append("forced_cycle_request_reason_mismatch")

    return {
        "status": "OK" if not reason_codes else "MISMATCH",
        "source": "fallback_after_report_fields",
        "reason_codes": _dedupe_codes(reason_codes),
    }


def _run_controlled_kpi(
    symbols: str,
    run_id: str,
    summary_hours: int,
    after_env_overrides: dict | None = None,
) -> dict:
    cmd = [
        sys.executable,
        str((WORKDIR / "scripts" / "controlled_kpi_run.py").resolve()),
        "--variant-only",
        "after",
        "--after-min",
        "2",
        "--paper-auto-open",
        "--paper-auto-close-sec",
        "20",
        "--quality-profile",
        "--no-alpha-bootstrap-auto-refresh",
        "--symbols",
        symbols,
        "--market-type",
        "futures",
        "--timeframe",
        "1",
    ]
    cmd.extend(_build_gate_after_env_args(after_env_overrides))
    proc = subprocess.run(
        cmd,
        cwd=str(WORKDIR),
        env=_paper_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        admission_contract_path = _parse_entry_admission_contract_json_path(
            proc.stdout or ""
        )
        if admission_contract_path is not None and admission_contract_path.exists():
            admission_payload = _load_json(admission_contract_path)
            admission_contract = admission_payload.get("contract") or {}
            admission_reasons = ",".join(
                str(code)
                for code in (admission_contract.get("reason_codes") or [])
                if str(code).strip()
            )
            raise RuntimeError(
                "controlled_kpi_entry_admission_contract_failed "
                f"for {run_id} rc={proc.returncode} "
                f"artifact={admission_contract_path} "
                f"reasons={admission_reasons}"
            )
        raise RuntimeError(
            f"controlled_kpi_run failed for {run_id} rc={proc.returncode}"
        )

    report_json = _parse_report_json_path(proc.stdout or "")
    if not report_json.exists():
        raise RuntimeError(
            f"controlled_kpi_run JSON missing for {run_id}: {report_json}"
        )

    report = _load_json(report_json)
    after_report = report.get("after") or {}
    db_path = _resolve_repo_path(after_report.get("db_path") or "")
    out_log = _resolve_repo_path(after_report.get("out_log") or "")
    err_log = _resolve_repo_path(after_report.get("err_log") or "")
    csv_path = report_json.with_suffix(".csv")

    summary_proc = subprocess.run(
        [
            sys.executable,
            str(
                (WORKDIR / "scripts" / "report_entry_gate_decision_summary.py").resolve()
            ),
            "--db-path",
            str(db_path),
            "--hours",
            str(summary_hours),
        ],
        cwd=str(WORKDIR),
        env=_paper_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if summary_proc.returncode != 0:
        raise RuntimeError(
            "report_entry_gate_decision_summary failed "
            f"for {run_id} rc={summary_proc.returncode}"
        )
    summary_json = json.loads(summary_proc.stdout)
    summary_path = PAPER_REPORT_DIR / f"{run_id}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary_json, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "symbols": symbols,
        "proc_returncode": proc.returncode,
        "report_json": str(report_json),
        "db_path": str(db_path),
        "stdout_log": str(out_log),
        "stderr_log": str(err_log),
        "controlled_kpi_csv": str(csv_path),
        "summary_json": str(summary_path),
        "summary": summary_json,
        "report": report,
        "after_report": after_report,
        "artifact_paths": {
            "db_path": str(db_path),
            "controlled_kpi_json": str(report_json),
            "controlled_kpi_csv": str(csv_path),
            "summary_json": str(summary_path),
        },
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _check_run(
    bundle: dict,
    artifact_registry: dict[str, dict[str, str]],
) -> tuple[bool, list[str], dict]:
    errors = []
    summary = bundle["summary"]
    report = bundle["report"]
    after_report = bundle.get("after_report") or {}
    params = report.get("params") or {}
    db_path = _resolve_repo_path(bundle["db_path"])
    report_json_path = _resolve_repo_path(bundle["report_json"])
    csv_path = _resolve_repo_path(bundle["controlled_kpi_csv"])
    summary_path = _resolve_repo_path(bundle["summary_json"])

    variant_only = str(params.get("variant_only") or "").strip()
    variants_run_raw = report.get("variants_run") or []
    variants_run = [str(item).strip() for item in variants_run_raw if str(item).strip()]
    before_report = report.get("before")
    before_artifact_present = False
    if isinstance(before_report, dict):
        before_artifact_present = any(
            bool(before_report.get(key))
            for key in ("db_exists", "db_path", "out_log", "err_log")
        ) or _safe_int(before_report.get("trade_count"), 0) > 0

    after_db_nonzero = db_path.exists() and db_path.stat().st_size > 0
    report_after_only = bool(
        variant_only == "after"
        and str(after_report.get("variant") or "").strip() == "after"
        and (not variants_run or variants_run == ["after"])
        and not before_artifact_present
    )
    after_process_returncode = _safe_int(after_report.get("process_returncode"), -1)
    after_log_error_count = _safe_int(
        ((after_report.get("log_health") or {}).get("error_count")),
        -1,
    )
    use_mock_value = params.get("use_mock")
    use_mock_false = use_mock_value is False
    paper_auto_open_true = bool(params.get("paper_auto_open"))
    natural_entry_candidate_contract = (
        summary.get("natural_entry_candidate_contract")
        if isinstance(summary.get("natural_entry_candidate_contract"), dict)
        else {}
    )
    natural_entry_classification = str(
        natural_entry_candidate_contract.get("classification") or ""
    ).strip()
    strategy_evidence_classification = str(
        natural_entry_candidate_contract.get("strategy_evidence_classification") or ""
    ).strip()
    no_natural_entry_candidate = (
        natural_entry_classification == "NO_NATURAL_ENTRY_CANDIDATE"
    )
    assisted_seed_evidence_only = bool(
        natural_entry_candidate_contract.get("assisted_seed_evidence_only")
    ) or (strategy_evidence_classification == "ASSISTED_SEED_EVIDENCE_ONLY")
    usable_strategy_economics = (
        natural_entry_candidate_contract.get("usable_strategy_economics")
        if natural_entry_candidate_contract
        else True
    )
    paper_validation_classification = (
        "PAPER_VALIDATION_CANDIDATE"
        if paper_auto_open_true
        else "DIAGNOSTIC_NO_OPEN_RUN"
    )
    if assisted_seed_evidence_only:
        paper_validation_classification = "ASSISTED_SEED_EVIDENCE_ONLY"
    elif no_natural_entry_candidate:
        paper_validation_classification = "NO_NATURAL_ENTRY_CANDIDATE"
    live_trace_detected = "LIVE=1" in (
        (bundle.get("stdout", "") or "") + (bundle.get("stderr", "") or "")
    )

    duplicate_path_hits = []
    forbidden_name_hits = []
    for label, path_text in (bundle.get("artifact_paths") or {}).items():
        resolved = _resolve_repo_path(path_text)
        if resolved.name.lower() in FORBIDDEN_SHARED_ARTIFACT_NAMES:
            forbidden_name_hits.append(
                {
                    "label": label,
                    "path": str(resolved),
                }
            )
            errors.append("forbidden_shared_artifact_name")
        artifact_key = _normalize_artifact_key(resolved)
        owner = artifact_registry.get(artifact_key)
        if owner is not None:
            duplicate_path_hits.append(
                {
                    "label": label,
                    "path": str(resolved),
                    "owner_run_id": owner.get("run_id", ""),
                    "owner_label": owner.get("label", ""),
                }
            )
            errors.append("shared_artifact_path")
            continue
        artifact_registry[artifact_key] = {
            "run_id": bundle["run_id"],
            "label": label,
            "path": str(resolved),
        }

    if bundle["proc_returncode"] != 0:
        errors.append("controlled_kpi_subprocess_nonzero")
    if not after_db_nonzero:
        errors.append("after_db_missing_or_empty")
    if not report_json_path.exists():
        errors.append("controlled_kpi_json_missing")
    if not csv_path.exists():
        errors.append("controlled_kpi_csv_missing")
    if not summary_path.exists():
        errors.append("summary_json_missing")
    if summary.get("rows", 0) <= 0:
        errors.append("summary_rows_not_positive")
    if not summary.get("count_alignment", {}).get("count_matches", False):
        errors.append("count_matches_false")
    if not summary.get("ordering", {}).get("all_pairs_in_order", False):
        errors.append("all_pairs_in_order_false")
    if not summary.get("payload_completeness", {}).get("all_complete", False):
        errors.append("payload_completeness_false")
    if live_trace_detected:
        errors.append("live_trace_detected")
    if not report_after_only:
        errors.append("report_not_after_only")
    if after_process_returncode != 0:
        errors.append("after_process_returncode_nonzero")
    if after_log_error_count != 0:
        errors.append("after_log_error_count_nonzero")
    if not use_mock_false:
        errors.append("use_mock_not_false")
    if not paper_auto_open_true:
        errors.append("paper_auto_open_false")
        errors.append("diagnostic_no_open_run")
    evidence_reason_codes = []
    if no_natural_entry_candidate:
        evidence_reason_codes.append("no_natural_entry_candidate")
        if strategy_evidence_classification == "FALLBACK_ECONOMICS_NOT_STRATEGY_EVIDENCE":
            evidence_reason_codes.append("fallback_economics_not_strategy_evidence")
    if assisted_seed_evidence_only:
        evidence_reason_codes.append("assisted_seed_evidence_only")
        if usable_strategy_economics is False:
            evidence_reason_codes.append("assisted_economics_not_strategy_evidence")

    bootstrap_runtime_contract = _resolve_alpha_bootstrap_runtime_contract(report)
    bootstrap_runtime_status = str(
        bootstrap_runtime_contract.get("status") or ""
    ).strip().upper()
    bootstrap_runtime_valid = bootstrap_runtime_status in {"PASS", "FAIL_CLOSED"}
    if not bootstrap_runtime_valid:
        errors.append("alpha_bootstrap_runtime_contract_invalid")

    forced_cycle_trigger_contract = _resolve_forced_cycle_trigger_contract(
        after_report
    )
    forced_cycle_trigger_status = str(
        forced_cycle_trigger_contract.get("status") or ""
    ).strip().upper()
    forced_cycle_trigger_valid = forced_cycle_trigger_status in {"OK", "INACTIVE"}
    if not forced_cycle_trigger_valid:
        errors.append("post_promotion_forced_cycle_trigger_contract_invalid")

    checks = {
        "rows": summary.get("rows", 0),
        "count_matches": summary.get("count_alignment", {}).get("count_matches", False),
        "all_pairs_in_order": summary.get("ordering", {}).get(
            "all_pairs_in_order", False
        ),
        "all_complete": summary.get("payload_completeness", {}).get(
            "all_complete", False
        ),
        "after_db_nonzero": after_db_nonzero,
        "report_after_only": report_after_only,
        "process_returncode_ok": after_process_returncode == 0,
        "log_errors_zero": after_log_error_count == 0,
        "use_mock_false": use_mock_false,
        "paper_auto_open_true": paper_auto_open_true,
        "paper_validation_classification": paper_validation_classification,
        "diagnostic_no_open_run": not paper_auto_open_true,
        "no_natural_entry_candidate": no_natural_entry_candidate,
        "assisted_seed_evidence_only": assisted_seed_evidence_only,
        "usable_strategy_economics": usable_strategy_economics is not False,
        "strategy_evidence_classification": strategy_evidence_classification,
        "strategy_evidence_valid": len(evidence_reason_codes) == 0,
        "evidence_reason_codes": evidence_reason_codes,
        "natural_entry_candidate_contract": natural_entry_candidate_contract,
        "unique_paths_ok": len(duplicate_path_hits) == 0,
        "forbidden_shared_names_detected": bool(forbidden_name_hits),
        "alpha_bootstrap_runtime_contract_status": bootstrap_runtime_status,
        "alpha_bootstrap_runtime_contract_source": bootstrap_runtime_contract.get(
            "source"
        ),
        "alpha_bootstrap_runtime_contract_reason_codes": list(
            bootstrap_runtime_contract.get("reason_codes") or []
        ),
        "alpha_bootstrap_runtime_contract_valid": bootstrap_runtime_valid,
        "post_promotion_forced_cycle_trigger_contract_status": (
            forced_cycle_trigger_status
        ),
        "post_promotion_forced_cycle_trigger_contract_source": (
            forced_cycle_trigger_contract.get("source")
        ),
        "post_promotion_forced_cycle_trigger_contract_reason_codes": list(
            forced_cycle_trigger_contract.get("reason_codes") or []
        ),
        "post_promotion_forced_cycle_trigger_contract_valid": (
            forced_cycle_trigger_valid
        ),
    }
    if duplicate_path_hits:
        checks["duplicate_path_hits"] = duplicate_path_hits
    if forbidden_name_hits:
        checks["forbidden_name_hits"] = forbidden_name_hits
    return (len(errors) == 0), _dedupe_codes(errors), checks


def _build_artifact_contract(per_run_checks: list[dict]) -> dict:
    expected_run_count = len(RUN_MATRIX)
    duplicate_path_hits = []
    forbidden_name_hits = []
    forced_cycle_trigger_contract_invalid_runs = []
    strategy_evidence_issue_runs = []
    for row in per_run_checks:
        checks = row.get("checks") or {}
        duplicate_path_hits.extend(checks.get("duplicate_path_hits") or [])
        forbidden_name_hits.extend(checks.get("forbidden_name_hits") or [])
        evidence_reason_codes = list(checks.get("evidence_reason_codes") or [])
        if evidence_reason_codes:
            strategy_evidence_issue_runs.append(
                {
                    "run_id": str(row.get("run_id") or ""),
                    "paper_validation_classification": str(
                        checks.get("paper_validation_classification") or ""
                    ),
                    "reason_codes": evidence_reason_codes,
                }
            )
        if checks.get("post_promotion_forced_cycle_trigger_contract_valid") is False:
            forced_cycle_trigger_contract_invalid_runs.append(
                {
                    "run_id": str(row.get("run_id") or ""),
                    "status": str(
                        checks.get("post_promotion_forced_cycle_trigger_contract_status")
                        or ""
                    ),
                    "reason_codes": list(
                        checks.get("post_promotion_forced_cycle_trigger_contract_reason_codes")
                        or []
                    ),
                }
            )

    run_matrix_complete = len(per_run_checks) == expected_run_count
    unique_paths_ok = len(duplicate_path_hits) == 0
    forbidden_shared_names_detected = len(forbidden_name_hits) > 0
    all_after_dbs_nonzero = run_matrix_complete and all(
        bool((row.get("checks") or {}).get("after_db_nonzero"))
        for row in per_run_checks
    )
    all_reports_after_only = run_matrix_complete and all(
        bool((row.get("checks") or {}).get("report_after_only"))
        for row in per_run_checks
    )
    all_forced_cycle_trigger_contracts_valid = run_matrix_complete and all(
        bool(
            (row.get("checks") or {}).get(
                "post_promotion_forced_cycle_trigger_contract_valid",
                True,
            )
        )
        for row in per_run_checks
    )

    reason_codes = []
    if not run_matrix_complete:
        reason_codes.append("RUN_MATRIX_INCOMPLETE")
    if not unique_paths_ok:
        reason_codes.append("ARTIFACT_PATHS_NOT_UNIQUE")
    if forbidden_shared_names_detected:
        reason_codes.append("FORBIDDEN_SHARED_ARTIFACT_NAME_DETECTED")
    if not all_after_dbs_nonzero:
        reason_codes.append("AFTER_DB_MISSING_OR_EMPTY")
    if not all_reports_after_only:
        reason_codes.append("REPORTS_NOT_AFTER_ONLY")
    if not all_forced_cycle_trigger_contracts_valid:
        reason_codes.append("POST_PROMOTION_FORCED_CYCLE_TRIGGER_CONTRACT_INVALID")

    return {
        "unique_paths_ok": bool(unique_paths_ok),
        "forbidden_shared_names_detected": bool(forbidden_shared_names_detected),
        "all_after_dbs_nonzero": bool(all_after_dbs_nonzero),
        "all_reports_after_only": bool(all_reports_after_only),
        "all_forced_cycle_trigger_contracts_valid": bool(
            all_forced_cycle_trigger_contracts_valid
        ),
        "reason_codes": _dedupe_codes(reason_codes),
        "duplicate_path_hits": duplicate_path_hits,
        "forbidden_name_hits": forbidden_name_hits,
        "strategy_evidence_issue_runs": strategy_evidence_issue_runs,
        "forced_cycle_trigger_contract_invalid_runs": (
            forced_cycle_trigger_contract_invalid_runs
        ),
    }


def _bootstrap_report_output_matches(report_output_path: Path, db_path: Path) -> bool:
    if report_output_path.resolve() == db_path.resolve():
        return True
    return bool(
        report_output_path.name == db_path.name
        and _path_is_within(report_output_path, TMP_DIR)
        and _path_is_within(db_path, DIAGNOSTICS_DIR)
    )


def _derive_selected_pairs_from_bootstrap_report(report_payload: dict) -> list[str]:
    selected_pairs = []
    seen = set()
    for row in (report_payload.get("pair_stats_top") or []):
        if not isinstance(row, dict) or not bool(row.get("selected")):
            continue
        symbol_name = str(row.get("symbol") or "").strip().upper()
        strategy_name = str(row.get("strategy") or "").strip().upper()
        if not symbol_name or not strategy_name:
            continue
        token = f"{symbol_name}:{strategy_name}"
        if token in seen:
            continue
        seen.add(token)
        selected_pairs.append(token)
    return selected_pairs


def _load_bootstrap_contract_from_scorecard_sources(
    corpus_contract: dict,
) -> dict | None:
    scorecard_path_txt = str(corpus_contract.get("scorecard_path") or "").strip()
    if corpus_contract.get("status") != "PASS" or not scorecard_path_txt:
        return None

    scorecard_path = _resolve_repo_path(scorecard_path_txt)
    if not scorecard_path.exists():
        return None

    try:
        scorecard = _load_json(scorecard_path)
    except Exception as exc:
        logging.warning(
            "run_paper_readiness_gate: bootstrap scorecard source load failed "
            "path=%s error=%s",
            scorecard_path,
            exc,
        )
        return None

    metadata = scorecard.get("metadata") or {}
    scope = metadata.get("scope") or {}
    sources = metadata.get("sources") or {}
    db_path_txt = str(sources.get("alpha_history_db_path") or "").strip()
    report_path_txt = str(sources.get("bootstrap_report_path") or "").strip()
    if not db_path_txt or not report_path_txt:
        return None

    db_path = _resolve_repo_path(db_path_txt)
    report_path = _resolve_repo_path(report_path_txt)
    bundle_dir_path = db_path.parent.resolve()
    contract = {
        "status": "UNCONFIRMED",
        "reason_codes": [],
        "manifest_path": "",
        "bundle_dir": str(bundle_dir_path),
        "source_scorecard_path": str(scorecard_path),
        "db_path": str(db_path),
        "report_path": str(report_path),
        "rows_inserted": 0,
        "pairs_selected": 0,
        "selected_pairs": [],
        "positive_side_allowlist": [],
        "accepted_run_count": _safe_int(corpus_contract.get("accepted_run_count"), 0),
        "contract_source": "scorecard_sources",
    }

    reason_codes = []
    if str(scope.get("exchange") or "").strip().lower() != "kucoin":
        reason_codes.append("BOOTSTRAP_SCOPE_EXCHANGE_INVALID")
    if str(scope.get("mode") or "").strip().upper() != "PAPER_ONLY":
        reason_codes.append("BOOTSTRAP_SCOPE_MODE_INVALID")
    if str(scope.get("variant") or "").strip().lower() != "after":
        reason_codes.append("BOOTSTRAP_SCOPE_VARIANT_INVALID")
    if bool(scope.get("live_in_scope")):
        reason_codes.append("BOOTSTRAP_SCOPE_LIVE_INVALID")

    if not bundle_dir_path.exists():
        reason_codes.append("BOOTSTRAP_BUNDLE_DIR_MISSING")
    elif not _path_is_within(bundle_dir_path, DIAGNOSTICS_DIR):
        reason_codes.append("BOOTSTRAP_BUNDLE_DIR_OUTSIDE_DIAGNOSTICS")

    if not db_path.exists():
        reason_codes.append("BOOTSTRAP_DB_MISSING")
    else:
        if db_path.stat().st_size <= 0:
            reason_codes.append("BOOTSTRAP_DB_ZERO_OR_EMPTY")
        if _path_is_within(db_path, TMP_DIR):
            reason_codes.append("BOOTSTRAP_DB_TMP_FORBIDDEN")
        if not _path_is_within(db_path, DIAGNOSTICS_DIR):
            reason_codes.append("BOOTSTRAP_DB_OUTSIDE_DIAGNOSTICS")

    report_payload = {}
    if not report_path.exists():
        reason_codes.append("BOOTSTRAP_REPORT_MISSING")
    else:
        if report_path.stat().st_size <= 0:
            reason_codes.append("BOOTSTRAP_REPORT_ZERO_OR_EMPTY")
        if _path_is_within(report_path, TMP_DIR):
            reason_codes.append("BOOTSTRAP_REPORT_TMP_FORBIDDEN")
        if not _path_is_within(report_path, DIAGNOSTICS_DIR):
            reason_codes.append("BOOTSTRAP_REPORT_OUTSIDE_DIAGNOSTICS")
        try:
            report_payload = _load_json(report_path)
        except Exception as exc:
            logging.warning(
                "run_paper_readiness_gate: bootstrap report load failed "
                "path=%s error=%s",
                report_path,
                exc,
            )
            reason_codes.append("BOOTSTRAP_REPORT_LOAD_FAILED")

    rows_inserted = _safe_int(report_payload.get("rows_inserted"), 0)
    contract["rows_inserted"] = rows_inserted
    if rows_inserted <= 0:
        reason_codes.append("BOOTSTRAP_ROWS_INSERTED_ZERO")

    contract["pairs_selected"] = _safe_int(report_payload.get("pairs_selected"), 0)
    contract["selected_pairs"] = _derive_selected_pairs_from_bootstrap_report(
        report_payload
    )

    report_output_txt = str(report_payload.get("output") or "").strip()
    if report_output_txt and db_path.exists():
        report_output_path = _resolve_repo_path(report_output_txt)
        if not _bootstrap_report_output_matches(report_output_path, db_path):
            reason_codes.append("BOOTSTRAP_REPORT_OUTPUT_MISMATCH")

    contract["reason_codes"] = _dedupe_codes(reason_codes)
    contract["status"] = "PASS" if not contract["reason_codes"] else "UNCONFIRMED"
    return contract


def _load_bootstrap_contract_from_manifest(corpus_contract: dict) -> dict:
    manifest_path = ANALYSIS_DIR / STRICT_BOOTSTRAP_MANIFEST_NAME
    contract = {
        "status": "UNCONFIRMED",
        "reason_codes": [],
        "manifest_path": str(manifest_path),
        "bundle_dir": "",
        "source_scorecard_path": "",
        "db_path": "",
        "report_path": "",
        "rows_inserted": 0,
        "pairs_selected": 0,
        "selected_pairs": [],
        "positive_side_allowlist": [],
        "accepted_run_count": 0,
        "contract_source": "strict_bootstrap_manifest",
    }
    reason_codes = []
    if not manifest_path.exists():
        contract["reason_codes"] = ["BOOTSTRAP_MANIFEST_MISSING"]
        return contract

    try:
        payload = _load_json(manifest_path)
    except Exception as exc:
        logging.warning(
            "run_paper_readiness_gate: bootstrap manifest load failed path=%s error=%s",
            manifest_path,
            exc,
        )
        contract["reason_codes"] = ["BOOTSTRAP_MANIFEST_LOAD_FAILED"]
        return contract

    metadata = payload.get("metadata") or {}
    scope = metadata.get("scope") or {}
    if str(scope.get("exchange") or "").strip().lower() != "kucoin":
        reason_codes.append("BOOTSTRAP_SCOPE_EXCHANGE_INVALID")
    if str(scope.get("mode") or "").strip().upper() != "PAPER_ONLY":
        reason_codes.append("BOOTSTRAP_SCOPE_MODE_INVALID")
    if str(scope.get("variant") or "").strip().lower() != "after":
        reason_codes.append("BOOTSTRAP_SCOPE_VARIANT_INVALID")
    if bool(scope.get("live_in_scope")):
        reason_codes.append("BOOTSTRAP_SCOPE_LIVE_INVALID")

    bundle_dir_txt = str(metadata.get("bundle_dir") or "").strip()
    if bundle_dir_txt:
        bundle_dir_path = _resolve_repo_path(bundle_dir_txt)
        contract["bundle_dir"] = str(bundle_dir_path)
        if not bundle_dir_path.exists():
            reason_codes.append("BOOTSTRAP_BUNDLE_DIR_MISSING")
        elif not _path_is_within(bundle_dir_path, DIAGNOSTICS_DIR):
            reason_codes.append("BOOTSTRAP_BUNDLE_DIR_OUTSIDE_DIAGNOSTICS")
    else:
        reason_codes.append("BOOTSTRAP_BUNDLE_DIR_MISSING")

    selection = payload.get("selection") or {}
    manifest_run_ids = [
        str(run_id).strip()
        for run_id in (selection.get("accepted_run_ids") or [])
        if str(run_id).strip()
    ]
    contract["accepted_run_count"] = len(manifest_run_ids)
    corpus_run_ids = [
        str(run_id).strip()
        for run_id in (corpus_contract.get("accepted_run_ids") or [])
        if str(run_id).strip()
    ]
    if corpus_run_ids and manifest_run_ids != corpus_run_ids:
        reason_codes.append("BOOTSTRAP_ACCEPTED_RUN_IDS_MISMATCH")

    source = payload.get("prebuilt_source") or {}
    source_scorecard_txt = str(source.get("source_scorecard_path") or "").strip()
    source_scorecard_path = None
    if source_scorecard_txt:
        source_scorecard_path = _resolve_repo_path(source_scorecard_txt)
        contract["source_scorecard_path"] = str(source_scorecard_path)
        if not source_scorecard_path.exists():
            reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_MISSING")
    else:
        reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_PATH_MISSING")

    db_path_txt = str(source.get("db_path") or "").strip()
    report_path_txt = str(source.get("report_path") or "").strip()
    db_path = None
    report_path = None
    if not db_path_txt:
        reason_codes.append("BOOTSTRAP_DB_PATH_MISSING")
    else:
        db_path = _resolve_repo_path(db_path_txt)
        contract["db_path"] = str(db_path)
        if not db_path.exists():
            reason_codes.append("BOOTSTRAP_DB_MISSING")
        else:
            if db_path.stat().st_size <= 0:
                reason_codes.append("BOOTSTRAP_DB_ZERO_OR_EMPTY")
            if _path_is_within(db_path, TMP_DIR):
                reason_codes.append("BOOTSTRAP_DB_TMP_FORBIDDEN")
            if not _path_is_within(db_path, DIAGNOSTICS_DIR):
                reason_codes.append("BOOTSTRAP_DB_OUTSIDE_DIAGNOSTICS")
            expected_db_sha = str(source.get("db_sha256") or "").strip().upper()
            if expected_db_sha:
                actual_db_sha = _sha256_file(db_path)
                if actual_db_sha != expected_db_sha:
                    reason_codes.append("BOOTSTRAP_DB_SHA_MISMATCH")
            expected_db_size = _safe_int(source.get("db_size_bytes"), 0)
            if expected_db_size > 0 and db_path.stat().st_size != expected_db_size:
                reason_codes.append("BOOTSTRAP_DB_SIZE_MISMATCH")

    if not report_path_txt:
        reason_codes.append("BOOTSTRAP_REPORT_PATH_MISSING")
    else:
        report_path = _resolve_repo_path(report_path_txt)
        contract["report_path"] = str(report_path)
        if not report_path.exists():
            reason_codes.append("BOOTSTRAP_REPORT_MISSING")
        else:
            if report_path.stat().st_size <= 0:
                reason_codes.append("BOOTSTRAP_REPORT_ZERO_OR_EMPTY")
            if _path_is_within(report_path, TMP_DIR):
                reason_codes.append("BOOTSTRAP_REPORT_TMP_FORBIDDEN")
            if not _path_is_within(report_path, DIAGNOSTICS_DIR):
                reason_codes.append("BOOTSTRAP_REPORT_OUTSIDE_DIAGNOSTICS")
            expected_report_sha = str(source.get("report_sha256") or "").strip().upper()
            if expected_report_sha:
                actual_report_sha = _sha256_file(report_path)
                if actual_report_sha != expected_report_sha:
                    reason_codes.append("BOOTSTRAP_REPORT_SHA_MISMATCH")
            expected_report_size = _safe_int(source.get("report_size_bytes"), 0)
            if (
                expected_report_size > 0
                and report_path.stat().st_size != expected_report_size
            ):
                reason_codes.append("BOOTSTRAP_REPORT_SIZE_MISMATCH")

    report_payload = {}
    if report_path is not None and report_path.exists():
        try:
            report_payload = _load_json(report_path)
        except Exception as exc:
            logging.warning(
                "run_paper_readiness_gate: bootstrap report load failed path=%s error=%s",
                report_path,
                exc,
            )
            reason_codes.append("BOOTSTRAP_REPORT_LOAD_FAILED")

    rows_inserted = _safe_int(report_payload.get("rows_inserted"), 0)
    contract["rows_inserted"] = rows_inserted
    if rows_inserted <= 0:
        reason_codes.append("BOOTSTRAP_ROWS_INSERTED_ZERO")
    expected_rows_inserted = _safe_int(source.get("rows_inserted"), 0)
    if expected_rows_inserted > 0 and rows_inserted != expected_rows_inserted:
        reason_codes.append("BOOTSTRAP_ROWS_INSERTED_MISMATCH")

    pairs_selected = _safe_int(report_payload.get("pairs_selected"), 0)
    contract["pairs_selected"] = pairs_selected
    expected_pairs_selected = _safe_int(source.get("pairs_selected"), 0)
    if expected_pairs_selected > 0 and pairs_selected != expected_pairs_selected:
        reason_codes.append("BOOTSTRAP_PAIRS_SELECTED_MISMATCH")

    contract["selected_pairs"] = [
        str(item).strip()
        for item in (source.get("selected_pairs") or [])
        if str(item).strip()
    ]
    contract["positive_side_allowlist"] = [
        str(item).strip()
        for item in (source.get("positive_side_allowlist") or [])
        if str(item).strip()
    ]

    report_output_txt = str(report_payload.get("output") or "").strip()
    if db_path is not None and report_output_txt:
        report_output_path = _resolve_repo_path(report_output_txt)
        if not _bootstrap_report_output_matches(report_output_path, db_path):
            reason_codes.append("BOOTSTRAP_REPORT_OUTPUT_MISMATCH")

    if source_scorecard_path is not None and source_scorecard_path.exists():
        try:
            source_scorecard = _load_json(source_scorecard_path)
        except Exception as exc:
            logging.warning(
                "run_paper_readiness_gate: bootstrap source scorecard load failed path=%s error=%s",
                source_scorecard_path,
                exc,
            )
            source_scorecard = {}
            reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_LOAD_FAILED")
        scorecard_sources = (
            ((source_scorecard.get("metadata") or {}).get("sources") or {})
        )
        scorecard_db_txt = str(scorecard_sources.get("alpha_history_db_path") or "").strip()
        scorecard_report_txt = str(
            scorecard_sources.get("bootstrap_report_path") or ""
        ).strip()
        if db_path is not None and scorecard_db_txt:
            if _resolve_repo_path(scorecard_db_txt) != db_path:
                reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_DB_MISMATCH")
        else:
            reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_DB_PATH_MISSING")
        if report_path is not None and scorecard_report_txt:
            if _resolve_repo_path(scorecard_report_txt) != report_path:
                reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_REPORT_MISMATCH")
        else:
            reason_codes.append("BOOTSTRAP_SOURCE_SCORECARD_REPORT_PATH_MISSING")

    contract["reason_codes"] = _dedupe_codes(reason_codes)
    contract["status"] = "PASS" if not contract["reason_codes"] else "UNCONFIRMED"
    return contract


def _load_bootstrap_contract(corpus_contract: dict) -> dict:
    scorecard_contract = _load_bootstrap_contract_from_scorecard_sources(
        corpus_contract
    )
    manifest_contract = _load_bootstrap_contract_from_manifest(corpus_contract)
    if scorecard_contract is not None and scorecard_contract.get("status") == "PASS":
        return scorecard_contract
    if manifest_contract.get("status") == "PASS":
        return manifest_contract
    if scorecard_contract is not None:
        return scorecard_contract
    return manifest_contract


def _accepted_artifacts_from_manifest(
    manifest_path_text: str,
    accepted_run_ids: list[str],
    expected_scorecard_path: Path | None = None,
) -> tuple[list[Path], list[str], list[str], list[str], dict]:
    manifest_path = _resolve_repo_path(manifest_path_text)
    details = {
        "accepted_manifest_path": str(manifest_path),
        "accepted_artifact_source": "accepted_manifest",
        "accepted_corpus_bundle_dir": "",
        "accepted_manifest_hash_mismatch_count": 0,
        "accepted_manifest_source_scorecard_path": "",
    }
    if not manifest_path.exists():
        return [], ["ACCEPTED_MANIFEST_MISSING"], [], [], details
    try:
        manifest = _load_json(manifest_path)
    except Exception as exc:
        logging.warning(
            "run_paper_readiness_gate: accepted manifest load failed path=%s error=%s",
            manifest_path,
            exc,
        )
        return [], ["ACCEPTED_MANIFEST_LOAD_FAILED"], [], [], details

    bundle_dir_txt = str(manifest.get("bundle_dir") or "").strip()
    if bundle_dir_txt:
        details["accepted_corpus_bundle_dir"] = str(_resolve_repo_path(bundle_dir_txt))

    reason_codes = []
    if str(manifest.get("report_type") or "").strip() != "zol0_accepted_corpus_manifest":
        reason_codes.append("ACCEPTED_MANIFEST_REPORT_TYPE_INVALID")
    scope = manifest.get("scope") or {}
    if str(scope.get("exchange") or "").strip().lower() != "kucoin":
        reason_codes.append("ACCEPTED_MANIFEST_SCOPE_EXCHANGE_INVALID")
    if str(scope.get("mode") or "").strip().upper() != "PAPER_ONLY":
        reason_codes.append("ACCEPTED_MANIFEST_SCOPE_MODE_INVALID")
    if str(scope.get("variant") or "").strip().lower() != "after":
        reason_codes.append("ACCEPTED_MANIFEST_SCOPE_VARIANT_INVALID")
    if not _scope_bool_false(scope.get("live_in_scope")):
        reason_codes.append("ACCEPTED_MANIFEST_SCOPE_LIVE_INVALID")
    source_scorecard_txt = str(manifest.get("source_scorecard_path") or "").strip()
    if not source_scorecard_txt:
        reason_codes.append("ACCEPTED_MANIFEST_SOURCE_SCORECARD_MISSING")
    else:
        source_scorecard_path = _resolve_repo_path(source_scorecard_txt)
        details["accepted_manifest_source_scorecard_path"] = str(source_scorecard_path)
        if not _path_is_within(source_scorecard_path, WORKDIR):
            reason_codes.append("ACCEPTED_MANIFEST_SOURCE_SCORECARD_OUTSIDE_WORKDIR")
        if (
            expected_scorecard_path is not None
            and source_scorecard_path.resolve() != expected_scorecard_path.resolve()
        ):
            reason_codes.append("ACCEPTED_MANIFEST_SOURCE_SCORECARD_MISMATCH")

    selection = manifest.get("selection") or {}
    manifest_run_ids = [
        str(run_id).strip()
        for run_id in (selection.get("accepted_run_ids") or [])
        if str(run_id).strip()
    ]
    if manifest_run_ids != accepted_run_ids:
        reason_codes.append("ACCEPTED_MANIFEST_RUN_IDS_MISMATCH")

    validation = manifest.get("bundle_validation") or {}
    required_validation_checks = (
        "accepted_run_count_matches_scorecard",
        "all_source_artifacts_present",
        "all_source_artifacts_nonzero",
        "all_bundled_hashes_match_source",
        "all_bundled_result_after_only",
        "all_bundled_result_use_mock_false",
        "all_bundled_result_process_ok",
    )
    if any(validation.get(key) is not True for key in required_validation_checks):
        reason_codes.append("ACCEPTED_MANIFEST_VALIDATION_FAILED")

    accepted_run_id_set = set(accepted_run_ids)
    entries = [entry for entry in (manifest.get("entries") or []) if isinstance(entry, dict)]
    if len(entries) != len(accepted_run_ids):
        reason_codes.append("ACCEPTED_MANIFEST_ENTRY_COUNT_MISMATCH")

    artifact_paths: list[Path] = []
    missing_artifacts: list[str] = []
    zero_artifacts: list[str] = []
    hash_mismatch_count = 0
    for entry in entries:
        run_id = str(entry.get("run_id") or "").strip()
        if run_id not in accepted_run_id_set:
            reason_codes.append("ACCEPTED_MANIFEST_ENTRY_RUN_ID_UNKNOWN")
            continue
        bundled = entry.get("bundled_artifacts") or {}
        for artifact_key in ("result_json", "csv", "db"):
            descriptor = bundled.get(artifact_key) or {}
            path_text = str(descriptor.get("path") or "").strip()
            if not path_text:
                reason_codes.append("ACCEPTED_MANIFEST_ARTIFACT_PATH_MISSING")
                continue
            path = _resolve_repo_path(path_text)
            artifact_paths.append(path)
            if not path.exists():
                missing_artifacts.append(str(path))
                continue
            if path.stat().st_size <= 0:
                zero_artifacts.append(str(path))
            expected_size = _safe_int(descriptor.get("size_bytes"), 0)
            if expected_size > 0 and path.stat().st_size != expected_size:
                reason_codes.append("ACCEPTED_MANIFEST_ARTIFACT_SIZE_MISMATCH")
            expected_sha = str(descriptor.get("sha256") or "").strip().upper()
            if expected_sha:
                actual_sha = _sha256_file(path)
                if actual_sha != expected_sha:
                    hash_mismatch_count += 1
                    reason_codes.append("ACCEPTED_MANIFEST_ARTIFACT_SHA_MISMATCH")

    details["accepted_manifest_hash_mismatch_count"] = hash_mismatch_count
    return (
        artifact_paths,
        _dedupe_codes(reason_codes),
        missing_artifacts,
        zero_artifacts,
        details,
    )


def _load_corpus_contract() -> dict:
    scorecard_path = _select_corpus_scorecard_path()
    strict_corpus_status_path = _preferred_or_latest_file(
        directory=ANALYSIS_DIR,
        preferred_names=[
            STRICT_CORPUS_STATUS_CURRENT_NAME,
            "zol0_strict_bucket_gate_fresh_corpus_status_20260409.json",
        ],
        glob_patterns=["zol0_strict_bucket_gate_fresh_corpus_status*.json"],
    )

    reason_codes = []
    scorecard = None
    strict_status = None
    strict_status_reason_codes = []
    accepted_run_ids = []
    accepted_artifacts_present = False
    accepted_artifacts_nonzero = False
    missing_artifacts = []
    zero_artifacts = []
    required_accepted_runs = None
    strict_accepted_run_count = None
    strict_classification = ""
    accepted_manifest_path = ""
    accepted_artifact_source = "legacy_workspace_paths"
    accepted_corpus_bundle_dir = ""
    accepted_manifest_hash_mismatch_count = 0
    accepted_manifest_source_scorecard_path = ""
    accepted_corpus_total_trade_count = None
    selection_source = ""
    selection_required_limit = 0

    if scorecard_path is None:
        reason_codes.append("SCORECARD_MISSING")
    else:
        try:
            scorecard = _load_json(scorecard_path)
        except Exception as exc:
            logging.warning(
                "run_paper_readiness_gate: scorecard load failed path=%s error=%s",
                scorecard_path,
                exc,
            )
            reason_codes.append("SCORECARD_LOAD_FAILED")

    if strict_corpus_status_path is None:
        strict_status_reason_codes.append("STRICT_FRESH_CORPUS_STATUS_MISSING")
    else:
        try:
            strict_status = _load_json(strict_corpus_status_path)
        except Exception as exc:
            logging.warning(
                "run_paper_readiness_gate: strict corpus load failed path=%s error=%s",
                strict_corpus_status_path,
                exc,
            )
            strict_status_reason_codes.append("STRICT_FRESH_CORPUS_STATUS_LOAD_FAILED")

    if isinstance(scorecard, dict):
        global_kpis = scorecard.get("global_kpis") or {}
        if "total_trade_count" in global_kpis:
            accepted_corpus_total_trade_count = _safe_int(
                global_kpis.get("total_trade_count"),
                0,
            )
            if accepted_corpus_total_trade_count <= 0:
                reason_codes.append("ACCEPTED_CORPUS_ZERO_TRADES")
        selection = ((scorecard.get("metadata") or {}).get("selection") or {})
        selection_source = str(selection.get("selection_source") or "").strip()
        selection_required_limit = _safe_int(selection.get("required_limit"), 0)
        accepted_run_ids_raw = selection.get("accepted_run_ids") or []
        accepted_run_ids = [
            str(run_id).strip()
            for run_id in accepted_run_ids_raw
            if str(run_id).strip()
        ]
        if not accepted_run_ids:
            reason_codes.append("SCORECARD_ACCEPTED_RUN_IDS_MISSING")
        else:
            sources = ((scorecard.get("metadata") or {}).get("sources") or {})
            accepted_manifest_path = str(
                sources.get("accepted_corpus_manifest_path")
                or selection.get("accepted_manifest_path")
                or ""
            ).strip()
            accepted_artifacts = []
            if accepted_manifest_path:
                (
                    accepted_artifacts,
                    manifest_reason_codes,
                    missing_artifacts,
                    zero_artifacts,
                    manifest_details,
                ) = _accepted_artifacts_from_manifest(
                    accepted_manifest_path,
                    accepted_run_ids,
                    scorecard_path,
                )
                reason_codes.extend(manifest_reason_codes)
                accepted_manifest_path = str(
                    manifest_details.get("accepted_manifest_path")
                    or accepted_manifest_path
                )
                accepted_artifact_source = str(
                    manifest_details.get("accepted_artifact_source")
                    or "accepted_manifest"
                )
                accepted_corpus_bundle_dir = str(
                    manifest_details.get("accepted_corpus_bundle_dir") or ""
                )
                accepted_manifest_source_scorecard_path = str(
                    manifest_details.get("accepted_manifest_source_scorecard_path")
                    or ""
                )
                accepted_manifest_hash_mismatch_count = _safe_int(
                    manifest_details.get("accepted_manifest_hash_mismatch_count"),
                    0,
                )
            else:
                for run_id in accepted_run_ids:
                    accepted_artifacts.extend(
                        [
                            TMP_DIR / f"controlled_kpi_after_{run_id}.db",
                            RESULTS_DIR / f"controlled_kpi_{run_id}.json",
                            RESULTS_DIR / f"controlled_kpi_{run_id}.csv",
                        ]
                    )
            missing_artifacts = [
                str(path)
                for path in accepted_artifacts
                if not path.exists()
            ]
            zero_artifacts = [
                str(path)
                for path in accepted_artifacts
                if path.exists() and path.stat().st_size <= 0
            ]
            accepted_artifacts_present = len(missing_artifacts) == 0
            accepted_artifacts_nonzero = (
                accepted_artifacts_present and len(zero_artifacts) == 0
            )
            if not accepted_artifacts_present:
                reason_codes.append("ACCEPTED_ARTIFACTS_MISSING")
            if not accepted_artifacts_nonzero:
                reason_codes.append("ACCEPTED_ARTIFACTS_ZERO_OR_EMPTY")

    accepted_manifest_replay_mode = bool(
        selection_source == "accepted_manifest"
        and accepted_manifest_path
        and accepted_artifacts_present
        and accepted_artifacts_nonzero
    )

    if accepted_manifest_replay_mode:
        required_accepted_runs = max(selection_required_limit, len(accepted_run_ids), 1)
        strict_accepted_run_count = len(accepted_run_ids)
        strict_classification = "ACCEPTED_MANIFEST_REPLAY"
        if strict_accepted_run_count < required_accepted_runs:
            reason_codes.append("STRICT_FRESH_CORPUS_INSUFFICIENT")
    elif isinstance(strict_status, dict):
        strict_inventory = strict_status.get("strict_gate_inventory") or {}
        strict_accepted_run_count = _safe_int(
            strict_inventory.get("accepted_run_count"),
            0,
        )
        required_accepted_runs = _safe_int(
            ((strict_status.get("collection_standard") or {}).get("required_accepted_runs")),
            0,
        )
        strict_classification = str(strict_status.get("classification") or "").strip()
        strict_pass = bool(
            (strict_status.get("pass_fail_criteria") or {}).get(
                "accepted_20_of_20_after_runs",
                False,
            )
        )
        if not strict_pass or strict_accepted_run_count < max(required_accepted_runs, 1):
            reason_codes.append("STRICT_FRESH_CORPUS_INSUFFICIENT")
    else:
        reason_codes.extend(strict_status_reason_codes)

    status = "PASS" if not reason_codes else "UNCONFIRMED"
    return {
        "status": status,
        "reason_codes": _dedupe_codes(reason_codes),
        "scorecard_path": str(scorecard_path) if scorecard_path else "",
        "strict_corpus_status_path": (
            str(strict_corpus_status_path) if strict_corpus_status_path else ""
        ),
        "accepted_artifacts_present": bool(accepted_artifacts_present),
        "accepted_artifacts_nonzero": bool(accepted_artifacts_nonzero),
        "accepted_artifact_source": accepted_artifact_source,
        "accepted_manifest_path": accepted_manifest_path,
        "accepted_corpus_bundle_dir": accepted_corpus_bundle_dir,
        "accepted_manifest_source_scorecard_path": (
            accepted_manifest_source_scorecard_path
        ),
        "accepted_manifest_hash_mismatch_count": accepted_manifest_hash_mismatch_count,
        "accepted_run_ids": accepted_run_ids,
        "accepted_run_count": len(accepted_run_ids),
        "accepted_corpus_total_trade_count": accepted_corpus_total_trade_count,
        "required_accepted_runs": required_accepted_runs,
        "strict_accepted_run_count": strict_accepted_run_count,
        "strict_classification": strict_classification,
        "missing_artifact_count": len(missing_artifacts),
        "zero_artifact_count": len(zero_artifacts),
        "missing_artifact_samples": missing_artifacts[:5],
        "zero_artifact_samples": zero_artifacts[:5],
    }


def _load_economics_context(corpus_contract: dict) -> dict:
    scorecard_path_text = str(corpus_contract.get("scorecard_path") or "").strip()
    if corpus_contract.get("status") != "PASS" or not scorecard_path_text:
        return {
            "status": "UNCONFIRMED",
            "go_no_go": "UNCONFIRMED",
            "reason_codes": _dedupe_codes(
                ["EXACT_CORPUS_EVIDENCE_UNCONFIRMED"]
                + list(corpus_contract.get("reason_codes") or [])
            ),
            "scorecard_path": scorecard_path_text,
        }

    scorecard_path = _resolve_repo_path(scorecard_path_text)
    try:
        scorecard = _load_json(scorecard_path)
    except Exception as exc:
        logging.warning(
            "run_paper_readiness_gate: economics scorecard load failed path=%s error=%s",
            scorecard_path,
            exc,
        )
        return {
            "status": "UNCONFIRMED",
            "go_no_go": "UNCONFIRMED",
            "reason_codes": [
                "EXACT_CORPUS_EVIDENCE_UNCONFIRMED",
                "SCORECARD_LOAD_FAILED",
            ],
            "scorecard_path": str(scorecard_path),
        }

    global_kpis = scorecard.get("global_kpis") or {}
    avg_profit_factor = _safe_float(global_kpis.get("avg_profit_factor"), None)
    avg_net_pnl = _safe_float(global_kpis.get("avg_net_pnl"), None)
    profitable_run_rate = _safe_float(global_kpis.get("profitable_run_rate"), None)
    pf_gt_1_rate = _safe_float(global_kpis.get("pf_gt_1_rate"), None)

    if avg_profit_factor is None or avg_net_pnl is None:
        return {
            "status": "UNCONFIRMED",
            "go_no_go": "UNCONFIRMED",
            "reason_codes": [
                "EXACT_CORPUS_EVIDENCE_UNCONFIRMED",
                "SCORECARD_GLOBAL_KPIS_INCOMPLETE",
            ],
            "scorecard_path": str(scorecard_path),
        }

    go_no_go = "GO" if avg_profit_factor >= 1.0 and avg_net_pnl >= 0.0 else "NO-GO"
    reason_codes = ["EXACT_CORPUS_EVIDENCE_AVAILABLE"]
    if go_no_go == "GO":
        reason_codes.append("SCORECARD_GO")
    else:
        reason_codes.append("SCORECARD_NO_GO")
        if avg_profit_factor < 1.0:
            reason_codes.append("AVG_PROFIT_FACTOR_BELOW_ONE")
        if avg_net_pnl < 0.0:
            reason_codes.append("AVG_NET_PNL_NEGATIVE")
        if profitable_run_rate is not None and profitable_run_rate <= 0.0:
            reason_codes.append("PROFITABLE_RUN_RATE_ZERO")
        if pf_gt_1_rate is not None and pf_gt_1_rate <= 0.0:
            reason_codes.append("PF_GT_1_RATE_ZERO")

    return {
        "status": "AVAILABLE",
        "go_no_go": go_no_go,
        "reason_codes": _dedupe_codes(reason_codes),
        "scorecard_path": str(scorecard_path),
        "avg_profit_factor": avg_profit_factor,
        "avg_net_pnl": avg_net_pnl,
        "profitable_run_rate": profitable_run_rate,
        "pf_gt_1_rate": pf_gt_1_rate,
        "accepted_run_count": corpus_contract.get("accepted_run_count"),
        "required_accepted_runs": corpus_contract.get("required_accepted_runs"),
    }


def _normalized_go_no_go(economics_context: dict) -> str:
    raw = str(economics_context.get("go_no_go") or "").strip().upper()
    if raw in {"GO", "NO-GO"}:
        return raw
    return "UNCONFIRMED"


def _derive_economic_channel(economics_context: dict) -> dict:
    go_no_go = _normalized_go_no_go(economics_context)
    context_reasons = list(economics_context.get("reason_codes") or [])
    if go_no_go == "GO":
        status = "PASS"
        reason_codes = _dedupe_codes(["ECONOMICS_GO"] + context_reasons)
    elif go_no_go == "NO-GO":
        status = "FAIL"
        reason_codes = _dedupe_codes(["ECONOMICS_NO_GO"] + context_reasons)
    else:
        status = "UNCONFIRMED"
        reason_codes = _dedupe_codes(["ECONOMICS_UNCONFIRMED"] + context_reasons)
    return {
        "status": status,
        "go_no_go": go_no_go,
        "reason_codes": reason_codes,
    }


def _derive_global_decision(
    operational_gate_status: str,
    economic_status: str,
    operational_reason_codes: list[str],
    economic_reason_codes: list[str],
) -> tuple[bool, str, str, list[str]]:
    if operational_gate_status == "PASS" and economic_status == "PASS":
        return (
            True,
            "PROMOTE_CANDIDATE",
            "proceed to guarded promotion rollout",
            ["OPERATIONAL_PASS", "ECONOMIC_PASS"],
        )
    if operational_gate_status != "PASS":
        return (
            False,
            "DO_NOT_PROMOTE",
            "fix operational gate failures and rerun readiness gate",
            _dedupe_codes(["OPERATIONAL_GATE_FAIL"] + list(operational_reason_codes)),
        )
    if economic_status == "FAIL":
        return (
            False,
            "DO_NOT_PROMOTE",
            "continue research / profitability hypothesis validation only",
            _dedupe_codes(["ECONOMICS_NO_GO"] + list(economic_reason_codes)),
        )
    return (
        False,
        "DO_NOT_PROMOTE",
        "collect exact corpus evidence and rerun readiness gate",
        _dedupe_codes(["ECONOMICS_UNCONFIRMED"] + list(economic_reason_codes)),
    )


def run_gate() -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    runs = []
    per_run_checks = []
    errors = []
    artifact_registry = {}
    for item in RUN_MATRIX:
        try:
            bundle = _run_controlled_kpi(
                item["symbols"],
                item["run_id"],
                int(item.get("summary_hours", 1)),
                after_env_overrides=_resolve_run_after_env_overrides(item),
            )
            ok, run_errors, checks = _check_run(bundle, artifact_registry)
            per_run_checks.append(
                {
                    "run_id": bundle["run_id"],
                    "ok": ok,
                    "errors": run_errors,
                    "checks": checks,
                }
            )
            runs.append(
                {
                    "run_id": bundle["run_id"],
                    "symbols": bundle["symbols"],
                    "db_path": bundle["db_path"],
                    "stdout_log": bundle["stdout_log"],
                    "stderr_log": bundle["stderr_log"],
                    "controlled_kpi_json": bundle["report_json"],
                    "controlled_kpi_csv": bundle["controlled_kpi_csv"],
                    "summary_json": bundle["summary_json"],
                    "alpha_bootstrap_runtime_contract_status": checks.get(
                        "alpha_bootstrap_runtime_contract_status"
                    ),
                    "alpha_bootstrap_runtime_contract_source": checks.get(
                        "alpha_bootstrap_runtime_contract_source"
                    ),
                }
            )
            if not ok:
                errors.extend(run_errors)
                continue
        except Exception as exc:
            reason_code = _classify_run_exception(exc)
            admission_contract_path = _parse_entry_admission_contract_json_path(
                str(exc)
            )
            admission_contract = {}
            if (
                admission_contract_path is not None
                and admission_contract_path.exists()
            ):
                try:
                    admission_payload = _load_json(admission_contract_path)
                    admission_contract = admission_payload.get("contract") or {}
                except Exception:
                    admission_contract = {}
            errors.append(reason_code)
            per_run_checks.append(
                {
                    "run_id": item["run_id"],
                    "ok": False,
                    "errors": [reason_code],
                    "checks": {
                        "rows": 0,
                        "count_matches": False,
                        "all_pairs_in_order": False,
                        "all_complete": False,
                        "after_db_nonzero": False,
                        "report_after_only": False,
                        "process_returncode_ok": False,
                        "log_errors_zero": False,
                        "use_mock_false": False,
                        "paper_auto_open_true": False,
                        "unique_paths_ok": False,
                        "forbidden_shared_names_detected": False,
                    },
                    "exception_reason_code": reason_code,
                    "exception": f"{type(exc).__name__}: {exc}",
                    "entry_admission_contract_json": (
                        str(admission_contract_path)
                        if admission_contract_path is not None
                        else ""
                    ),
                    "entry_admission_contract": admission_contract,
                }
            )
            run_error = {
                "run_id": item["run_id"],
                "symbols": item["symbols"],
                "error": f"{type(exc).__name__}: {exc}",
            }
            if admission_contract_path is not None:
                run_error["entry_admission_contract_json"] = str(
                    admission_contract_path
                )
                run_error["entry_admission_contract"] = admission_contract
            runs.append(run_error)
            continue

    artifact_contract = _build_artifact_contract(per_run_checks)
    operational_reason_codes = _dedupe_codes(
        list(errors) + list(artifact_contract.get("reason_codes") or [])
    )
    operational_gate_status = (
        "PASS"
        if not operational_reason_codes and len(per_run_checks) == len(RUN_MATRIX)
        else "FAIL"
    )
    paper_operational_confidence = (
        "PARTIAL-CONFIDENCE" if operational_gate_status == "PASS" else "UNCONFIRMED"
    )
    corpus_contract = _load_corpus_contract()
    bootstrap_contract = _load_bootstrap_contract(corpus_contract)
    economics_context = _load_economics_context(corpus_contract)
    economic_channel = _derive_economic_channel(economics_context)
    paper_ready, global_verdict, next_allowed_step, global_reason_codes = (
        _derive_global_decision(
            operational_gate_status=operational_gate_status,
            economic_status=str(economic_channel.get("status") or "UNCONFIRMED"),
            operational_reason_codes=operational_reason_codes,
            economic_reason_codes=list(economic_channel.get("reason_codes") or []),
        )
    )
    aggregate_checks = {
        "runs_passed": sum(1 for r in per_run_checks if r["ok"]),
        "runs_total": len(RUN_MATRIX),
        "all_runs_passed": (
            len(per_run_checks) == len(RUN_MATRIX) and all(r["ok"] for r in per_run_checks)
        ),
        "paper_operational_confidence": paper_operational_confidence,
        "economics_status": economic_channel.get("status"),
        "economics_go_no_go": economic_channel.get("go_no_go"),
        "bootstrap_status": bootstrap_contract.get("status"),
    }
    report = {
        "timestamp": timestamp,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "evidence_scope": {
            "exchange": "kucoin",
            "mode": "paper",
            "variant": "after",
            "market_data": "real",
        },
        "artifact_contract": artifact_contract,
        "corpus_contract": corpus_contract,
        "bootstrap_contract": bootstrap_contract,
        "operational_gate_status": operational_gate_status,
        "paper_operational_confidence": paper_operational_confidence,
        "paper_ready": paper_ready,
        "operational_channel": {
            "status": operational_gate_status,
            "confidence": paper_operational_confidence,
            "reason_codes": (
                ["OPERATIONAL_GATE_PASS"]
                if operational_gate_status == "PASS"
                else _dedupe_codes(["OPERATIONAL_GATE_FAIL"] + operational_reason_codes)
            ),
        },
        "economic_channel": economic_channel,
        "runs": runs,
        "artifacts": {
            "controlled_kpi_run_script": str(
                (WORKDIR / "scripts" / "controlled_kpi_run.py").resolve()
            ),
            "summary_script": str(
                (WORKDIR / "scripts" / "report_entry_gate_decision_summary.py").resolve()
            ),
        },
        "per_run_checks": per_run_checks,
        "aggregate_checks": aggregate_checks,
        "economics_context": economics_context,
        "global_verdict": global_verdict,
        "global_reason_codes": global_reason_codes,
        "next_allowed_step": next_allowed_step,
    }
    out_dir = PAPER_REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"paper_readiness_gate_{timestamp}.json"
    md_path = out_dir / f"paper_readiness_gate_{timestamp}.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    md_lines = [
        "# PAPER Readiness Gate",
        "",
        f"- timestamp: {timestamp}",
        f"- evidence_contract_version: {EVIDENCE_CONTRACT_VERSION}",
        f"- evidence_scope.exchange: {report['evidence_scope']['exchange']}",
        f"- evidence_scope.mode: {report['evidence_scope']['mode']}",
        f"- evidence_scope.variant: {report['evidence_scope']['variant']}",
        f"- evidence_scope.market_data: {report['evidence_scope']['market_data']}",
        f"- operational_gate_status: {operational_gate_status}",
        f"- paper_operational_confidence: {paper_operational_confidence}",
        f"- paper_ready: {paper_ready}",
        f"- global_verdict: {global_verdict}",
        f"- global_reason_codes: {','.join(global_reason_codes)}",
        f"- next_allowed_step: {next_allowed_step}",
        "",
        "## Artifact Contract",
        f"- unique_paths_ok: {artifact_contract['unique_paths_ok']}",
        (
            "- forbidden_shared_names_detected: "
            f"{artifact_contract['forbidden_shared_names_detected']}"
        ),
        f"- all_after_dbs_nonzero: {artifact_contract['all_after_dbs_nonzero']}",
        f"- all_reports_after_only: {artifact_contract['all_reports_after_only']}",
        (
            "- all_forced_cycle_trigger_contracts_valid: "
            f"{artifact_contract['all_forced_cycle_trigger_contracts_valid']}"
        ),
        f"- reason_codes: {','.join(artifact_contract['reason_codes'])}",
        "",
        "## Corpus Contract",
        f"- status: {corpus_contract['status']}",
        f"- reason_codes: {','.join(corpus_contract['reason_codes'])}",
        f"- scorecard_path: {corpus_contract['scorecard_path']}",
        (
            "- strict_corpus_status_path: "
            f"{corpus_contract['strict_corpus_status_path']}"
        ),
        (
            "- accepted_artifacts_present: "
            f"{corpus_contract['accepted_artifacts_present']}"
        ),
        (
            "- accepted_artifacts_nonzero: "
            f"{corpus_contract['accepted_artifacts_nonzero']}"
        ),
        f"- accepted_artifact_source: {corpus_contract['accepted_artifact_source']}",
        f"- accepted_manifest_path: {corpus_contract['accepted_manifest_path']}",
        f"- accepted_corpus_bundle_dir: {corpus_contract['accepted_corpus_bundle_dir']}",
        (
            "- accepted_manifest_hash_mismatch_count: "
            f"{corpus_contract['accepted_manifest_hash_mismatch_count']}"
        ),
        f"- accepted_run_count: {corpus_contract['accepted_run_count']}",
        f"- required_accepted_runs: {corpus_contract['required_accepted_runs']}",
        "",
        "## Bootstrap Contract",
        f"- status: {bootstrap_contract['status']}",
        f"- reason_codes: {','.join(bootstrap_contract['reason_codes'])}",
        f"- manifest_path: {bootstrap_contract['manifest_path']}",
        f"- source_scorecard_path: {bootstrap_contract['source_scorecard_path']}",
        f"- bundle_dir: {bootstrap_contract['bundle_dir']}",
        f"- db_path: {bootstrap_contract['db_path']}",
        f"- report_path: {bootstrap_contract['report_path']}",
        f"- rows_inserted: {bootstrap_contract['rows_inserted']}",
        f"- pairs_selected: {bootstrap_contract['pairs_selected']}",
        (
            "- positive_side_allowlist: "
            f"{','.join(bootstrap_contract['positive_side_allowlist'])}"
        ),
        "",
        "## Channels",
        f"- operational_channel.status: {report['operational_channel']['status']}",
        (
            "- operational_channel.confidence: "
            f"{report['operational_channel']['confidence']}"
        ),
        (
            "- operational_channel.reason_codes: "
            f"{','.join(report['operational_channel']['reason_codes'])}"
        ),
        f"- economic_channel.status: {economic_channel['status']}",
        f"- economic_channel.go_no_go: {economic_channel['go_no_go']}",
        (
            "- economic_channel.reason_codes: "
            f"{','.join(economic_channel['reason_codes'])}"
        ),
        "",
        "## Economics Context",
    ]
    for key in (
        "status",
        "go_no_go",
        "avg_profit_factor",
        "avg_net_pnl",
        "profitable_run_rate",
        "pf_gt_1_rate",
        "accepted_run_count",
        "required_accepted_runs",
        "scorecard_path",
    ):
        if key in economics_context:
            md_lines.append(f"- {key}: {economics_context[key]}")
    md_lines.extend(["", "## Per-run checks"])
    for run in per_run_checks:
        checks = run.get("checks") or {}
        md_lines.append(
            f"- {run['run_id']}: ok={run['ok']} rows={checks.get('rows', 0)} "
            f"count_matches={checks.get('count_matches', False)} "
            f"all_pairs_in_order={checks.get('all_pairs_in_order', False)} "
            f"all_complete={checks.get('all_complete', False)} "
            f"after_db_nonzero={checks.get('after_db_nonzero', False)} "
            f"report_after_only={checks.get('report_after_only', False)} "
            f"unique_paths_ok={checks.get('unique_paths_ok', False)} "
            f"forbidden_shared_names_detected={checks.get('forbidden_shared_names_detected', False)}"
        )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", default="")
    parser.add_argument("--md-out", default="")
    args = parser.parse_args(argv)
    report = run_gate()
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
        )
    if args.md_out:
        Path(args.md_out).write_text(
            (
                "# PAPER Readiness Gate\n\n"
                f"{json.dumps(report, indent=2, ensure_ascii=True)}\n"
            ),
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["paper_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
