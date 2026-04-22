import json
import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "controlled_kpi_run", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strict_bucket_gate_derives_positive_allowlist_and_toxic_blocks():
    module = _load_module()
    report = {
        "pair_stats_top": [
            {
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 11,
                "winrate": 0.55,
                "expectancy": -0.0046,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 40,
                "winrate": 0.45,
                "expectancy": 0.0026,
                "selected": True,
            },
        ],
        "pair_side_stats_top": [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 30,
                "winrate": 0.50,
                "expectancy": 0.0048,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "Momentum",
                "side": "buy",
                "trade_count": 23,
                "winrate": 0.52,
                "expectancy": 0.00016,
            },
            {
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "side": "sell",
                "trade_count": 5,
                "winrate": 0.60,
                "expectancy": -0.0035,
            },
        ],
    }

    derived = module._derive_profitability_bucket_gate(report)
    overrides = derived["overrides"]

    assert overrides["ALPHA_WHITELIST_ENABLE"] == "0"
    assert overrides["ALPHA_WHITELIST_COLDSTART_ALLOW"] == "0"
    assert overrides["ALPHA_WHITELIST_FALLBACK_ENABLE"] == "0"
    assert overrides["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == (
        "ETHUSDTM:TRENDFOLLOWING:buy"
    )
    assert overrides["ENTRY_SYMBOL_STRATEGY_BLOCKLIST"] == "BTCUSDTM:TRENDFOLLOWING"
    assert overrides["ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST"] == (
        "BTCUSDTM:TRENDFOLLOWING:sell"
    )


def test_strict_bucket_gate_coerces_selected_string_flags():
    module = _load_module()
    report = {
        "pair_stats_top": [
            {
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 11,
                "winrate": 0.55,
                "expectancy": 0.002,
                "selected": "false",
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 40,
                "winrate": 0.50,
                "expectancy": 0.003,
                "selected": "true",
            },
        ],
        "pair_side_stats_top": [
            {
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 11,
                "winrate": 0.55,
                "expectancy": 0.001,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 40,
                "winrate": 0.50,
                "expectancy": 0.003,
            },
        ],
    }

    derived = module._derive_profitability_bucket_gate(report)

    assert derived["positive_side_allowlist"] == [
        "ETHUSDTM:TRENDFOLLOWING:buy"
    ]
    assert derived["overrides"]["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == (
        "ETHUSDTM:TRENDFOLLOWING:buy"
    )


def test_strict_bucket_gate_skips_missing_or_weak_reports():
    module = _load_module()

    assert module._derive_profitability_bucket_gate(None)["overrides"] == {}

    weak_report = {
        "pair_stats_top": [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 4,
                "winrate": 0.25,
                "expectancy": -0.002,
            }
        ],
        "pair_side_stats_top": [],
    }
    assert module._derive_profitability_bucket_gate(
        weak_report, _disable_contract_fallback=True
    )["overrides"] == {}


def test_strict_bucket_gate_requires_at_least_two_side_trades_for_allowlist():
    module = _load_module()
    report = {
        "pair_stats_top": [
            {
                "symbol": "XRPUSDTM",
                "strategy": "Momentum",
                "trade_count": 8,
                "winrate": 0.45,
                "expectancy": 0.01,
                "selected": True,
            },
            {
                "symbol": "XRPUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 8,
                "winrate": 0.45,
                "expectancy": 0.01,
                "selected": True,
            },
        ],
        "pair_side_stats_top": [
            {
                "symbol": "XRPUSDTM",
                "strategy": "Momentum",
                "side": "sell",
                "trade_count": 1,
                "winrate": 1.0,
                "expectancy": 0.12,
            },
            {
                "symbol": "XRPUSDTM",
                "strategy": "TrendFollowing",
                "side": "sell",
                "trade_count": 1,
                "winrate": 1.0,
                "expectancy": 0.05,
            },
            {
                "symbol": "XRPUSDTM",
                "strategy": "Momentum",
                "side": "buy",
                "trade_count": 3,
                "winrate": 0.33,
                "expectancy": -0.05,
            },
            {
                "symbol": "XRPUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 4,
                "winrate": 0.0,
                "expectancy": -0.35,
            },
        ],
    }

    derived = module._derive_profitability_bucket_gate(
        report, _disable_contract_fallback=True
    )

    assert derived["positive_side_allowlist"] == []
    assert "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST" not in derived["overrides"]


def test_strict_bucket_gate_does_not_use_contract_fallback_when_live_side_rows_present(
    monkeypatch, tmp_path
):
    module = _load_module()
    contract_path = (
        tmp_path / "analysis" / "zol0_positive_side_allowlist_contract_current.json"
    )
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "positive_side_allowlist": ["ETHUSDTM:TRENDFOLLOWING:buy"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    report = {
        "pair_stats_top": [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 12,
                "winrate": 0.30,
                "expectancy": -0.0020,
                "selected": True,
            }
        ],
        "pair_side_stats_top": [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 12,
                "winrate": 0.30,
                "expectancy": -0.0020,
                "net_pnl": -0.024,
                "gross_pnl": -0.010,
                "fee_total": 0.014,
            }
        ],
    }

    derived = module._derive_profitability_bucket_gate(report)

    assert derived["positive_side_allowlist"] == []
    assert "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST" not in derived["overrides"]


def test_strict_bucket_gate_uses_contract_fallback_when_no_valid_side_rows(
    monkeypatch, tmp_path
):
    module = _load_module()
    contract_path = (
        tmp_path / "analysis" / "zol0_positive_side_allowlist_contract_current.json"
    )
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "positive_side_allowlist": ["ETHUSDTM:TRENDFOLLOWING:buy"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    report = {
        "pair_stats_top": [],
        "pair_side_stats_top": ["malformed-row"],
    }

    derived = module._derive_profitability_bucket_gate(report)

    assert derived["positive_side_allowlist"] == ["ETHUSDTM:TRENDFOLLOWING:buy"]
    assert derived["overrides"]["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == (
        "ETHUSDTM:TRENDFOLLOWING:buy"
    )


def test_strict_bucket_gate_filters_contract_fallback_to_active_run_symbols(
    monkeypatch, tmp_path
):
    module = _load_module()
    contract_path = (
        tmp_path / "analysis" / "zol0_positive_side_allowlist_contract_current.json"
    )
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "positive_side_allowlist": [
                    "SOLUSDTM:TRENDFOLLOWING:sell",
                    "ADAUSDTM:TRENDFOLLOWING:buy",
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    report = {
        "pair_stats_top": [],
        "pair_side_stats_top": ["malformed-row"],
    }

    derived = module._derive_profitability_bucket_gate(
        report,
        active_run_symbols={"BTCUSDTM", "SOLUSDTM"},
    )

    assert derived["positive_side_allowlist"] == ["SOLUSDTM:TRENDFOLLOWING:sell"]
    assert derived["overrides"]["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == (
        "SOLUSDTM:TRENDFOLLOWING:sell,SOLUSDTM:UNIVERSAL:sell"
    )


def test_strict_bucket_gate_blocks_cost_burden_side_without_allowlist():
    module = _load_module()
    report = {
        "pair_stats_top": [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 10,
                "winrate": 0.30,
                "expectancy": -0.000967,
                "selected": False,
            }
        ],
        "pair_side_stats_top": [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 10,
                "winrate": 0.30,
                "expectancy": -0.000967,
                "net_pnl": -0.009672,
                "gross_pnl": 0.010332,
                "fee_total": 0.020004,
            }
        ],
    }

    derived = module._derive_profitability_bucket_gate(
        report, _disable_contract_fallback=True
    )
    overrides = derived["overrides"]

    assert derived["positive_side_allowlist"] == []
    assert derived["cost_burden_side_blocklist"] == [
        "ETHUSDTM:TRENDFOLLOWING:buy"
    ]
    assert overrides == {
        "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "ETHUSDTM:TRENDFOLLOWING:buy"
    }


def test_strict_bucket_gate_avoids_allowlist_blocklist_conflict_on_universal_sell_expansion():
    module = _load_module()
    report = {
        "pair_stats_top": [
            {
                "symbol": "XRPUSDTM",
                "strategy": "Momentum",
                "trade_count": 10,
                "winrate": 0.60,
                "expectancy": 0.0012,
                "selected": True,
            }
        ],
        "pair_side_stats_top": [
            {
                "symbol": "XRPUSDTM",
                "strategy": "Momentum",
                "side": "sell",
                "trade_count": 6,
                "winrate": 0.60,
                "expectancy": 0.0015,
                "net_pnl": 0.009,
                "gross_pnl": 0.015,
                "fee_total": 0.006,
            },
            {
                "symbol": "XRPUSDTM",
                "strategy": "Universal",
                "side": "sell",
                "trade_count": 7,
                "winrate": 0.57,
                "expectancy": -0.0005,
                "net_pnl": -0.0035,
                "gross_pnl": 0.0010,
                "fee_total": 0.0045,
            },
        ],
    }

    derived = module._derive_profitability_bucket_gate(
        report, _disable_contract_fallback=True
    )
    overrides = derived["overrides"]
    allow_tokens = {
        token.strip()
        for token in str(
            overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", "")
        ).split(",")
        if token.strip()
    }
    block_tokens = {
        token.strip()
        for token in str(
            overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST", "")
        ).split(",")
        if token.strip()
    }

    assert "XRPUSDTM:MOMENTUM:sell" in allow_tokens
    assert "XRPUSDTM:UNIVERSAL:sell" not in allow_tokens
    assert "XRPUSDTM:UNIVERSAL:sell" in block_tokens
    assert allow_tokens.isdisjoint(block_tokens)


def test_strict_bucket_gate_handles_malformed_rows_and_side_normalization():
    module = _load_module()
    report = {
        "pair_stats_top": [
            "not-a-dict",
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": 40,
                "winrate": 0.6,
                "expectancy": 0.05,
                "selected": True,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "trade_count": "bad",
                "winrate": "bad",
                "expectancy": "bad",
                "selected": True,
            },
            {
                "symbol": "",
                "strategy": "TrendFollowing",
                "trade_count": 10,
                "winrate": 0.55,
                "expectancy": 0.01,
            },
        ],
        "pair_side_stats_top": [
            "still-not-a-dict",
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "long",
                "trade_count": 40,
                "winrate": 0.6,
                "expectancy": 0.05,
                "gross_pnl": 1.0,
                "fee_total": 0.2,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "short",
                "trade_count": "bad",
                "winrate": "bad",
                "expectancy": "bad",
                "gross_pnl": "bad",
                "fee_total": "bad",
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "",
                "side": "buy",
                "trade_count": 8,
                "winrate": 0.52,
                "expectancy": 0.005,
                "gross_pnl": 1.0,
                "fee_total": 0.2,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "left",
                "trade_count": 8,
                "winrate": 0.52,
                "expectancy": 0.005,
                "gross_pnl": 1.0,
                "fee_total": 0.2,
            },
        ],
    }

    derived = module._derive_profitability_bucket_gate(report)

    assert derived["positive_side_allowlist"] == ["ETHUSDTM:TRENDFOLLOWING:buy"]
    assert derived["toxic_pair_blocklist"] == []
    assert derived["toxic_side_blocklist"] == []
    assert derived["cost_burden_side_blocklist"] == []


def test_alpha_bootstrap_runtime_contract_pass_without_fail_closed():
    module = _load_module()
    contract = module._derive_alpha_bootstrap_runtime_contract(
        {
            "status": "UNCONFIRMED",
            "source_fail_closed": False,
            "reason_codes": ["manifest_rows_inserted_zero"],
            "exact_source_contract": {"active": True},
        }
    )

    assert contract["status"] == "PASS"
    assert contract["active"] is True
    assert contract["source_fail_closed"] is False
    assert contract["refresh_status"] == "UNCONFIRMED"
    assert contract["reason_codes"] == ["manifest_rows_inserted_zero"]


def test_alpha_bootstrap_runtime_contract_fail_closed_with_reason_codes():
    module = _load_module()
    contract = module._derive_alpha_bootstrap_runtime_contract(
        {
            "status": "UNCONFIRMED",
            "source_fail_closed": True,
            "reason_codes": [
                "external_rows_inserted_zero",
                "source_fail_closed",
            ],
            "exact_source_contract": {"active": True},
        }
    )

    assert contract["status"] == "FAIL_CLOSED"
    assert contract["active"] is True
    assert contract["source_fail_closed"] is True
    assert contract["refresh_status"] == "UNCONFIRMED"
    assert contract["reason_codes"] == [
        "source_fail_closed",
        "external_rows_inserted_zero",
    ]


def test_prebuilt_manifest_rejects_duplicate_accepted_run_ids(monkeypatch, tmp_path):
    module = _load_module()
    diag_dir = tmp_path / "diagnostics"
    tmp_shadow = tmp_path / "tmp"
    diag_dir.mkdir(parents=True, exist_ok=True)
    tmp_shadow.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diag_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_shadow)

    db_path = diag_dir / "alpha_history.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE logs (rows_inserted INTEGER)")
        conn.execute("INSERT INTO logs(rows_inserted) VALUES (1)")
        conn.commit()
    finally:
        conn.close()

    report_path = diag_dir / "alpha_history_report.json"
    report_path.write_text(
        json.dumps({"rows_inserted": 1, "output": str(db_path)}),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "prebuilt_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {
                    "accepted_run_ids": ["run_a", "run_a"],
                },
                "prebuilt_source": {
                    "db_path": str(db_path),
                    "db_size_bytes": db_path.stat().st_size,
                    "db_sha256": module._sha256_file(db_path),
                    "report_path": str(report_path),
                    "report_size_bytes": report_path.stat().st_size,
                    "report_sha256": module._sha256_file(report_path),
                    "rows_inserted": 1,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a", "run_a"],
    )

    assert manifest["valid"] is False
    assert "manifest_accepted_run_ids_duplicate" in manifest["reason_codes"]


def test_prebuilt_manifest_flags_missing_manifest_path():
    module = _load_module()

    manifest = module._load_alpha_bootstrap_prebuilt_manifest("", expected_run_ids=None)

    assert manifest["valid"] is False
    assert manifest["reason_codes"] == ["manifest_path_missing"]


def test_prebuilt_manifest_flags_missing_manifest_file(tmp_path):
    module = _load_module()
    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(tmp_path / "missing_manifest.json"),
        expected_run_ids=None,
    )

    assert manifest["valid"] is False
    assert manifest["reason_codes"] == ["manifest_missing"]


def test_prebuilt_manifest_flags_unreadable_manifest(tmp_path):
    module = _load_module()
    manifest_path = tmp_path / "unreadable_manifest.json"
    manifest_path.write_text("{not-json", encoding="utf-8")

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=None,
    )

    assert manifest["valid"] is False
    assert manifest["reason_codes"] == ["manifest_unreadable"]


def test_prebuilt_manifest_flags_missing_source_paths(monkeypatch, tmp_path):
    module = _load_module()
    diag_dir = tmp_path / "diagnostics"
    tmp_shadow = tmp_path / "tmp"
    diag_dir.mkdir(parents=True, exist_ok=True)
    tmp_shadow.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diag_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_shadow)

    manifest_path = tmp_path / "missing_paths_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert manifest["valid"] is False
    assert "manifest_db_path_missing" in manifest["reason_codes"]

    db_path = tmp_shadow / "alpha.db"
    db_path.write_text("db", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {"db_path": str(db_path)},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert manifest["valid"] is False
    assert "manifest_report_path_missing" in manifest["reason_codes"]


def test_prebuilt_manifest_flags_missing_report_file(monkeypatch, tmp_path):
    module = _load_module()
    diag_dir = tmp_path / "diagnostics"
    tmp_shadow = tmp_path / "tmp"
    diag_dir.mkdir(parents=True, exist_ok=True)
    tmp_shadow.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diag_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_shadow)

    db_path = diag_dir / "alpha_history.db"
    db_path.write_bytes(b"db")
    report_path = diag_dir / "missing_alpha_history_report.json"
    manifest_path = tmp_path / "missing_report_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {
                    "db_path": str(db_path),
                    "report_path": str(report_path),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert manifest["valid"] is False
    assert manifest["report_path"] == str(report_path.resolve())
    assert "manifest_report_missing" in manifest["reason_codes"]


def test_prebuilt_manifest_flags_path_and_checksum_mismatches(monkeypatch, tmp_path):
    module = _load_module()
    diag_dir = tmp_path / "diagnostics"
    tmp_shadow = tmp_path / "tmp"
    diag_dir.mkdir(parents=True, exist_ok=True)
    tmp_shadow.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diag_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_shadow)

    db_path = tmp_shadow / "alpha_history.db"
    db_path.write_text("db", encoding="utf-8")
    report_path = tmp_shadow / "alpha_history_report.json"
    report_path.write_text(
        json.dumps(
            {
                "rows_inserted": 2,
                "output": str(report_path.with_name("other.db")),
            }
        ),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "mismatch_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {
                    "source_scorecard_path": (
                        "analysis/zol0_profitability_audit_scorecard.json"
                    ),
                    "db_path": str(db_path),
                    "db_size_bytes": db_path.stat().st_size + 1,
                    "db_sha256": "0" * 64,
                    "report_path": str(report_path),
                    "report_size_bytes": report_path.stat().st_size + 1,
                    "report_sha256": "1" * 64,
                    "rows_inserted": 3,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert manifest["valid"] is False
    assert "manifest_db_tmp_forbidden" in manifest["reason_codes"]
    assert "manifest_db_outside_diagnostics" in manifest["reason_codes"]
    assert "manifest_report_tmp_forbidden" in manifest["reason_codes"]
    assert "manifest_report_outside_diagnostics" in manifest["reason_codes"]
    assert "manifest_db_size_mismatch" in manifest["reason_codes"]
    assert "manifest_db_sha_mismatch" in manifest["reason_codes"]
    assert "manifest_report_size_mismatch" in manifest["reason_codes"]
    assert "manifest_report_sha_mismatch" in manifest["reason_codes"]
    assert "manifest_report_output_mismatch" in manifest["reason_codes"]
    assert "manifest_rows_inserted_mismatch" in manifest["reason_codes"]


def test_prebuilt_manifest_flags_invalid_scope_and_run_id_mismatch(
    monkeypatch, tmp_path
):
    module = _load_module()
    diag_dir = tmp_path / "diagnostics"
    tmp_shadow = tmp_path / "tmp"
    diag_dir.mkdir(parents=True, exist_ok=True)
    tmp_shadow.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diag_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_shadow)

    db_path = diag_dir / "alpha_history_valid.db"
    db_path.write_text("db", encoding="utf-8")
    report_path = diag_dir / "alpha_history_valid_report.json"
    report_path.write_text(
        json.dumps({"rows_inserted": 1, "output": str(db_path)}),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "invalid_scope_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "OtherExchange",
                        "mode": "LIVE",
                        "variant": "before",
                        "live_in_scope": True,
                    }
                },
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {
                    "db_path": str(db_path),
                    "report_path": str(report_path),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_b"],
    )

    assert manifest["valid"] is False
    assert "manifest_scope_exchange_invalid" in manifest["reason_codes"]
    assert "manifest_scope_mode_invalid" in manifest["reason_codes"]
    assert "manifest_scope_variant_invalid" in manifest["reason_codes"]
    assert "manifest_scope_live_invalid" in manifest["reason_codes"]
    assert "manifest_accepted_run_ids_mismatch" in manifest["reason_codes"]


def test_entry_admission_contract_fails_closed_without_side_allowlist():
    module = _load_module()
    contract = module._derive_entry_admission_contract(
        variant_only="after",
        paper_auto_open=True,
        after_overrides={
            "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "ETHUSDTM:TRENDFOLLOWING:buy",
        },
        alpha_bootstrap_runtime_contract={"status": "FAIL_CLOSED"},
        strict_bucket_gate={
            "positive_side_allowlist": [],
            "cost_burden_side_blocklist": ["ETHUSDTM:TRENDFOLLOWING:buy"],
        },
    )

    assert contract["status"] == "FAIL_CLOSED"
    assert contract["reason_codes"] == [
        "NO_ELIGIBLE_ENTRY_BUCKETS",
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_EMPTY",
        "STRICT_POSITIVE_SIDE_ALLOWLIST_EMPTY",
        "PAPER_AUTO_OPEN_EXPLICIT_SIDE_ALLOWLIST_REQUIRED",
        "ALPHA_BOOTSTRAP_RUNTIME_FAIL_CLOSED",
    ]


def test_entry_admission_contract_fails_closed_with_runtime_pass_but_no_allowlist():
    module = _load_module()
    contract = module._derive_entry_admission_contract(
        variant_only="after",
        paper_auto_open=True,
        after_overrides={},
        alpha_bootstrap_runtime_contract={"status": "PASS"},
        strict_bucket_gate={"positive_side_allowlist": []},
    )

    assert contract["status"] == "FAIL_CLOSED"
    assert contract["validation_classification"] == (
        "NO_ELIGIBLE_POSITIVE_ENTRY_BUCKETS"
    )
    assert "NO_ELIGIBLE_ENTRY_BUCKETS" in contract["reason_codes"]
    assert "ALPHA_BOOTSTRAP_RUNTIME_FAIL_CLOSED" not in contract["reason_codes"]


def test_entry_admission_contract_marks_paper_auto_open_false_as_diagnostic():
    module = _load_module()
    contract = module._derive_entry_admission_contract(
        variant_only="after",
        paper_auto_open=False,
        after_overrides={},
        alpha_bootstrap_runtime_contract={"status": "PASS"},
        strict_bucket_gate={"positive_side_allowlist": []},
    )

    assert contract["status"] == "PASS"
    assert contract["validation_classification"] == "DIAGNOSTIC_NO_OPEN_RUN"
    assert "DIAGNOSTIC_NO_OPEN_RUN" in contract["reason_codes"]
    assert "PAPER_AUTO_OPEN_DISABLED" in contract["reason_codes"]


def test_entry_admission_contract_passes_with_explicit_side_allowlist():
    module = _load_module()
    contract = module._derive_entry_admission_contract(
        variant_only="after",
        paper_auto_open=True,
        after_overrides={
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:sell",
            "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "ETHUSDTM:TRENDFOLLOWING:buy",
        },
        alpha_bootstrap_runtime_contract={"status": "FAIL_CLOSED"},
        strict_bucket_gate={"positive_side_allowlist": []},
    )

    assert contract["status"] == "PASS"
    assert contract["explicit_side_allowlist"] == [
        "BTCUSDTM:TRENDFOLLOWING:sell"
    ]
    assert "EXPLICIT_SIDE_ALLOWLIST_PRESENT" in contract["reason_codes"]


def test_entry_admission_contract_fails_closed_on_side_allowlist_blocklist_conflict():
    module = _load_module()
    contract = module._derive_entry_admission_contract(
        variant_only="after",
        paper_auto_open=True,
        after_overrides={
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": "ETHUSDTM:TRENDFOLLOWING:long",
            "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "ethusdtm:trendfollowing:buy",
        },
        alpha_bootstrap_runtime_contract={"status": "PASS"},
        strict_bucket_gate={"positive_side_allowlist": []},
    )

    assert contract["status"] == "FAIL_CLOSED"
    assert contract["validation_classification"] == (
        "ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT"
    )
    assert "ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT" in contract["reason_codes"]
    assert contract["conflicting_side_tokens"] == [
        "ETHUSDTM:TRENDFOLLOWING:buy"
    ]


def test_entry_admission_contract_fails_closed_when_strict_allowlist_conflicts():
    module = _load_module()
    contract = module._derive_entry_admission_contract(
        variant_only="after",
        paper_auto_open=True,
        after_overrides={
            "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "BTCUSDTM:TRENDFOLLOWING:sell",
        },
        alpha_bootstrap_runtime_contract={"status": "PASS"},
        strict_bucket_gate={
            "positive_side_allowlist": ["BTCUSDTM:TRENDFOLLOWING:sell"]
        },
    )

    assert contract["status"] == "FAIL_CLOSED"
    assert contract["validation_classification"] == (
        "ENTRY_SIDE_ALLOWLIST_BLOCKLIST_CONFLICT"
    )
    assert contract["conflicting_side_tokens"] == [
        "BTCUSDTM:TRENDFOLLOWING:sell"
    ]


def test_positive_side_allowlist_contract_applies_exact_allowlist():
    module = _load_module()
    after_overrides = {}

    result = module._apply_positive_side_allowlist_contract(
        after_overrides=after_overrides,
        after_overrides_cli={},
        contract={
            "status": "PASS",
            "positive_side_allowlist": ["BTCUSDTM:TRENDFOLLOWING:sell"],
        },
    )

    assert result["allowlist_applied"] is True
    assert after_overrides["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == (
        "BTCUSDTM:TRENDFOLLOWING:sell"
    )
    assert after_overrides["ALPHA_WHITELIST_ENABLE"] == "0"
    assert after_overrides["ALPHA_WHITELIST_COLDSTART_ALLOW"] == "0"
    assert after_overrides["ALPHA_WHITELIST_FALLBACK_ENABLE"] == "0"


def test_positive_side_allowlist_contract_rejects_malformed_payload(tmp_path):
    module = _load_module()
    contract_path = tmp_path / "positive_side_allowlist_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "positive_side_allowlist": "BTCUSDTM:TRENDFOLLOWING:sell",
                "reason_codes": ["ok"],
                "thresholds": {},
                "evidence_contract": {},
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    result = module._load_positive_side_allowlist_contract(str(contract_path))

    assert result["status"] == "MALFORMED"
    assert result["positive_side_allowlist"] == []
    assert result["reason_codes"] == ["contract_malformed"]


def test_prebuilt_manifest_rejects_malformed_root_and_nested_containers(tmp_path):
    module = _load_module()
    manifest_path = tmp_path / "malformed_manifest.json"
    manifest_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert manifest["valid"] is False
    assert manifest["reason_codes"] == ["manifest_malformed"]

    manifest_path.write_text(
        json.dumps(
            {
                "metadata": "broken",
                "selection": "broken",
                "prebuilt_source": "broken",
            }
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert manifest["valid"] is False
    assert "manifest_metadata_malformed" in manifest["reason_codes"]
    assert "manifest_selection_malformed" in manifest["reason_codes"]
    assert "manifest_prebuilt_source_malformed" in manifest["reason_codes"]


def test_prebuilt_manifest_coerces_live_in_scope_string_false(tmp_path):
    module = _load_module()
    manifest_path = tmp_path / "manifest_live_false.json"
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "kucoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": "false",
                    }
                },
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(manifest_path),
        expected_run_ids=["run_a"],
    )

    assert "manifest_scope_live_invalid" not in manifest["reason_codes"]


def test_prebuilt_manifest_handles_scope_and_payload_edge_cases(
    monkeypatch, tmp_path
):
    module = _load_module()
    diag_dir = tmp_path / "diagnostics"
    tmp_shadow = tmp_path / "tmp"
    diag_dir.mkdir(parents=True, exist_ok=True)
    tmp_shadow.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diag_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_shadow)

    original_stat = module.Path.stat
    original_exists = module.Path.exists
    original_resolve = module.Path.resolve

    def fake_exists(self, *args, **kwargs):
        if self.name in {"broken.db", "broken_report.json"}:
            return True
        return original_exists(self, *args, **kwargs)

    def fake_stat(self, *args, **kwargs):
        if self.name in {"broken.db", "broken_report.json"}:
            raise OSError("stat boom")
        return original_stat(self, *args, **kwargs)

    def fake_resolve(self, *args, **kwargs):
        if self.name == "bad_output.db":
            raise OSError("resolve boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(module.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(module.Path, "stat", fake_stat, raising=False)
    monkeypatch.setattr(module.Path, "resolve", fake_resolve, raising=False)

    malformed_db = diag_dir / "broken.db"
    malformed_db.write_bytes(b"db")
    malformed_report = diag_dir / "broken_report.json"
    malformed_report.write_bytes(b"")
    malformed_manifest_path = tmp_path / "malformed_scope_manifest.json"
    malformed_manifest_path.write_text(
        json.dumps(
            {
                "metadata": {"scope": "broken"},
                "selection": {"accepted_run_ids": ["run_a"]},
                "prebuilt_source": {
                    "db_path": str(malformed_db),
                    "report_path": str(malformed_report),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    malformed_manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(malformed_manifest_path),
        expected_run_ids=["run_a"],
    )

    assert malformed_manifest["valid"] is False
    assert "manifest_scope_malformed" in malformed_manifest["reason_codes"]
    assert "manifest_db_zero_or_empty" in malformed_manifest["reason_codes"]
    assert "manifest_report_zero_or_empty" in malformed_manifest["reason_codes"]
    assert "manifest_report_unreadable" in malformed_manifest["reason_codes"]
    assert "manifest_rows_inserted_zero" in malformed_manifest["reason_codes"]

    rows_db = diag_dir / "rows.db"
    rows_db.write_bytes(b"db")
    rows_report = diag_dir / "rows_report.json"
    rows_report.write_text(
        json.dumps({"rows_inserted": "bad", "output": "bad_output.db"}),
        encoding="utf-8",
    )
    rows_manifest_path = tmp_path / "rows_manifest.json"
    rows_manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {"accepted_run_ids": ["run_b"]},
                "prebuilt_source": {
                    "db_path": str(rows_db),
                    "report_path": str(rows_report),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rows_manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(rows_manifest_path),
        expected_run_ids=["run_b"],
    )

    assert rows_manifest["valid"] is False
    assert "manifest_rows_inserted_zero" in rows_manifest["reason_codes"]
    assert "manifest_report_output_mismatch" in rows_manifest["reason_codes"]

    missing_manifest_path = tmp_path / "missing_db_manifest.json"
    missing_manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {"accepted_run_ids": ["run_c"]},
                "prebuilt_source": {
                    "db_path": str(tmp_path / "missing.db"),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    missing_manifest = module._load_alpha_bootstrap_prebuilt_manifest(
        str(missing_manifest_path),
        expected_run_ids=["run_c"],
    )

    assert missing_manifest["valid"] is False
    assert missing_manifest["reason_codes"] == ["manifest_db_missing"]


def test_alpha_bootstrap_refresh_and_runtime_coerce_string_booleans():
    module = _load_module()
    refresh = module._finalize_alpha_bootstrap_refresh_contract(
        {
            "ran": "false",
            "output_exists": "true",
            "returncode": 0,
            "report": {"rows_inserted": 0},
            "exact_source_contract": {"active": "true"},
        }
    )
    assert refresh["status"] == "FAIL"
    assert "refresh_not_run" in refresh["reason_codes"]
    assert refresh["success"] is False
    assert refresh["exact_source_contract"]["status"] == "FAIL"

    runtime = module._derive_alpha_bootstrap_runtime_contract(
        {
            "status": "UNCONFIRMED",
            "source_fail_closed": "false",
            "reason_codes": ["source_fail_closed"],
            "exact_source_contract": {"active": "false"},
        }
    )
    assert runtime["status"] == "PASS"
    assert runtime["source_fail_closed"] is False
    assert runtime["active"] is False
    assert runtime["reason_codes"] == ["source_fail_closed"]


def test_alpha_bootstrap_refresh_contract_demotes_to_unconfirmed_on_reason_codes():
    module = _load_module()
    refresh = module._finalize_alpha_bootstrap_refresh_contract(
        {
            "ran": True,
            "output_exists": True,
            "returncode": 0,
            "report": {"rows_inserted": 3},
            "exact_source_contract": {
                "active": True,
                "reason_codes": ["manifest_rows_inserted_zero"],
            },
        }
    )

    assert refresh["status"] == "UNCONFIRMED"
    assert refresh["success"] is False
    assert refresh["reason_codes"] == ["manifest_rows_inserted_zero"]
    assert refresh["exact_source_contract"]["status"] == "UNCONFIRMED"


def test_alpha_bootstrap_refresh_contract_fails_when_output_missing():
    module = _load_module()
    refresh = module._finalize_alpha_bootstrap_refresh_contract(
        {
            "ran": True,
            "output_exists": False,
            "returncode": 0,
            "report": {"rows_inserted": 1},
            "exact_source_contract": {"active": False},
        }
    )

    assert refresh["status"] == "FAIL"
    assert refresh["success"] is False
    assert refresh["reason_codes"] == ["refresh_output_missing"]


def test_alpha_bootstrap_refresh_contract_fails_when_returncode_nonzero():
    module = _load_module()
    refresh = module._finalize_alpha_bootstrap_refresh_contract(
        {
            "ran": True,
            "output_exists": True,
            "returncode": 17,
            "report": {"rows_inserted": 1},
            "exact_source_contract": {"active": False},
        }
    )

    assert refresh["status"] == "FAIL"
    assert refresh["success"] is False
    assert refresh["reason_codes"] == ["refresh_returncode_nonzero"]


def test_alpha_bootstrap_refresh_contract_marks_unconfirmed_when_rows_missing():
    module = _load_module()
    refresh = module._finalize_alpha_bootstrap_refresh_contract(
        {
            "ran": True,
            "output_exists": True,
            "returncode": 0,
            "report": {"rows_inserted": 0},
            "exact_source_contract": {"active": True},
        }
    )

    assert refresh["status"] == "UNCONFIRMED"
    assert refresh["success"] is False
    assert refresh["reason_codes"] == ["external_rows_inserted_zero"]
    assert refresh["exact_source_contract"]["status"] == "UNCONFIRMED"


def test_alpha_bootstrap_refresh_contract_keeps_pass_for_prebuilt_seed_only_gap():
    module = _load_module()
    refresh = module._finalize_alpha_bootstrap_refresh_contract(
        {
            "ran": True,
            "output_exists": True,
            "returncode": 0,
            "report": {"rows_inserted": 0},
            "exact_source_contract": {
                "active": True,
                "source_mode": "prebuilt_alpha_history_db",
                "prebuilt_alpha_history_rows_inserted": 85,
                "reason_codes": [],
            },
        }
    )

    assert refresh["status"] == "PASS"
    assert refresh["success"] is True
    assert refresh["reason_codes"] == ["external_rows_inserted_zero"]
    assert refresh["exact_source_contract"]["status"] == "PASS"


def test_exact_source_contract_prefers_valid_prebuilt_db(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)
    monkeypatch.setattr(module, "TMP_DIR", tmp_path / "tmp")

    (tmp_path / "tmp").mkdir(parents=True, exist_ok=True)
    scorecard_path = tmp_path / "scorecard.json"
    accepted_db_path = tmp_path / "tmp" / "controlled_kpi_after_run-a.db"
    accepted_db_path.write_bytes(b"seed")
    prebuilt_db_path = tmp_path / "prebuilt_alpha_history.db"
    prebuilt_db_path.write_bytes(b"prebuilt-db")
    prebuilt_report_path = tmp_path / "prebuilt_alpha_history_report.json"
    prebuilt_report_path.write_text(
        json.dumps(
            {
                "rows_inserted": 4,
                "output": str(prebuilt_db_path),
            }
        ),
        encoding="utf-8",
    )
    scorecard_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {
                        "accepted_run_ids": ["run-a"],
                    },
                    "sources": {
                        "alpha_history_db_path": str(prebuilt_db_path),
                        "bootstrap_report_path": str(prebuilt_report_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard.json"
    )

    assert contract["active"] is True
    assert contract["accepted_run_ids"] == ["run-a"]
    assert contract["exact_after_db_patterns"] == [
        "tmp/controlled_kpi_after_run-a.db"
    ]
    assert contract["existing_run_ids"] == ["run-a"]
    assert contract["nonzero_run_ids"] == ["run-a"]
    assert contract["source_mode"] == "prebuilt_alpha_history_db"
    assert contract["prebuilt_alpha_history_db_path"] == str(prebuilt_db_path)
    assert contract["prebuilt_alpha_history_report_path"] == str(
        prebuilt_report_path
    )
    assert contract["prebuilt_alpha_history_rows_inserted"] == 4
    assert contract["reason_codes"] == []
    assert contract["resolved_scorecard_path"] == str(scorecard_path.resolve())


def test_exact_source_contract_falls_back_to_prebuilt_manifest(
    tmp_path,
    monkeypatch,
):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)
    monkeypatch.setattr(module, "TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", tmp_path / "diagnostics")

    (tmp_path / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "diagnostics").mkdir(parents=True, exist_ok=True)
    (tmp_path / "analysis").mkdir(parents=True, exist_ok=True)

    scorecard_path = tmp_path / "scorecard.json"
    scorecard_prebuilt_db_path = tmp_path / "scorecard_prebuilt.db"
    scorecard_prebuilt_db_path.write_bytes(b"prebuilt")
    scorecard_prebuilt_report_path = tmp_path / "scorecard_prebuilt_report.json"
    scorecard_prebuilt_report_path.write_text(
        json.dumps(
            {
                "rows_inserted": 0,
                "output": str(scorecard_prebuilt_db_path),
            }
        ),
        encoding="utf-8",
    )
    zero_run_db_path = tmp_path / "tmp" / "controlled_kpi_after_run-b.db"
    zero_run_db_path.touch()

    scorecard_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {
                        "accepted_run_ids": ["run-b"],
                    },
                    "sources": {
                        "alpha_history_db_path": str(scorecard_prebuilt_db_path),
                        "bootstrap_report_path": str(
                            scorecard_prebuilt_report_path
                        ),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest_db_path = tmp_path / "diagnostics" / "alpha_history.db"
    manifest_db_path.write_bytes(b"manifest-db")
    manifest_report_path = tmp_path / "diagnostics" / "alpha_history_report.json"
    manifest_report_path.write_text(
        json.dumps(
            {
                "rows_inserted": 2,
                "output": str(manifest_db_path),
            }
        ),
        encoding="utf-8",
    )
    source_scorecard_path = tmp_path / "analysis" / "source_scorecard.json"
    source_scorecard_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "analysis" / (
        "zol0_profitability_audit_strict_bootstrap_manifest.json"
    )
    manifest_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "scope": {
                        "exchange": "KuCoin",
                        "mode": "PAPER_ONLY",
                        "variant": "after",
                        "live_in_scope": False,
                    }
                },
                "selection": {
                    "accepted_run_ids": ["run-b"],
                },
                "prebuilt_source": {
                    "source_scorecard_path": str(source_scorecard_path),
                    "db_path": str(manifest_db_path),
                    "db_size_bytes": manifest_db_path.stat().st_size,
                    "db_sha256": module._sha256_file(manifest_db_path),
                    "report_path": str(manifest_report_path),
                    "report_size_bytes": manifest_report_path.stat().st_size,
                    "report_sha256": module._sha256_file(manifest_report_path),
                    "rows_inserted": 2,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard.json"
    )

    assert contract["active"] is True
    assert contract["accepted_run_ids"] == ["run-b"]
    assert contract["exact_after_db_patterns"] == [
        "tmp/controlled_kpi_after_run-b.db"
    ]
    assert contract["existing_run_ids"] == ["run-b"]
    assert contract["nonzero_run_ids"] == []
    assert contract["source_mode"] == "prebuilt_alpha_history_manifest"
    assert contract["prebuilt_manifest_path"] == str(manifest_path)
    assert contract["prebuilt_alpha_history_db_path"] == str(manifest_db_path)
    assert contract["prebuilt_alpha_history_report_path"] == str(
        manifest_report_path
    )
    assert contract["prebuilt_alpha_history_rows_inserted"] == 2
    assert contract["resolved_scorecard_path"] == str(source_scorecard_path.resolve())
    assert contract["reason_codes"] == []


def test_exact_source_contract_flags_missing_accepted_run_ids(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    scorecard_path = tmp_path / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {
                        "accepted_run_ids": [],
                    },
                    "sources": {},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard.json"
    )

    assert contract["active"] is True
    assert contract["accepted_run_ids"] == []
    assert contract["reason_codes"] == ["accepted_run_ids_missing"]
    assert contract["prebuilt_manifest_path"] is None


def test_exact_source_contract_flags_missing_and_unreadable_scorecards(
    tmp_path,
    monkeypatch,
):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    missing_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "missing_scorecard.json"
    )
    assert missing_contract["reason_codes"] == ["scorecard_missing"]

    unreadable_path = tmp_path / "unreadable_scorecard.json"
    unreadable_path.write_text("{not-json", encoding="utf-8")
    unreadable_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "unreadable_scorecard.json"
    )
    assert unreadable_contract["reason_codes"] == ["scorecard_unreadable"]


def test_exact_source_contract_covers_prebuilt_source_failures_and_manifest_reasons(
    tmp_path,
    monkeypatch,
):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)
    monkeypatch.setattr(module, "TMP_DIR", tmp_path / "tmp")

    (tmp_path / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "analysis").mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "analysis" / (
        "zol0_profitability_audit_strict_bootstrap_manifest.json"
    )
    manifest_path.write_text("{not-json", encoding="utf-8")

    zero_db_path = tmp_path / "zero_db.db"
    zero_db_path.touch()
    valid_report_path = tmp_path / "valid_report.json"
    valid_report_path.write_text(
        json.dumps({"rows_inserted": 1, "output": str(zero_db_path)}),
        encoding="utf-8",
    )

    db_in_tmp_path = tmp_path / "tmp" / "db_in_tmp.db"
    db_in_tmp_path.write_bytes(b"db")

    report_in_tmp_path = tmp_path / "tmp" / "report_in_tmp.json"
    report_in_tmp_path.write_text(
        json.dumps({"rows_inserted": 1, "output": str(zero_db_path)}),
        encoding="utf-8",
    )

    invalid_report_path = tmp_path / "invalid_report.json"
    invalid_report_path.write_text("{not-json", encoding="utf-8")

    scorecard_zero_db = tmp_path / "scorecard_zero_db.json"
    scorecard_zero_db.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-zero"]},
                    "sources": {
                        "alpha_history_db_path": str(zero_db_path),
                        "bootstrap_report_path": str(valid_report_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    zero_db_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_zero_db.json"
    )
    assert zero_db_contract["source_mode"] == "accepted_after_run_dbs"

    scorecard_db_tmp = tmp_path / "scorecard_db_tmp.json"
    scorecard_db_tmp.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-db-tmp"]},
                    "sources": {
                        "alpha_history_db_path": str(db_in_tmp_path),
                        "bootstrap_report_path": str(valid_report_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    db_tmp_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_db_tmp.json"
    )
    assert db_tmp_contract["source_mode"] == "accepted_after_run_dbs"

    scorecard_report_tmp = tmp_path / "scorecard_report_tmp.json"
    scorecard_report_tmp.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-report-tmp"]},
                    "sources": {
                        "alpha_history_db_path": str(zero_db_path),
                        "bootstrap_report_path": str(report_in_tmp_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report_tmp_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_report_tmp.json"
    )
    assert report_tmp_contract["source_mode"] == "accepted_after_run_dbs"

    scorecard_invalid_report = tmp_path / "scorecard_invalid_report.json"
    scorecard_invalid_report.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-invalid-report"]},
                    "sources": {
                        "alpha_history_db_path": str(zero_db_path),
                        "bootstrap_report_path": str(invalid_report_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    invalid_report_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_invalid_report.json"
    )
    assert invalid_report_contract["source_mode"] == "accepted_after_run_dbs"

    scorecard_missing_run = tmp_path / "scorecard_missing_run.json"
    scorecard_missing_run.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-c"]},
                    "sources": {
                        "alpha_history_db_path": str(zero_db_path),
                        "bootstrap_report_path": str(valid_report_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    missing_run_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_missing_run.json"
    )
    assert missing_run_contract["accepted_run_ids"] == ["run-c"]
    assert "accepted_after_db_missing" in missing_run_contract["reason_codes"]
    assert "accepted_after_db_zero_or_empty" in missing_run_contract["reason_codes"]
    assert "manifest_unreadable" in missing_run_contract["reason_codes"]


def test_exact_source_contract_covers_empty_scorecard_and_report_parse_failures(
    tmp_path,
    monkeypatch,
):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)
    monkeypatch.setattr(module, "TMP_DIR", tmp_path / "tmp")

    (tmp_path / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "analysis").mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "analysis" / (
        "zol0_profitability_audit_strict_bootstrap_manifest.json"
    )
    manifest_path.write_text("{not-json", encoding="utf-8")

    empty_contract = module._resolve_alpha_bootstrap_exact_source_contract("")
    assert empty_contract["active"] is False

    report_in_tmp_db_path = tmp_path / "outside_db_for_tmp_report.db"
    report_in_tmp_db_path.write_bytes(b"db")
    report_in_tmp_path = tmp_path / "tmp" / "report_in_tmp.json"
    report_in_tmp_path.write_text(
        json.dumps({"rows_inserted": 1, "output": str(report_in_tmp_db_path)}),
        encoding="utf-8",
    )
    scorecard_report_tmp = tmp_path / "scorecard_report_tmp_only.json"
    scorecard_report_tmp.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-report-tmp"]},
                    "sources": {
                        "alpha_history_db_path": str(report_in_tmp_db_path),
                        "bootstrap_report_path": str(report_in_tmp_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report_tmp_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_report_tmp_only.json"
    )
    assert report_tmp_contract["source_mode"] == "accepted_after_run_dbs"

    invalid_report_db_path = tmp_path / "outside_db_for_invalid_report.db"
    invalid_report_db_path.write_bytes(b"db")
    invalid_report_path = tmp_path / "invalid_report_only.json"
    invalid_report_path.write_text("{not-json", encoding="utf-8")
    scorecard_invalid_report = tmp_path / "scorecard_invalid_report_only.json"
    scorecard_invalid_report.write_text(
        json.dumps(
            {
                "metadata": {
                    "selection": {"accepted_run_ids": ["run-invalid-report"]},
                    "sources": {
                        "alpha_history_db_path": str(invalid_report_db_path),
                        "bootstrap_report_path": str(invalid_report_path),
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    invalid_report_contract = module._resolve_alpha_bootstrap_exact_source_contract(
        "scorecard_invalid_report_only.json"
    )
    assert invalid_report_contract["source_mode"] == "accepted_after_run_dbs"
