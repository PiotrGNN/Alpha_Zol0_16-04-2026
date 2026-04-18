import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_locked_positive_subset.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "audit_locked_positive_subset",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _descriptor(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "mtime_utc": "2026-04-10T00:00:00+00:00",
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_db(path: Path, run_id: str, trades: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp TEXT NOT NULL, event TEXT NOT NULL, details TEXT)"
        )
        for idx, trade in enumerate(trades):
            pnl = float(trade["pnl"])
            fee_total = float(trade.get("fee", 0.0))
            funding_total = float(trade.get("funding", 0.0))
            gross_pnl = float(trade.get("gross", pnl + fee_total + funding_total))
            details = {
                "symbol": trade["symbol"],
                "strategy": trade["strategy"],
                "realized_pnl": pnl,
                "fee_total": fee_total,
                "funding_cost": funding_total,
                "pnl_decompose": {
                    "gross_fill_pnl_model": gross_pnl,
                    "fee_total": fee_total,
                    "funding_total": funding_total,
                    "net_pnl": pnl,
                },
                "position": {
                    "symbol": trade["symbol"],
                    "strategy": trade["strategy"],
                    "side": trade["side"],
                    "entry_price": 1.0,
                    "close_price": 1.0 + pnl,
                    "amount": 1.0,
                    "timestamp": f"entry-{run_id}-{idx}",
                    "close_timestamp": f"close-{run_id}-{idx}",
                    "realized_pnl": pnl,
                    "fee_total": fee_total,
                    "fee_cost": fee_total,
                    "funding_cost": funding_total,
                    "pnl_decompose": {
                        "gross_fill_pnl_model": gross_pnl,
                        "fee_total": fee_total,
                        "funding_total": funding_total,
                        "net_pnl": pnl,
                    },
                },
            }
            conn.execute(
                "INSERT INTO logs(timestamp, event, details) VALUES(?, ?, ?)",
                (
                    f"2026-04-10T00:{idx:02d}:00+00:00",
                    "position_close",
                    json.dumps(details),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _build_exact_corpus(tmp_path: Path, trades: list[dict]) -> tuple[Path, Path]:
    run_id = "20260410_000001"
    result_path = tmp_path / "accepted_runs" / f"controlled_kpi_{run_id}.json"
    csv_path = tmp_path / "accepted_runs" / f"controlled_kpi_{run_id}.csv"
    db_path = tmp_path / "accepted_runs" / f"controlled_kpi_after_{run_id}.db"
    _write_db(db_path, run_id, trades)
    net_pnl = round(sum(float(trade["pnl"]) for trade in trades), 6)
    _write_json(
        result_path,
        {
            "run_id": run_id,
            "params": {"use_mock": False},
            "after": {
                "variant": "after",
                "trade_count": len(trades),
                "net_pnl": net_pnl,
                "process_returncode": 0,
                "log_health": {"error_count": 0},
                "db_path": str(db_path),
            },
        },
    )
    csv_path.write_text("variant,trade_count,net_pnl\nafter,%d,%s\n" % (len(trades), net_pnl))
    entry = {
        "run_id": run_id,
        "trade_count": len(trades),
        "net_pnl": net_pnl,
        "profit_factor": 1.0,
        "bundled_artifacts": {
            "result_json": _descriptor(result_path),
            "csv": _descriptor(csv_path),
            "db": _descriptor(db_path),
        },
    }
    manifest_path = tmp_path / "accepted_manifest.json"
    manifest = {
        "report_type": "zol0_accepted_corpus_manifest",
        "scope": {
            "exchange": "KuCoin",
            "mode": "PAPER_ONLY",
            "variant": "after",
            "live_in_scope": False,
        },
        "selection": {
            "selection_source": "accepted_manifest",
            "accepted_run_count": 1,
            "accepted_run_ids": [run_id],
            "accepted_dates": ["2026-04-10"],
            "allowed_dates": ["2026-04-10"],
            "required_limit": 1,
        },
        "bundle_validation": {
            "accepted_run_count_matches_scorecard": True,
            "all_source_artifacts_present": True,
            "all_source_artifacts_nonzero": True,
            "all_bundled_hashes_match_source": True,
            "all_bundled_result_after_only": True,
            "all_bundled_result_use_mock_false": True,
            "all_bundled_result_process_ok": True,
        },
        "entries": [entry],
    }
    _write_json(manifest_path, manifest)
    scorecard_path = tmp_path / "scorecard.json"
    _write_json(
        scorecard_path,
        {
            "metadata": {
                "report_type": "zol0_profitability_audit_scorecard",
                "scope": {
                    "exchange": "KuCoin",
                    "mode": "PAPER_ONLY",
                    "variant": "after",
                    "live_in_scope": False,
                },
                "selection": {
                    "selection_source": "accepted_manifest",
                    "accepted_manifest_path": str(manifest_path),
                },
                "sources": {"accepted_corpus_manifest_path": str(manifest_path)},
                "validation": {"all_passed": True},
            }
        },
    )
    return scorecard_path, manifest_path


def test_locked_positive_subset_found_from_exact_manifest(tmp_path):
    module = _load_module()
    trades = [
        {"symbol": "ETHUSDTM", "strategy": "TrendFollowing", "side": "buy", "pnl": 0.02}
        for _ in range(6)
    ] + [
        {"symbol": "ETHUSDTM", "strategy": "TrendFollowing", "side": "buy", "pnl": -0.01}
        for _ in range(4)
    ]
    scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)

    audit = module.build_audit(
        scorecard_path=scorecard_path,
        manifest_path=manifest_path,
    )

    assert audit["evidence_contract"]["status"] == "PASS"
    assert audit["subset_decision"]["verdict"] == "LOCKED_POSITIVE_SUBSET_FOUND"
    assert audit["subset_decision"]["locked_symbol_strategy_side_allowlist"] == [
        "ETHUSDTM:TRENDFOLLOWING:buy"
    ]


def test_artifact_check_sha256_mismatch_sets_ok_false(tmp_path):
    """
    P2-5: _artifact_check must return ok=False and sha256_match=False when the
    expected hash in the manifest descriptor differs from the actual file hash.
    """
    module = _load_module()

    artifact_file = tmp_path / "artifact.db"
    artifact_file.write_bytes(b"real content here - sha will not match the descriptor")

    entry = {
        "bundled_artifacts": {
            "db": {
                "path": str(artifact_file),
                "sha256": "deadbeef" * 8,  # 64-char hex string, but wrong hash
            }
        }
    }
    result = module._artifact_check(entry, "db", "run_mismatch_001")

    assert result["ok"] is False, (
        "SHA256 mismatch must set ok=False in the artifact check result"
    )
    assert result["checks"]["sha256_match"] is False, (
        "checks['sha256_match'] must be False when hash differs"
    )
    # Other checks must pass — the file exists and is non-zero
    assert result["checks"]["exists"] is True
    assert result["checks"]["nonzero"] is True
    assert result["checks"]["path_present"] is True


def test_artifact_check_ok_when_sha256_matches(tmp_path):
    """
    _artifact_check must return ok=True when all checks pass including SHA256.
    """
    import hashlib

    module = _load_module()

    artifact_file = tmp_path / "artifact_ok.db"
    content = b"correct content"
    artifact_file.write_bytes(content)
    correct_sha = hashlib.sha256(content).hexdigest()

    entry = {
        "bundled_artifacts": {
            "db": {
                "path": str(artifact_file),
                "sha256": correct_sha,
            }
        }
    }
    result = module._artifact_check(entry, "db", "run_ok_001")

    assert result["ok"] is True
    assert result["checks"]["sha256_match"] is True


def test_no_positive_subset_keeps_tiny_sample_rejected(tmp_path):
    module = _load_module()
    trades = [
        {"symbol": "XRPUSDTM", "strategy": "TrendFollowing", "side": "buy", "pnl": 0.01}
    ]
    trades += [
        {"symbol": "ETHUSDTM", "strategy": "TrendFollowing", "side": "buy", "pnl": 0.001}
        for _ in range(3)
    ]
    trades += [
        {"symbol": "ETHUSDTM", "strategy": "TrendFollowing", "side": "buy", "pnl": -0.002}
        for _ in range(7)
    ]
    scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)

    audit = module.build_audit(
        scorecard_path=scorecard_path,
        manifest_path=manifest_path,
    )

    assert audit["evidence_contract"]["status"] == "PASS"
    assert audit["subset_decision"]["status"] == "NO_GO"
    assert audit["subset_decision"]["verdict"] == "NO_POSITIVE_SUBSET_FOUND"
    assert audit["subset_decision"]["locked_symbol_strategy_side_allowlist"] == []
    assert "BEST_POSITIVE_BUCKET_TINY_SAMPLE" in audit["subset_decision"]["reason_codes"]
    assert audit["rejected_positive_candidates"][0]["name"] == (
        "XRPUSDTM|TrendFollowing|buy"
    )
    assert audit["rejected_positive_candidates"][0]["rejection_reasons"] == [
        "BELOW_MIN_TRADES"
    ]
