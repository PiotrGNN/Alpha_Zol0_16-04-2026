import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_positive_side_allowlist_contract.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_positive_side_allowlist_contract", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _build_inputs(tmp_path: Path, *, selection_source: str = "accepted_manifest", positive: bool = True):
    manifest_path = tmp_path / "accepted_manifest.json"
    bootstrap_report_path = tmp_path / "alpha_history_report.json"
    scorecard_path = tmp_path / "scorecard.json"
    run_ids = ["20260411_000001"]

    _write_json(
        manifest_path,
        {
            "report_type": "zol0_accepted_corpus_manifest",
            "bundle_validation": {
                "accepted_run_count_matches_scorecard": True,
                "all_source_artifacts_present": True,
                "all_source_artifacts_nonzero": True,
                "all_bundled_hashes_match_source": True,
                "all_bundled_result_after_only": True,
                "all_bundled_result_use_mock_false": True,
                "all_bundled_result_process_ok": True,
            },
            "entries": [{"run_id": run_ids[0]}],
        },
    )
    _write_json(
        bootstrap_report_path,
        {
            "rows_inserted": 12 if positive else 0,
            "pairs_selected": 1 if positive else 0,
            "sources_used": 1,
            "pair_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "trade_count": 12,
                    "winrate": 0.55,
                    "expectancy": 0.002,
                    "selected": True,
                }
            ],
            "pair_side_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "sell",
                    "trade_count": 12,
                    "winrate": 0.55,
                    "expectancy": 0.002,
                    "net_pnl": 0.024,
                }
            ] if positive else [],
        },
    )
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
                    "selection_source": selection_source,
                    "accepted_run_count": 1,
                    "accepted_run_ids": run_ids,
                    "accepted_manifest_path": str(manifest_path),
                },
                "sources": {
                    "accepted_corpus_manifest_path": str(manifest_path),
                    "bootstrap_report_path": str(bootstrap_report_path),
                },
            },
            "global_kpis": {"run_count": 1},
        },
    )
    return scorecard_path


def _rewrite_side_token_inputs(scorecard_path: Path, *, symbol: str, strategy: str, side: str):
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    bootstrap_path = Path(scorecard["metadata"]["sources"]["bootstrap_report_path"])
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap["pair_stats_top"][0]["symbol"] = symbol
    bootstrap["pair_stats_top"][0]["strategy"] = strategy
    bootstrap["pair_side_stats_top"][0]["symbol"] = symbol
    bootstrap["pair_side_stats_top"][0]["strategy"] = strategy
    bootstrap["pair_side_stats_top"][0]["side"] = side
    bootstrap_path.write_text(json.dumps(bootstrap, indent=2), encoding="utf-8")


def _rewrite_bootstrap_selection(scorecard_path: Path, *, selected: bool, pairs_selected: int):
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    bootstrap_path = Path(scorecard["metadata"]["sources"]["bootstrap_report_path"])
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap["pairs_selected"] = pairs_selected
    bootstrap["pair_stats_top"][0]["selected"] = selected
    bootstrap_path.write_text(json.dumps(bootstrap, indent=2), encoding="utf-8")


def test_contract_passes_with_exact_positive_side_evidence(tmp_path):
    module = _load_module()
    scorecard_path = _build_inputs(tmp_path, positive=True)

    contract = module.build_contract(scorecard_path=scorecard_path)

    assert contract["status"] == "PASS"
    assert contract["reason_codes"] == []
    assert contract["positive_side_allowlist"] == [
        "BTCUSDTM:TRENDFOLLOWING:sell"
    ]


def test_contract_fails_closed_without_positive_side_evidence(tmp_path):
    module = _load_module()
    scorecard_path = _build_inputs(tmp_path, positive=False)

    contract = module.build_contract(scorecard_path=scorecard_path)

    assert contract["status"] == "FAIL_CLOSED"
    assert "BOOTSTRAP_ROWS_INSERTED_ZERO" in contract["reason_codes"]
    assert "NO_ELIGIBLE_POSITIVE_SIDE_BUCKETS" in contract["reason_codes"]
    assert contract["positive_side_allowlist"] == []


def test_contract_rejects_results_scan_scorecard(tmp_path):
    module = _load_module()
    scorecard_path = _build_inputs(
        tmp_path,
        selection_source="results_scan",
        positive=True,
    )

    contract = module.build_contract(scorecard_path=scorecard_path)

    assert contract["status"] == "FAIL_CLOSED"
    assert "SCORECARD_SELECTION_SOURCE_ACCEPTED_MANIFEST_FAILED" in contract[
        "reason_codes"
    ]


def test_contract_fails_closed_when_bootstrap_selection_count_mismatches(tmp_path):
    module = _load_module()
    scorecard_path = _build_inputs(tmp_path, positive=True)
    _rewrite_bootstrap_selection(scorecard_path, selected=False, pairs_selected=1)

    contract = module.build_contract(scorecard_path=scorecard_path)

    assert contract["status"] == "FAIL_CLOSED"
    assert "BOOTSTRAP_PAIRS_SELECTED_MISMATCH" in contract["reason_codes"]
    assert contract["positive_side_allowlist"] == []


def test_contract_blocks_cost_burden_side_even_when_historically_positive(tmp_path):
    module = _load_module()
    scorecard_path = _build_inputs(tmp_path, positive=True)
    _rewrite_side_token_inputs(
        scorecard_path,
        symbol="ETHUSDTM",
        strategy="TrendFollowing",
        side="buy",
    )

    contract = module.build_contract(scorecard_path=scorecard_path)

    assert contract["status"] == "FAIL_CLOSED"
    assert "ALL_POSITIVE_SIDE_BUCKETS_BLOCKED" in contract["reason_codes"]
    assert "NO_ELIGIBLE_POSITIVE_SIDE_BUCKETS" in contract["reason_codes"]
    assert contract["blocked_positive_side_allowlist"] == [
        "ETHUSDTM:TRENDFOLLOWING:buy"
    ]
    assert contract["positive_side_allowlist"] == []


def test_main_writes_contract_artifacts_and_exit_codes(tmp_path, capsys):
    module = _load_module()

    positive_scorecard = _build_inputs(tmp_path / "positive", positive=True)
    positive_json = tmp_path / "positive" / "contract.json"
    positive_md = tmp_path / "positive" / "contract.md"

    rc = module.main(
        [
            "--scorecard-path",
            str(positive_scorecard),
            "--output-json",
            str(positive_json),
            "--output-md",
            str(positive_md),
        ]
    )

    assert rc == 0
    positive_stdout = capsys.readouterr().out
    assert "POSITIVE_SIDE_ALLOWLIST_CONTRACT_JSON=" in positive_stdout
    assert "POSITIVE_SIDE_ALLOWLIST_CONTRACT_MD=" in positive_stdout
    assert "POSITIVE_SIDE_ALLOWLIST_CONTRACT status=PASS" in positive_stdout
    assert positive_json.exists()
    assert positive_md.exists()

    positive_contract = json.loads(positive_json.read_text(encoding="utf-8"))
    assert positive_contract["status"] == "PASS"
    assert positive_contract["positive_side_allowlist"] == [
        "BTCUSDTM:TRENDFOLLOWING:sell"
    ]
    assert positive_md.read_text(encoding="utf-8").startswith(
        "# Positive Side Allowlist Contract"
    )

    negative_scorecard = _build_inputs(tmp_path / "negative", positive=False)
    negative_json = tmp_path / "negative" / "contract.json"
    negative_md = tmp_path / "negative" / "contract.md"

    rc_fail = module.main(
        [
            "--scorecard-path",
            str(negative_scorecard),
            "--output-json",
            str(negative_json),
            "--output-md",
            str(negative_md),
        ]
    )

    assert rc_fail == 1
    negative_stdout = capsys.readouterr().out
    assert "POSITIVE_SIDE_ALLOWLIST_CONTRACT status=FAIL_CLOSED" in negative_stdout
    assert negative_json.exists()
    assert negative_md.exists()

    negative_contract = json.loads(negative_json.read_text(encoding="utf-8"))
    assert negative_contract["status"] == "FAIL_CLOSED"
    assert "BOOTSTRAP_ROWS_INSERTED_ZERO" in negative_contract["reason_codes"]
    assert "NO_ELIGIBLE_POSITIVE_SIDE_BUCKETS" in negative_contract["reason_codes"]
