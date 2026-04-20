import importlib.util
import json
import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("controlled_kpi_run", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def controlled_kpi_run_module():
    return _load_module()


def _make_runtime_db(tmp_path):
    db_path = tmp_path / "runtime.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    conn.execute(
        "CREATE TABLE equity (id INTEGER PRIMARY KEY AUTOINCREMENT, equity REAL)"
    )
    conn.execute(
        "CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, event TEXT, details TEXT)"
    )
    return db_path, conn


def _insert_log(conn, event, details, timestamp="2026-04-13T00:00:00Z"):
    conn.execute(
        "INSERT INTO logs(timestamp, event, details) VALUES (?, ?, ?)",
        (timestamp, event, details),
    )


def _build_candles(start_ms, count, *, bad_ohlc_index=None, bad_volume_index=None):
    candles = []
    for index in range(count):
        open_price = 100.0 + index
        high_price = open_price + 1.0
        low_price = open_price - 1.0
        close_price = open_price + 0.5
        volume = 1000.0 + index
        if bad_ohlc_index == index:
            high_price = low_price - 0.5
        if bad_volume_index == index:
            volume = -1.0
        candles.append(
            {
                "timestamp": start_ms + index * 60_000,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            }
        )
    return candles


def _seed_metrics_db(conn):
    for _ in range(2):
        conn.execute("INSERT INTO decisions DEFAULT VALUES")
    for value in (100.0, 120.0, 60.0, 70.0):
        conn.execute("INSERT INTO equity(equity) VALUES (?)", (value,))

    _insert_log(conn, "position_open", json.dumps({"symbol": "BTCUSDTM"}))
    _insert_log(
        conn,
        "position_close",
        json.dumps({"symbol": "BTCUSDTM", "realized_pnl": 3.0}),
    )
    _insert_log(
        conn,
        "position_close",
        json.dumps(
            {
                "position": {
                    "symbol": "ETHUSDTM",
                    "realized_pnl": -1.0,
                }
            }
        ),
    )
    _insert_log(conn, "position_close", "{not-json")
    _insert_log(
        conn,
        "entry_gate_decision_summary",
        json.dumps({"final_allow": True, "local_gate_reason": "insufficient_history"}),
    )
    _insert_log(
        conn,
        "entry_gate_decision_summary",
        json.dumps({"final_allow": False, "local_gate_reason": "weak_signal"}),
    )
    _insert_log(conn, "diagnostic_gate_trace", json.dumps({"step": "one"}))
    _insert_log(conn, "diagnostic_gate_trace", "not-json")
    conn.commit()


def _seed_probe_db(conn):
    rows = [
        (
            "canonical_promotion",
            {
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "runtime_seq": 11,
                "correlation_id": "corr-a",
            },
        ),
        (
            "canonical_explicit_post_promotion_eval_invoked",
            {
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "runtime_seq": 12,
            },
        ),
        (
            "canonical_gate_read",
            {
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "runtime_seq": 13,
            },
        ),
        (
            "canonical_promotion",
            {
                "symbol": "ETHUSDTM",
                "strategy": "Momentum",
                "side": "sell",
                "canonical_key": "ETHUSDTM|MOMENTUM|sell",
                "runtime_seq": 21,
                "correlation_id": "corr-b",
            },
        ),
        (
            "canonical_gate_read",
            {
                "canonical_key": "ETHUSDTM|MOMENTUM|sell",
                "runtime_seq": 22,
                "timing_replay_index": 7,
            },
        ),
        ("position_open", {"symbol": "BTCUSDTM"}),
        ("position_close_request", {"symbol": "BTCUSDTM"}),
        ("position_close_request", {"symbol": "BTCUSDTM"}),
        ("position_close", {"symbol": "BTCUSDTM"}),
        ("position_open", {"symbol": "ETHUSDTM"}),
        (
            "entry_edge_over_fee_eval",
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"},
        ),
        (
            "post_close_summary_pre_assembly",
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"},
        ),
        (
            "post_close_summary_assembly_enter",
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"},
        ),
        (
            "post_close_summary_payload_built",
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"},
        ),
        (
            "post_close_summary_emit_attempt",
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"},
        ),
        (
            "post_close_summary_emit_done",
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"},
        ),
        (
            "entry_gate_decision_summary",
            {"final_allow": True, "local_gate_reason": "insufficient_history"},
        ),
        ("risk_decision", {"allow": True}),
        ("post_promotion_force_cycle_request", {"promotion_runtime_seq": 41}),
        ("forced_cycle_requested", {"promotion_runtime_seq": 41}),
        ("forced_cycle_started", {"promotion_runtime_seq": 41}),
        (
            "forced_cycle_completed",
            {
                "promotion_runtime_seq": 41,
                "forced_cycle_exit_reason": "complete",
                "result_classification": "done",
            },
        ),
        (
            "forced_cycle_failed",
            {
                "promotion_runtime_seq": 41,
                "forced_cycle_exit_reason": "timeout",
                "result_classification": "failed",
            },
        ),
    ]

    for index, (event, payload) in enumerate(rows, start=1):
        _insert_log(
            conn,
            event,
            json.dumps(payload),
            timestamp=f"2026-04-13T00:00:{index:02d}Z",
        )
    conn.commit()


def test_base_env_and_variant_env_contracts(controlled_kpi_run_module, tmp_path):
    module = controlled_kpi_run_module
    db_path = tmp_path / "controlled_kpi.db"

    base_env = module._base_env(
        db_path,
        use_mock=True,
        market_type="futures",
        run_symbols="BTCUSDTM,ETHUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=45,
        equity_snapshot_sec=15,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="analysis/*.json",
    )

    assert base_env["LIVE"] == "0"
    assert base_env["USE_MOCK"] == "1"
    assert base_env["ZOL0_TOKEN"] == "controlled_kpi_runner"
    assert base_env["DATABASE_URL"] == f"sqlite:///{db_path.as_posix()}"
    assert base_env["MARKET_TYPE"] == "futures"
    assert base_env["RUN_SYMBOLS"] == "BTCUSDTM,ETHUSDTM"
    assert base_env["PAPER_AUTO_OPEN"] == "1"
    assert base_env["PAPER_AUTO_CLOSE_SEC"] == "45"
    assert base_env["EQUITY_SNAPSHOT_SEC"] == "15"
    assert base_env["ALPHA_BOOTSTRAP_SOURCE_DB_URL"] == "sqlite:///source.db"
    assert base_env["ALPHA_BOOTSTRAP_SOURCE_DB_GLOB"] == "analysis/*.json"
    assert base_env["DATA_QUALITY_GUARD"] == "1"
    assert base_env["STRATEGY_GUARD_ENABLE"] == "1"
    assert base_env["PAPER_GATE_ENABLE"] == "1"
    assert base_env["WF_CALIBRATION_MIN_PCT_MEET"] == "0.55"
    assert "PAPER_RUN_ONCE" not in base_env

    no_source_env = module._base_env(
        db_path,
        use_mock=False,
        market_type="spot",
        run_symbols="BTCUSDTM",
        paper_auto_open=False,
        paper_auto_close_sec=20,
        equity_snapshot_sec=5,
        quality_profile=False,
        alpha_bootstrap_source_db_url="",
        alpha_bootstrap_source_db_glob="",
    )

    assert no_source_env["USE_MOCK"] == "0"
    assert no_source_env["PAPER_AUTO_OPEN"] == "0"
    assert no_source_env["MARKET_TYPE"] == "spot"
    assert "ALPHA_BOOTSTRAP_SOURCE_DB_URL" not in no_source_env
    assert "ALPHA_BOOTSTRAP_SOURCE_DB_GLOB" not in no_source_env
    assert "DATA_QUALITY_GUARD" not in no_source_env

    before_env = module._variant_env(
        db_path,
        "before",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=False,
        paper_auto_close_sec=30,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="analysis/*.json",
        variant_overrides={
            "ENTRY_FILTER_STRICT": 9,
            "CUSTOM_OVERRIDE": 42,
            "": "ignored",
        },
    )
    assert before_env["ENTRY_FILTER_STRICT"] == "9"
    assert before_env["ENTRY_IGNORE_HOLD_SIGNALS"] == "0"
    assert before_env["ENTRY_MIN_ACTIVE_STRATEGIES"] == "1"
    assert before_env["PAPER_AUTO_OPEN_STARTUP_ENABLE"] == "0"
    assert before_env["MAX_OPEN_POSITIONS"] == "1"
    assert before_env["allocation_pct"] == "0.010"
    assert before_env["ENTRY_MIN_NET_USDT"] == "0.12"
    assert before_env["ENTRY_MIN_NET_TO_STOP_RATIO"] == "1.10"
    assert before_env["CONTROLLED_KPI_EXPLICIT_POST_PROMOTION_EVAL_REQUEST"] == "1"
    assert before_env["RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL"] == "1"
    assert before_env["RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS"] == "1"
    assert before_env["CUSTOM_OVERRIDE"] == "42"

    after_env = module._variant_env(
        db_path,
        "after",
        use_mock=True,
        market_type="futures",
        run_symbols="BTCUSDTM,ETHUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=30,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="analysis/*.json",
        variant_overrides={"ENTRY_FILTER_STRICT": 7, "ANOTHER_OVERRIDE": "value"},
    )
    assert after_env["ENTRY_FILTER_STRICT"] == "7"
    assert after_env["ENTRY_IGNORE_HOLD_SIGNALS"] == "0"
    assert after_env["SEED_TRADES_ENABLE"] == "0"
    assert after_env["PAPER_AUTO_OPEN_STARTUP_ENABLE"] == "0"
    assert after_env["PAPER_AUTO_OPEN_FALLBACK_ENABLE"] == "0"
    assert after_env["PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST"] == "1"
    assert after_env["ALPHA_BOOTSTRAP_REQUIRE_EXTERNAL_SOURCE"] == "1"
    assert after_env["PAPER_AUTO_CLOSE_POLICY"] == "profit_or_hard"
    assert after_env["ALPHA_WHITELIST_ENABLE"] == "1"
    assert after_env["PAPER_GATE_ENABLE"] == "0"
    assert after_env["ENTRY_TRENDFOLLOWING_FILTER_ENABLE"] == "0"
    assert after_env["ENTRY_SIDE_EXPECTANCY_MIN"] == "-1.0"
    assert after_env["PAPER_POST_GREEN_GIVEBACK_TRIGGER"] == "0.08"
    assert after_env["RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS"] == "1"
    assert after_env["ANOTHER_OVERRIDE"] == "value"


def test_runtime_helper_contracts(controlled_kpi_run_module, monkeypatch, tmp_path):
    module = controlled_kpi_run_module

    assert module._compute_max_drawdown([]) == 0.0
    assert module._compute_max_drawdown([100.0, 120.0, 60.0, 70.0]) == pytest.approx(
        0.5
    )
    assert module._controlled_entry_cutoff_sec(60, 10) == 15
    assert module._controlled_entry_cutoff_sec(120, 10) == 20
    assert module._controlled_entry_cutoff_sec("bad", "bad") == 10

    missing_analysis = module._analyze_process_logs(
        tmp_path / "missing_out.log",
        tmp_path / "missing_err.log",
    )
    assert missing_analysis == {
        "error_count": 0,
        "warning_count": 0,
        "sample_errors": [],
    }

    out_log = tmp_path / "out.log"
    out_log.write_text(
        "\n".join(
            ["warning: first"]
            + [f"traceback failure {index}" for index in range(22)]
            + ["critical failure"]
        ),
        encoding="utf-8",
    )
    err_dir = tmp_path / "err_dir"
    err_dir.mkdir()
    analysis = module._analyze_process_logs(out_log, err_dir)
    assert analysis["error_count"] == 23
    assert analysis["warning_count"] == 1
    assert len(analysis["sample_errors"]) == 20
    assert analysis["sample_errors"][0] == "traceback failure 0"
    assert analysis["sample_errors"][-1] == "traceback failure 19"

    metrics_line = module._format_metrics_line(
        "paper",
        {
            "trade_count": 3,
            "net_pnl": 1.5,
            "winrate": 0.5,
            "max_drawdown": 0.25,
            "profit_factor": float("inf"),
            "decisions_count": 2,
            "equity_points": 4,
            "log_health": {"error_count": 7},
        },
    )
    assert "paper: trades=3" in metrics_line
    assert "net_pnl=1.500000" in metrics_line
    assert "winrate=50.00%" in metrics_line
    assert "max_dd=25.00%" in metrics_line
    assert "profit_factor=inf" in metrics_line
    assert "decisions=2" in metrics_line
    assert "equity_points=4" in metrics_line
    assert "log_errors=7" in metrics_line

    assert (
        module._block_mock_ohlcv_kucoin_paper_startup(
            use_mock=False,
            market_type="futures",
            symbols=["BTCUSDTM"],
            timeframe="1m",
        )
        is None
    )
    with pytest.raises(SystemExit) as excinfo:
        module._block_mock_ohlcv_kucoin_paper_startup(
            use_mock=True,
            market_type="futures",
            symbols=["BTCUSDTM"],
            timeframe="1m",
        )
    message = str(excinfo.value)
    assert "MOCK_OHLCV_BLOCKED_KUCOIN_PAPER" in message
    assert "market_type=futures" in message
    assert "symbol=BTCUSDTM" in message
    assert "interval=1m" in message

    assert (
        module._canonical_bucket_from_payload(
            {"canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy"}
        )
        == "BTCUSDTM|TRENDFOLLOWING|buy"
    )
    canonical_payload = {
        "symbol": "BTCUSDTM",
        "side": "buy",
        "position": {"entry_main_strategy": "TrendFollowing"},
    }
    assert module._canonical_bucket_from_payload(canonical_payload) == (
        "BTCUSDTM|TRENDFOLLOWING|buy"
    )

    import scripts.canonical_edge_history_linkage as linkage

    monkeypatch.setattr(
        linkage,
        "build_canonical_bucket_key",
        lambda payload: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert module._canonical_bucket_from_payload(canonical_payload) is None
    assert module._canonical_bucket_from_payload(None) is None


def test_collect_metrics_emits_profitability_exit_timing_fields(
    controlled_kpi_run_module,
    tmp_path,
):
    module = controlled_kpi_run_module
    db_path, conn = _make_runtime_db(tmp_path)
    conn.execute("INSERT INTO decisions DEFAULT VALUES")
    conn.execute("INSERT INTO decisions DEFAULT VALUES")
    conn.execute("INSERT INTO equity(equity) VALUES (100.0)")
    conn.execute("INSERT INTO equity(equity) VALUES (101.0)")
    conn.execute("INSERT INTO equity(equity) VALUES (99.0)")

    _insert_log(
        conn,
        "position_close",
        json.dumps(
            {
                "symbol": "BTCUSDTM",
                "position": {
                    "symbol": "BTCUSDTM",
                    "timestamp": "2026-04-13T00:00:00+00:00",
                    "first_positive_mfe_ts": "2026-04-13T00:00:05+00:00",
                    "peak_mfe_ts": "2026-04-13T00:00:08+00:00",
                    "close_timestamp": "2026-04-13T00:00:10+00:00",
                    "realized_net": 2.0,
                    "mfe": 4.0,
                    "exit_reason": "post_green_protective_exit",
                    "pnl_decompose": {"gross_fill_pnl_model": 3.0},
                },
            }
        ),
        timestamp="2026-04-13T00:00:10+00:00",
    )
    _insert_log(
        conn,
        "position_close",
        json.dumps(
            {
                "symbol": "ETHUSDTM",
                "position": {
                    "symbol": "ETHUSDTM",
                    "timestamp": "2026-04-13T00:01:00+00:00",
                    "first_positive_mfe_ts": "2026-04-13T00:01:04+00:00",
                    "max_unrealized_pnl_ts": "2026-04-13T00:01:05+00:00",
                    "close_timestamp": "2026-04-13T00:01:10+00:00",
                    "realized_net": -1.0,
                    "max_unrealized_pnl": 0.8,
                    "close_reason": "auto_close_hard",
                    "pnl_decompose": {"gross_fill_pnl_model": 0.5},
                },
            }
        ),
        timestamp="2026-04-13T00:01:10+00:00",
    )
    conn.commit()
    conn.close()

    metrics = module._collect_metrics(db_path)

    assert metrics["trade_count"] == 2
    assert metrics["net_pnl"] == pytest.approx(1.0)
    assert metrics["profit_factor"] == pytest.approx(2.0)
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["winrate"] == pytest.approx(0.5)
    assert metrics["avg_win"] == pytest.approx(2.0)
    assert metrics["avg_loss"] == pytest.approx(-1.0)
    assert metrics["expectancy"] == pytest.approx(0.5)
    assert metrics["green_to_red_share"] == pytest.approx(0.5)
    assert metrics["fee_inversion_share"] == pytest.approx(0.5)
    assert metrics["share_ever_profitable"] == pytest.approx(1.0)
    assert metrics["exit_reason_distribution"] == {
        "auto_close_hard": 1,
        "post_green_protective_exit": 1,
    }
    assert metrics["time_to_first_MFE"] == pytest.approx(4.5)
    assert metrics["time_to_first_MFE_median"] == pytest.approx(4.5)
    assert metrics["time_to_first_MFE_count"] == 2
    assert metrics["time_from_peak_to_close"] == pytest.approx(3.5)
    assert metrics["time_from_peak_to_close_median"] == pytest.approx(3.5)
    assert metrics["time_from_peak_to_close_count"] == 2


def test_data_integrity_and_refresh_history_contracts(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module

    assert module._run_data_integrity_checks(["BTCUSDTM"], "futures", True, "1m") == {
        "skipped": True,
        "reason": "USE_MOCK=1",
        "symbols": ["BTCUSDTM"],
        "results": {},
    }

    now_ms = int(time.time() * 1000)

    class FakeMarketDataFetcher:
        init_market_types = []

        def __init__(self, market_type):
            self.market_type = market_type
            self.init_market_types.append(market_type)

        def get_ohlcv(self, symbol, timeframe, limit=120):
            if symbol == "BTCUSDTM":
                return _build_candles(now_ms - 59 * 60_000, 60)
            if symbol == "ETHUSDTM":
                return _build_candles(
                    now_ms - 59 * 60_000,
                    60,
                    bad_ohlc_index=10,
                    bad_volume_index=11,
                )
            raise RuntimeError("boom")

    fake_market_module = types.ModuleType("core.MarketDataFetcher")
    fake_market_module.MarketDataFetcher = FakeMarketDataFetcher
    monkeypatch.setitem(sys.modules, "core.MarketDataFetcher", fake_market_module)

    integrity = module._run_data_integrity_checks(
        ["BTCUSDTM", "ETHUSDTM", "XRPUSDTM"],
        "futures",
        False,
        "1m",
    )
    assert integrity["skipped"] is False
    assert integrity["market_type"] == "futures"
    assert integrity["timeframe"] == "1m"
    assert FakeMarketDataFetcher.init_market_types == ["futures"]

    btc = integrity["results"]["BTCUSDTM"]
    eth = integrity["results"]["ETHUSDTM"]
    xrp = integrity["results"]["XRPUSDTM"]

    assert btc["ok"] is True
    assert btc["count"] == 60
    assert btc["monotonic_ts"] is True
    assert btc["unique_ts_ratio"] == pytest.approx(1.0)
    assert btc["bad_ohlc_count"] == 0
    assert btc["bad_volume_count"] == 0

    assert eth["ok"] is False
    assert eth["count"] == 60
    assert eth["bad_ohlc_count"] >= 1
    assert eth["bad_volume_count"] >= 1

    assert xrp == {"ok": False, "error": "boom", "count": 0}

    assert module._refresh_alpha_bootstrap_history(
        enabled=False,
        output_rel="artifacts/bootstrap.db",
        glob_patterns="analysis/*.json",
        max_sources=1,
        max_per_source=1,
        max_total=1,
        min_abs_pnl=0.0,
        min_pair_trades=1,
        min_pair_winrate=0.0,
        min_pair_expectancy=0.0,
        fallback_top_pairs=1,
        report_json_rel="artifacts/bootstrap_report.json",
    ) == {
        "enabled": False,
        "ran": False,
        "success": False,
    }

    assert module._refresh_alpha_bootstrap_history(
        enabled=True,
        output_rel="",
        glob_patterns="",
        max_sources=1,
        max_per_source=1,
        max_total=1,
        min_abs_pnl=0.0,
        min_pair_trades=1,
        min_pair_winrate=0.0,
        min_pair_expectancy=0.0,
        fallback_top_pairs=1,
        report_json_rel="",
    ) == {
        "enabled": True,
        "ran": False,
        "success": False,
        "error": "missing_output_or_glob",
    }

    calls = []

    def fake_run(
        cmd,
        cwd=None,
        env=None,
        capture_output=False,
        text=False,
        check=False,
    ):
        calls.append(
            {
                "cmd": cmd,
                "cwd": cwd,
                "env": env,
                "capture_output": capture_output,
                "text": text,
                "check": check,
            }
        )
        if cmd[1] == "-c":
            assert env is not None
            expected_database_url = f"sqlite:///{(tmp_path / 'schema.db').as_posix()}"
            assert env["DATABASE_URL"] == expected_database_url
            return types.SimpleNamespace(returncode=0, stdout="init ok\n", stderr="")

        output_index = cmd.index("--output") + 1
        report_index = cmd.index("--report-json") + 1
        out_path = tmp_path / cmd[output_index]
        report_path = tmp_path / cmd[report_index]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("db-bytes", encoding="utf-8")
        report_path.write_text(
            json.dumps({"rows_inserted": 3, "output": str(out_path)}),
            encoding="utf-8",
        )
        return types.SimpleNamespace(
            returncode=0,
            stdout="first\nsecond\n",
            stderr="warn\ntrace\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    schema_db_path = tmp_path / "schema.db"
    module._init_db_schema(schema_db_path)

    refresh = module._refresh_alpha_bootstrap_history(
        enabled=True,
        output_rel="artifacts/bootstrap.db",
        glob_patterns="analysis/*.json",
        max_sources=2,
        max_per_source=2,
        max_total=5,
        min_abs_pnl=0.0,
        min_pair_trades=1,
        min_pair_winrate=0.0,
        min_pair_expectancy=0.0,
        fallback_top_pairs=1,
        report_json_rel="artifacts/bootstrap_report.json",
    )

    assert len(calls) == 2
    assert refresh["enabled"] is True
    assert refresh["ran"] is True
    assert refresh["success"] is True
    assert refresh["returncode"] == 0
    assert refresh["output_exists"] is True
    assert Path(refresh["output_path"]) == tmp_path / "artifacts" / "bootstrap.db"
    assert refresh["report_path"] == str(
        tmp_path / "artifacts" / "bootstrap_report.json"
    )
    assert refresh["report"]["rows_inserted"] == 3
    assert refresh["stdout_tail"] == "first\nsecond"
    assert refresh["stderr_tail"] == "warn\ntrace"
    assert calls[0]["cmd"][1] == "-c"
    assert calls[1]["capture_output"] is True
    assert calls[1]["text"] is True
    assert calls[1]["check"] is False


def test_collect_metrics_and_log_reader_contracts(
    controlled_kpi_run_module,
    tmp_path,
):
    module = controlled_kpi_run_module

    missing_db = tmp_path / "missing.db"
    assert module._collect_metrics(missing_db) == {
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
    assert module._load_entry_gate_summary_payloads(missing_db) == []
    assert module._load_diagnostic_trace_rows(missing_db) == []

    db_path, conn = _make_runtime_db(tmp_path)
    try:
        _seed_metrics_db(conn)
    finally:
        conn.close()

    metrics = module._collect_metrics(db_path)
    assert metrics["db_exists"] is True
    assert metrics["trade_count"] == 2
    assert metrics["net_pnl"] == 2.0
    assert metrics["winrate"] == 0.5
    assert metrics["max_drawdown"] == pytest.approx(0.5)
    assert metrics["profit_factor"] == 3.0
    assert metrics["gross_profit"] == 3.0
    assert metrics["gross_loss_abs"] == 1.0
    assert metrics["decisions_count"] == 2
    assert metrics["equity_points"] == 4
    assert metrics["event_counts"]["position_open"] == 1
    assert metrics["event_counts"]["position_close"] == 3
    assert metrics["event_counts"]["entry_gate_decision_summary"] == 2
    assert metrics["event_counts"]["diagnostic_gate_trace"] == 2
    assert metrics["symbol_stats"]["BTCUSDTM"]["trade_count"] == 1
    assert metrics["symbol_stats"]["BTCUSDTM"]["profit_factor"] == float("inf")
    assert metrics["symbol_stats"]["ETHUSDTM"]["net_pnl"] == -1.0

    entry_payloads = module._load_entry_gate_summary_payloads(db_path)
    assert len(entry_payloads) == 2
    assert entry_payloads[0]["payload"]["final_allow"] is True
    assert entry_payloads[1]["payload"]["local_gate_reason"] == "weak_signal"

    trace_rows = module._load_diagnostic_trace_rows(db_path)
    assert len(trace_rows) == 2
    assert trace_rows[0]["payload"]["step"] == "one"
    assert trace_rows[1]["payload"] == {}


def test_close_drain_and_probe_contracts(controlled_kpi_run_module, tmp_path):
    module = controlled_kpi_run_module
    missing_db = tmp_path / "missing.db"

    assert module._close_drain_snapshot(missing_db) is None
    assert module._pending_open_positions(missing_db) is None
    assert module._pending_open_symbols(missing_db) is None
    assert module._probe_latest_canonical_promotion(missing_db) is None
    assert module._probe_real_post_promotion_reevaluation(missing_db) == {
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
    assert module._probe_forced_post_promotion_cycle(missing_db) == {
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
    assert module._probe_post_close_summary_grace(missing_db) == {
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

    db_path, conn = _make_runtime_db(tmp_path)
    try:
        _seed_probe_db(conn)
    finally:
        conn.close()

    latest = module._probe_latest_canonical_promotion(db_path)
    assert latest == {
        "symbol": "ETHUSDTM",
        "strategy": "Momentum",
        "side": "sell",
        "canonical_key": "ETHUSDTM|MOMENTUM|sell",
        "correlation_id": "corr-b",
        "promotion_runtime_seq": 21,
        "promotion_row_id": 4,
        "promotion_ts": "2026-04-13T00:00:04Z",
    }

    reeval = module._probe_real_post_promotion_reevaluation(db_path)
    assert reeval["promotion_count"] == 2
    assert reeval["promoted_buckets"] == [
        "BTCUSDTM|TRENDFOLLOWING|buy",
        "ETHUSDTM|MOMENTUM|sell",
    ]
    assert reeval["promotion_runtime_seq"] == 11
    assert reeval["reeval_runtime_seq"] == 12
    assert reeval["real_post_promotion_read_count"] == 1
    assert reeval["real_post_promotion_read_buckets"] == [
        "BTCUSDTM|TRENDFOLLOWING|buy",
    ]
    assert reeval["gate_read_after_promotion_runtime_seq"] == 13
    assert reeval["timing_replay_only_buckets"] == ["ETHUSDTM|MOMENTUM|sell"]
    assert reeval["observed_real_post_promotion_read"] is True

    snapshot = module._close_drain_snapshot(db_path)
    assert snapshot == {
        "position_open_count": 2,
        "position_close_request_count": 1,
        "position_close_request_count_raw": 2,
        "position_close_count": 1,
        "pending_positions": 1,
        "close_request_backlog": 0,
        "close_request_backlog_raw": 1,
        "duplicate_close_request_count": 1,
        "pending_position_symbols": ["ETHUSDTM"],
        "effective_close_request_symbols": ["BTCUSDTM"],
        "duplicate_close_request_symbols": ["BTCUSDTM"],
        "progress_complete": False,
    }
    assert module._pending_open_positions(db_path) == 1
    assert module._pending_open_symbols(db_path) == ["ETHUSDTM"]

    grace = module._probe_post_close_summary_grace(db_path)
    assert grace["post_close_boundary_rowid"] == 8
    assert grace["entry_edge_over_fee_eval_count"] == 1
    assert grace["post_close_summary_pre_assembly_count"] == 1
    assert grace["post_close_summary_assembly_enter_count"] == 1
    assert grace["post_close_summary_payload_built_count"] == 1
    assert grace["post_close_summary_emit_attempt_count"] == 1
    assert grace["post_close_summary_emit_done_count"] == 1
    assert grace["entry_gate_decision_summary_count"] == 1
    assert grace["risk_decision_count"] == 1
    assert grace["observed_post_close_eval"] is True
    assert grace["observed_post_close_summary_complete"] is True
    assert grace["observed_post_close_summary_emit_done"] is True
    assert grace["observed_post_close_risk_decision_parity"] is True

    cycle = module._probe_forced_post_promotion_cycle(db_path)
    assert cycle["requested"] is True
    assert cycle["started"] is True
    assert cycle["completed"] is True
    assert cycle["failed"] is True
    assert cycle["promotion_runtime_seq"] == 41
    assert cycle["forced_cycle_request_runtime_seq"] == 20
    assert cycle["forced_cycle_runtime_seq"] == 23
    assert cycle["forced_cycle_exit_reason"] == "timeout"
    assert cycle["forced_cycle_result_classification"] == "failed"


def test_run_variant_immediate_exit_assembles_metrics(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "0",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "1",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "1",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 4321
        returncode = 0

        def poll(self):
            return 0

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 0

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 0,
        }

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
        }

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "before",
        5,
        "run-1",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=False,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=False,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={"FOO": "1"},
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "before"
    assert variant_env_calls[0]["kwargs"]["variant_overrides"] == {"FOO": "1"}
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) == 1
    assert len(close_snapshot_calls) == 2
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "before"
    assert result["process_returncode"] == 0
    assert result["process_returncode_raw"] == 0
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_defers_and_releases_close_requests(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    probe_calls = []
    pending_symbol_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "2",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "2",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 4321
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 0

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    probe_results = [
        {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        },
        {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        },
        {
            "promotion_count": 1,
            "observed_real_post_promotion_read": True,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        },
    ]

    def fake_probe_real_post_promotion_reevaluation(db_path):
        probe_calls.append(db_path)
        if probe_results:
            return probe_results.pop(0)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": True,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        }

    def fake_pending_open_symbols(db_path):
        pending_symbol_calls.append(db_path)
        return []

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
        }

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "after",
        0,
        "run-2",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM,ETHUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) == 4
    assert len(probe_calls) >= 2
    assert len(pending_symbol_calls) == 1
    assert len(enqueue_close_calls) == 1, enqueue_close_calls
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_promotion_window_armed"] is True
    assert result["post_promotion_window_exit_reason"] == (
        "first_post_promotion_gate_read_observed"
    )
    assert result["post_promotion_reeval_result"] == "gate_read_observed"
    assert result["post_promotion_reeval_exit_reason"] == (
        "first_post_promotion_gate_read_observed"
    )
    assert result["process_returncode"] == 0
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_post_promotion_reevaluation_forced_cycle_handoff_requests_once(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    reeval_probe_calls = []
    latest_promotion_calls = []
    reeval_request_calls = []
    forced_cycle_probe_calls = []
    forced_cycle_request_calls = []
    pending_symbol_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "100",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "3",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 5432
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 1

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    def fake_probe_real_post_promotion_reevaluation(db_path):
        reeval_probe_calls.append(db_path)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": 77,
            "real_post_promotion_read_count": 0,
            "real_post_promotion_read_buckets": [],
            "timing_replay_only_buckets": [],
            "promoted_buckets": ["BTCUSDTM|TRENDFOLLOWING|buy"],
        }

    def fake_probe_latest_canonical_promotion(db_path):
        latest_promotion_calls.append(db_path)
        return {
            "symbol": "BTCUSDTM",
            "strategy": "TRENDFOLLOWING",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "correlation_id": "corr-1",
            "promotion_runtime_seq": 11,
            "promotion_row_id": 8,
            "promotion_ts": "2026-04-14T00:00:00Z",
        }

    def fake_enqueue_post_promotion_reeval_request(db_path, request_payload, diag_cb):
        reeval_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return 101

    forced_cycle_probe_completed = {
        "requested": True,
        "started": True,
        "completed": True,
        "failed": False,
        "promotion_runtime_seq": 11,
        "forced_cycle_request_runtime_seq": 202,
        "forced_cycle_runtime_seq": 203,
        "forced_cycle_exit_reason": "forced_cycle_completed",
        "forced_cycle_result_classification": "forced_cycle_completed",
    }
    forced_cycle_probe_results = [
        {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
            "promotion_runtime_seq": None,
            "forced_cycle_request_runtime_seq": None,
            "forced_cycle_runtime_seq": None,
            "forced_cycle_exit_reason": None,
            "forced_cycle_result_classification": None,
        },
        forced_cycle_probe_completed,
    ]

    def fake_probe_forced_post_promotion_cycle(db_path):
        forced_cycle_probe_calls.append(db_path)
        if forced_cycle_probe_results:
            return forced_cycle_probe_results.pop(0)
        return forced_cycle_probe_completed

    def fake_enqueue_post_promotion_force_cycle_request(
        db_path,
        request_payload,
        diag_cb,
    ):
        forced_cycle_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return 202

    def fake_pending_open_symbols(db_path):
        pending_symbol_calls.append(db_path)
        return ["BTCUSDTM"]

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    real_finalize_post_promotion_forced_cycle_trigger_contract = (
        module._finalize_post_promotion_forced_cycle_trigger_contract
    )

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return real_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs)

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(
        module,
        "_probe_latest_canonical_promotion",
        fake_probe_latest_canonical_promotion,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_reeval_request",
        fake_enqueue_post_promotion_reeval_request,
    )
    monkeypatch.setattr(
        module,
        "_probe_forced_post_promotion_cycle",
        fake_probe_forced_post_promotion_cycle,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_force_cycle_request",
        fake_enqueue_post_promotion_force_cycle_request,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "after",
        0,
        "run-5",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) >= 2
    assert len(reeval_probe_calls) >= 1
    assert len(latest_promotion_calls) == 2
    assert len(reeval_request_calls) == 1
    assert reeval_request_calls[0]["request_payload"]["request_reason"] == (
        "post_promotion_bounded_reeval"
    )
    assert len(forced_cycle_probe_calls) >= 2
    assert len(forced_cycle_request_calls) == 1
    assert forced_cycle_request_calls[0]["request_payload"]["request_reason"] == (
        "post_promotion_forced_cycle"
    )
    assert len(enqueue_close_calls) >= 1
    assert any(
        call["reason"] == "controlled_kpi_window_end"
        for call in enqueue_close_calls
    )
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_promotion_window_armed"] is True
    assert result["post_promotion_reeval_requested"] is True
    assert result["post_promotion_reeval_dispatch_entered"] is True
    assert result["post_promotion_window_exit_reason"] == "forced_cycle_completed"
    assert result["post_promotion_reeval_result"] == "forced_cycle_completed"
    assert result["post_promotion_reeval_exit_reason"] == "forced_cycle_completed"
    assert result["post_promotion_forced_cycle_trigger_mode"] == (
        "after_reeval_completed"
    )
    assert result["post_promotion_forced_cycle_request_reason"] == (
        "post_promotion_forced_cycle"
    )
    forced_cycle_contract = result["post_promotion_forced_cycle_trigger_contract"]
    assert forced_cycle_contract["active"] is True
    assert forced_cycle_contract["expected_mode"] == "after_reeval_completed"
    assert forced_cycle_contract["expected_request_reason"] == (
        "post_promotion_forced_cycle"
    )
    assert forced_cycle_contract["observed_mode"] == "after_reeval_completed"
    assert forced_cycle_contract["observed_request_reason"] == (
        "post_promotion_forced_cycle"
    )
    assert forced_cycle_contract["ok"] is True
    assert forced_cycle_contract["status"] == "ok"
    runner_events = [record["event"] for record in result["runner_diagnostics"]]
    assert runner_events.count("post_promotion_window_enter") == 1
    assert runner_events.count("post_promotion_reeval_dispatch_enter") == 1
    assert runner_events.count("forced_cycle_requested") == 1
    assert runner_events.count("forced_cycle_completed") == 1
    assert result["process_returncode"] == 0
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_post_promotion_forced_cycle_execution_lock_defers_shutdown_until_completion(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    reeval_probe_calls = []
    latest_promotion_calls = []
    reeval_request_calls = []
    forced_cycle_probe_calls = []
    forced_cycle_request_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "100",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "3",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 6543
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 1

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    def fake_probe_real_post_promotion_reevaluation(db_path):
        reeval_probe_calls.append(db_path)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": 77,
            "real_post_promotion_read_count": 0,
            "real_post_promotion_read_buckets": [],
            "timing_replay_only_buckets": [],
            "promoted_buckets": ["BTCUSDTM|TRENDFOLLOWING|buy"],
        }

    def fake_probe_latest_canonical_promotion(db_path):
        latest_promotion_calls.append(db_path)
        return {
            "symbol": "BTCUSDTM",
            "strategy": "TRENDFOLLOWING",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "correlation_id": "corr-1",
            "promotion_runtime_seq": 11,
            "promotion_row_id": 8,
            "promotion_ts": "2026-04-14T00:00:00Z",
        }

    def fake_enqueue_post_promotion_reeval_request(db_path, request_payload, diag_cb):
        reeval_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return 101

    forced_cycle_probe_results = [
        {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
            "promotion_runtime_seq": 11,
            "forced_cycle_request_runtime_seq": None,
            "forced_cycle_runtime_seq": None,
            "forced_cycle_exit_reason": None,
            "forced_cycle_result_classification": None,
        },
        {
            "requested": True,
            "started": True,
            "completed": False,
            "failed": False,
            "promotion_runtime_seq": 11,
            "forced_cycle_request_runtime_seq": 202,
            "forced_cycle_runtime_seq": 203,
            "forced_cycle_exit_reason": None,
            "forced_cycle_result_classification": None,
        },
        {
            "requested": True,
            "started": False,
            "completed": True,
            "failed": False,
            "promotion_runtime_seq": 11,
            "forced_cycle_request_runtime_seq": 202,
            "forced_cycle_runtime_seq": 204,
            "forced_cycle_exit_reason": "forced_cycle_completed",
            "forced_cycle_result_classification": "forced_cycle_completed",
        },
    ]

    def fake_probe_forced_post_promotion_cycle(db_path):
        forced_cycle_probe_calls.append(db_path)
        if forced_cycle_probe_results:
            return forced_cycle_probe_results.pop(0)
        return {
            "requested": True,
            "started": False,
            "completed": True,
            "failed": False,
            "promotion_runtime_seq": 11,
            "forced_cycle_request_runtime_seq": 202,
            "forced_cycle_runtime_seq": 204,
            "forced_cycle_exit_reason": "forced_cycle_completed",
            "forced_cycle_result_classification": "forced_cycle_completed",
        }

    def fake_enqueue_post_promotion_force_cycle_request(
        db_path,
        request_payload,
        diag_cb,
    ):
        forced_cycle_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return 202

    def fake_pending_open_symbols(db_path):
        return []

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    real_finalize_post_promotion_forced_cycle_trigger_contract = (
        module._finalize_post_promotion_forced_cycle_trigger_contract
    )

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return real_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs)

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(
        module,
        "_probe_latest_canonical_promotion",
        fake_probe_latest_canonical_promotion,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_reeval_request",
        fake_enqueue_post_promotion_reeval_request,
    )
    monkeypatch.setattr(
        module,
        "_probe_forced_post_promotion_cycle",
        fake_probe_forced_post_promotion_cycle,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_force_cycle_request",
        fake_enqueue_post_promotion_force_cycle_request,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "after",
        0,
        "run-lock",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) >= 2
    assert len(reeval_probe_calls) >= 1
    assert len(latest_promotion_calls) >= 1
    assert len(reeval_request_calls) == 1
    assert len(forced_cycle_probe_calls) >= 3
    assert len(forced_cycle_request_calls) == 1
    assert any(
        record["event"] == "runner_shutdown_deferred"
        and record.get("deferred_reason") == "post_promotion_execution_lock_active"
        for record in result["runner_diagnostics"]
    )
    assert any(record["event"] == "forced_cycle_started" for record in result["runner_diagnostics"])
    assert any(record["event"] == "forced_cycle_completed" for record in result["runner_diagnostics"])
    assert len(enqueue_close_calls) >= 1
    assert any(
        call["reason"] == "controlled_kpi_window_end"
        for call in enqueue_close_calls
    )
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_promotion_window_armed"] is True
    assert result["post_promotion_reeval_requested"] is True
    assert result["post_promotion_reeval_dispatch_entered"] is True
    assert result["post_promotion_window_exit_reason"] == "forced_cycle_completed"
    assert result["post_promotion_reeval_result"] == "forced_cycle_completed"
    assert result["post_promotion_reeval_exit_reason"] == "forced_cycle_completed"
    assert result["post_promotion_forced_cycle_trigger_mode"] == (
        "after_reeval_completed"
    )
    assert result["post_promotion_forced_cycle_request_reason"] == (
        "post_promotion_forced_cycle"
    )
    forced_cycle_contract = result["post_promotion_forced_cycle_trigger_contract"]
    assert forced_cycle_contract["active"] is True
    assert forced_cycle_contract["ok"] is True
    assert forced_cycle_contract["status"] == "ok"
    assert result["process_returncode"] == 0
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_post_promotion_forced_cycle_enqueue_failure_reports_failed_exit(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    reeval_probe_calls = []
    latest_promotion_calls = []
    reeval_request_calls = []
    forced_cycle_probe_calls = []
    forced_cycle_request_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "100",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "3",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 7654
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 1

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    def fake_probe_real_post_promotion_reevaluation(db_path):
        reeval_probe_calls.append(db_path)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": 77,
            "real_post_promotion_read_count": 0,
            "real_post_promotion_read_buckets": [],
            "timing_replay_only_buckets": [],
            "promoted_buckets": ["BTCUSDTM|TRENDFOLLOWING|buy"],
        }

    def fake_probe_latest_canonical_promotion(db_path):
        latest_promotion_calls.append(db_path)
        return {
            "symbol": "BTCUSDTM",
            "strategy": "TRENDFOLLOWING",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "correlation_id": "corr-2",
            "promotion_runtime_seq": 11,
            "promotion_row_id": 9,
            "promotion_ts": "2026-04-14T00:00:00Z",
        }

    def fake_enqueue_post_promotion_reeval_request(db_path, request_payload, diag_cb):
        reeval_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return 101

    def fake_probe_forced_post_promotion_cycle(db_path):
        forced_cycle_probe_calls.append(db_path)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
            "promotion_runtime_seq": 11,
            "forced_cycle_request_runtime_seq": None,
            "forced_cycle_runtime_seq": None,
            "forced_cycle_exit_reason": None,
            "forced_cycle_result_classification": None,
        }

    def fake_enqueue_post_promotion_force_cycle_request(
        db_path,
        request_payload,
        diag_cb,
    ):
        forced_cycle_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return None

    def fake_pending_open_symbols(db_path):
        return []

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    real_finalize_post_promotion_forced_cycle_trigger_contract = (
        module._finalize_post_promotion_forced_cycle_trigger_contract
    )

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return real_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs)

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(
        module,
        "_probe_latest_canonical_promotion",
        fake_probe_latest_canonical_promotion,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_reeval_request",
        fake_enqueue_post_promotion_reeval_request,
    )
    monkeypatch.setattr(
        module,
        "_probe_forced_post_promotion_cycle",
        fake_probe_forced_post_promotion_cycle,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_force_cycle_request",
        fake_enqueue_post_promotion_force_cycle_request,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "after",
        0,
        "run-fail",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) >= 2
    assert len(reeval_probe_calls) >= 1
    assert len(latest_promotion_calls) >= 1
    assert len(reeval_request_calls) == 1
    assert len(forced_cycle_probe_calls) >= 1
    assert len(forced_cycle_request_calls) == 1
    assert any(
        record["event"] == "forced_cycle_failed"
        for record in result["runner_diagnostics"]
    )
    assert not any(
        record["event"] == "forced_cycle_requested"
        for record in result["runner_diagnostics"]
    )
    assert len(enqueue_close_calls) >= 1
    assert any(
        call["reason"] == "controlled_kpi_window_end"
        for call in enqueue_close_calls
    )
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_promotion_window_armed"] is True
    assert result["post_promotion_reeval_requested"] is True
    assert result["post_promotion_reeval_dispatch_entered"] is True
    assert result["post_promotion_window_exit_reason"] == "enqueue_failed"
    assert result["post_promotion_reeval_result"] == "enqueue_failed"
    assert result["post_promotion_reeval_exit_reason"] == "enqueue_failed"
    assert result["post_promotion_forced_cycle_trigger_mode"] == (
        "after_reeval_completed"
    )
    assert result["post_promotion_forced_cycle_request_reason"] == (
        "post_promotion_forced_cycle"
    )
    forced_cycle_contract = result["post_promotion_forced_cycle_trigger_contract"]
    assert forced_cycle_contract["active"] is False
    assert forced_cycle_contract["status"] == "inactive"
    assert forced_cycle_contract["ok"] is True
    assert result["process_returncode"] == 0
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_post_promotion_reeval_request_enqueue_failure_fails_closed(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    reeval_probe_calls = []
    latest_promotion_calls = []
    reeval_request_calls = []
    forced_cycle_probe_calls = []
    forced_cycle_request_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "100",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "3",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 7777
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 1

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    def fake_probe_real_post_promotion_reevaluation(db_path):
        reeval_probe_calls.append(db_path)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
            "real_post_promotion_read_count": 0,
            "real_post_promotion_read_buckets": [],
            "timing_replay_only_buckets": [],
            "promoted_buckets": ["BTCUSDTM|TRENDFOLLOWING|buy"],
        }

    def fake_probe_latest_canonical_promotion(db_path):
        latest_promotion_calls.append(db_path)
        return {
            "symbol": "BTCUSDTM",
            "strategy": "TRENDFOLLOWING",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "correlation_id": "corr-3",
            "promotion_runtime_seq": 11,
            "promotion_row_id": 10,
            "promotion_ts": "2026-04-14T00:00:00Z",
        }

    def fake_enqueue_post_promotion_reeval_request(db_path, request_payload, diag_cb):
        reeval_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return None

    def fake_probe_forced_post_promotion_cycle(db_path):
        forced_cycle_probe_calls.append(db_path)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
            "promotion_runtime_seq": 11,
            "forced_cycle_request_runtime_seq": None,
            "forced_cycle_runtime_seq": None,
            "forced_cycle_exit_reason": None,
            "forced_cycle_result_classification": None,
        }

    def fake_enqueue_post_promotion_force_cycle_request(
        db_path,
        request_payload,
        diag_cb,
    ):
        forced_cycle_request_calls.append(
            {
                "db_path": db_path,
                "request_payload": dict(request_payload),
            }
        )
        return None

    def fake_pending_open_symbols(db_path):
        pending_calls.append(db_path)
        return []

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    real_finalize_post_promotion_forced_cycle_trigger_contract = (
        module._finalize_post_promotion_forced_cycle_trigger_contract
    )

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return real_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs)

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(
        module,
        "_probe_latest_canonical_promotion",
        fake_probe_latest_canonical_promotion,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_reeval_request",
        fake_enqueue_post_promotion_reeval_request,
    )
    monkeypatch.setattr(
        module,
        "_probe_forced_post_promotion_cycle",
        fake_probe_forced_post_promotion_cycle,
    )
    monkeypatch.setattr(
        module,
        "_enqueue_post_promotion_force_cycle_request",
        fake_enqueue_post_promotion_force_cycle_request,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "after",
        0,
        "run-reeval-fail",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) >= 2
    assert len(reeval_probe_calls) >= 1
    assert len(latest_promotion_calls) >= 1
    assert len(reeval_request_calls) == 1
    assert len(forced_cycle_probe_calls) >= 1
    assert len(forced_cycle_request_calls) == 1
    assert any(
        record["event"] == "forced_cycle_failed"
        for record in result["runner_diagnostics"]
    )
    assert not any(
        record["event"] == "forced_cycle_requested"
        for record in result["runner_diagnostics"]
    )
    assert not any(
        record["event"] == "post_promotion_reeval_dispatch_enter"
        for record in result["runner_diagnostics"]
    )
    assert len(enqueue_close_calls) >= 1
    assert any(
        call["reason"] == "controlled_kpi_window_end"
        for call in enqueue_close_calls
    )
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_promotion_window_armed"] is True
    assert result["post_promotion_reeval_requested"] is False
    assert result["post_promotion_reeval_dispatch_entered"] is False
    assert result["post_promotion_window_exit_reason"] == "enqueue_failed"
    assert result["post_promotion_reeval_result"] == "enqueue_failed"
    assert result["post_promotion_reeval_exit_reason"] == "enqueue_failed"
    assert result["post_promotion_forced_cycle_trigger_mode"] == (
        "after_reeval_enqueue_failure"
    )
    assert result["post_promotion_forced_cycle_request_reason"] == (
        "post_promotion_forced_cycle_after_enqueue_failure"
    )
    forced_cycle_contract = result["post_promotion_forced_cycle_trigger_contract"]
    assert forced_cycle_contract["active"] is False
    assert forced_cycle_contract["status"] == "inactive"
    assert forced_cycle_contract["ok"] is True
    assert result["process_returncode"] == 0
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_post_promotion_timeout_without_gate_read_falls_back(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    probe_calls = []
    pending_symbol_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append(
            {
                "db_path": db_path,
                "variant": variant,
                "kwargs": kwargs,
            }
        )
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "100",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "1",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 4321
        returncode = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        assert "CONTROLLED_RUN_END_TS" in env
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 1

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    probe_results = [
        {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        },
        {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        },
        {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        },
    ]

    def fake_probe_real_post_promotion_reevaluation(db_path):
        probe_calls.append(db_path)
        if probe_results:
            return probe_results.pop(0)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
        }

    def fake_pending_open_symbols(db_path):
        pending_symbol_calls.append(db_path)
        return []

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "proc_exited",
            "final_termination_reason": "proc_exited",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
        }

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )

    result = module._run_variant(
        "after",
        0,
        "run-4",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM,ETHUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) >= 2
    assert len(probe_calls) >= 2
    assert len(pending_symbol_calls) == 0
    assert len(enqueue_close_calls) == 2
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_promotion_window_exit_reason"] == "max_cycles_reached"
    assert result["post_promotion_reeval_result"] == (
        "reevaluation_timeout_no_gate_read"
    )
    assert result["post_promotion_reeval_exit_reason"] == "max_cycles_reached"
    assert result["process_returncode"] == 0
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_post_close_summary_grace_finalizes_successfully(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    summary_grace_calls = []
    reeval_calls = []
    pending_symbol_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 1.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append({"db_path": db_path, "variant": variant})
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "0",
            "POST_PROMOTION_OBSERVATION_ENABLED": "1",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "2",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "2",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "1",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "0",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 9876
        returncode = 0

        def __init__(self):
            self.wait_count = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.wait_count += 1
            if self.wait_count <= 2:
                raise module.subprocess.TimeoutExpired(
                    cmd="fake-proc-wait",
                    timeout=timeout,
                )
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 1

    drain_snapshots = [
        {
            "pending_positions": 1,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 1,
        },
        {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        },
    ]

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return drain_snapshots.pop(0)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 1,
        }

    summary_grace_calls = []

    def fake_probe_post_close_summary_grace(db_path):
        summary_grace_calls.append(db_path)
        return {
            "post_close_boundary_rowid": 8,
            "entry_edge_over_fee_eval_count": 1,
            "post_close_summary_pre_assembly_count": 1,
            "post_close_summary_assembly_enter_count": 1,
            "post_close_summary_payload_built_count": 1,
            "post_close_summary_emit_attempt_count": 1,
            "post_close_summary_emit_done_count": 1,
            "entry_gate_decision_summary_count": 1,
            "risk_decision_count": 1,
            "observed_post_close_eval": True,
            "observed_post_close_summary_complete": True,
            "observed_post_close_summary_emit_done": True,
            "observed_post_close_risk_decision_parity": True,
        }

    def fake_probe_real_post_promotion_reevaluation(db_path):
        reeval_calls.append(db_path)
        return {
            "promotion_count": 1,
            "observed_real_post_promotion_read": True,
            "promotion_runtime_seq": 11,
            "gate_read_after_promotion_runtime_seq": 12,
            "reeval_runtime_seq": None,
            "real_post_promotion_read_count": 1,
            "real_post_promotion_read_buckets": ["BTCUSDTM|TRENDFOLLOWING|buy"],
            "timing_replay_only_buckets": [],
            "promoted_buckets": ["BTCUSDTM|TRENDFOLLOWING|buy"],
        }

    def fake_pending_open_symbols(db_path):
        pending_symbol_calls.append(db_path)
        return ["BTCUSDTM"]

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": "close_flush_done_pending_positions_zero",
            "final_termination_reason": "close_flush_done_pending_positions_zero",
            "final_drain_recheck_result": "not_applicable",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return 0

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
        }

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_post_close_summary_grace",
        fake_probe_post_close_summary_grace,
    )
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )

    result = module._run_variant(
        "after",
        0,
        "run-3",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 1
    assert len(close_snapshot_calls) >= 2
    assert len(summary_grace_calls) >= 2
    assert len(reeval_calls) >= 1
    assert len(enqueue_close_calls) >= 1
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["variant"] == "after"
    assert result["post_close_summary_grace_release_reason"] == (
        "bounded_tick_limit"
    )
    assert result["post_close_extra_tick_triggered"] is True
    assert result["post_close_extra_tick_count"] == 1
    assert result["runner_shutdown_reason"] == "real_post_promotion_read_observed"
    assert result["process_stop_mode"] == "wrapper_kill_after_success"
    assert result["process_returncode"] == 0
    assert result["process_returncode_raw"] == 0
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_run_variant_startup_parse_fallbacks_and_existing_db_cleanup(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    class _ExplodingStr:
        def __str__(self):
            raise RuntimeError("bad-string")

    stale_db_path = tmp_path / "controlled_kpi_after_run-fallback.db"
    stale_db_path.write_text("stale-db", encoding="utf-8")

    init_exists_before_calls = []
    init_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    def fake_init_db_schema(db_path):
        init_exists_before_calls.append(db_path.exists())
        init_calls.append(db_path)

    def fake_variant_env(*_args, **_kwargs):
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "not-a-float",
            "POST_PROMOTION_OBSERVATION_ENABLED": _ExplodingStr(),
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "not-a-float",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "not-an-int",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "not-an-int",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "not-a-float",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 4321
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(*_args, **_kwargs):
        return FakeProcess()

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 0

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        return {
            "pending_positions": 0,
            "close_request_backlog": 0,
            "close_request_backlog_raw": 0,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 0,
        }

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": kwargs.get("shutdown_classification")
            or "proc_exited",
            "final_termination_reason": kwargs.get("termination_reason")
            or "proc_exited",
            "final_drain_recheck_result": "not_applicable",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return int(kwargs.get("raw_returncode") or 0)

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
        }

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )

    result = module._run_variant(
        "after",
        0,
        "run-fallback",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=45,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    assert init_calls
    assert init_exists_before_calls == [False]
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) == 1
    assert len(close_snapshot_calls) >= 1
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert result["runner_shutdown_reason"] == "proc_exited"
    assert result["research_post_promotion_reeval_grace_sec"] == 0.0
    assert result["post_promotion_observation_enabled"] is True
    assert result["post_promotion_observation_max_sec"] == 15.0
    assert result["post_promotion_observation_max_cycles"] == 3
    assert result["research_post_close_summary_grace_ticks"] == 0
    assert result["research_post_close_summary_grace_timeout_sec"] == 45.0


def test_run_variant_close_drain_soft_warning_retry_and_failure_shutdown(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    init_calls = []
    variant_env_calls = []
    sentinel_calls = []
    clear_calls = []
    pending_calls = []
    close_snapshot_calls = []
    reeval_calls = []
    pending_symbol_calls = []
    enqueue_close_calls = []
    resolve_shutdown_calls = []
    collect_metrics_calls = []
    analyze_calls = []
    normalize_calls = []
    finalize_contract_calls = []

    time_value = {"current": 0.0}

    def fake_time():
        time_value["current"] += 5.0
        return time_value["current"]

    monkeypatch.setattr(module.time, "time", fake_time)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    def fake_init_db_schema(db_path):
        init_calls.append(db_path)

    def fake_variant_env(db_path, variant, **kwargs):
        variant_env_calls.append({"db_path": db_path, "variant": variant})
        return {
            "DIAGNOSTIC_MODE": "0",
            "LIVE": "0",
            "RESEARCH_POST_PROMOTION_REEVAL_GRACE_SEC": "5",
            "POST_PROMOTION_OBSERVATION_ENABLED": "0",
            "POST_PROMOTION_OBSERVATION_MAX_SEC": "30",
            "POST_PROMOTION_OBSERVATION_MAX_CYCLES": "3",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "0",
            "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "30",
        }

    def fake_sqlite_enqueue_window_sentinel_path(db_path):
        sentinel_calls.append(db_path)
        return db_path.with_suffix(".sentinel")

    def fake_clear_sqlite_enqueue_window_sentinel(db_path):
        clear_calls.append(db_path)

    class FakeProcess:
        pid = 9876
        returncode = 1

        def __init__(self):
            self.wait_count = 0
            self.terminate_count = 0
            self.kill_count = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.wait_count += 1
            if self.wait_count == 1:
                raise module.subprocess.TimeoutExpired(
                    cmd="fake-proc-wait",
                    timeout=timeout,
                )
            self.returncode = 1
            return 1

        def terminate(self):
            self.terminate_count += 1

        def kill(self):
            self.kill_count += 1

    fake_process = FakeProcess()

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        assert cwd == str(tmp_path)
        assert env is not None
        assert env["CONTROLLED_KPI_SQLITE_ENQUEUE_WINDOW_SENTINEL"].endswith(
            ".sentinel"
        )
        return fake_process

    def fake_pending_open_positions(db_path):
        pending_calls.append(db_path)
        return 2

    drain_snapshots = [
        {
            "pending_positions": 2,
            "close_request_backlog": 1,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 0,
            "position_open_count": 2,
        },
        {
            "pending_positions": 1,
            "close_request_backlog": 1,
            "close_request_backlog_raw": 1,
            "duplicate_close_request_count": 0,
            "position_close_count": 1,
            "position_open_count": 2,
        },
    ]
    steady_snapshot = {
        "pending_positions": 1,
        "close_request_backlog": 1,
        "close_request_backlog_raw": 1,
        "duplicate_close_request_count": 0,
        "position_close_count": 1,
        "position_open_count": 2,
    }

    def fake_close_drain_snapshot(db_path):
        close_snapshot_calls.append(db_path)
        if drain_snapshots:
            return dict(drain_snapshots.pop(0))
        return dict(steady_snapshot)

    def fake_probe_real_post_promotion_reevaluation(db_path):
        reeval_calls.append(db_path)
        return {
            "promotion_count": 0,
            "observed_real_post_promotion_read": False,
            "promotion_runtime_seq": None,
            "gate_read_after_promotion_runtime_seq": None,
            "reeval_runtime_seq": None,
            "real_post_promotion_read_count": 0,
            "real_post_promotion_read_buckets": [],
            "timing_replay_only_buckets": [],
            "promoted_buckets": [],
        }

    def fake_pending_open_symbols(db_path):
        pending_symbol_calls.append(db_path)
        return ["BTCUSDTM"]

    def fake_enqueue_close_requests(db_path, release_symbols, reason, diag_cb):
        enqueue_close_calls.append(
            {
                "db_path": db_path,
                "release_symbols": list(release_symbols),
                "reason": reason,
            }
        )
        return len(list(release_symbols)) or 1

    def fake_resolve_final_shutdown_state(**kwargs):
        resolve_shutdown_calls.append(kwargs)
        return {
            "final_shutdown_classification": kwargs.get("shutdown_classification"),
            "final_termination_reason": kwargs.get("termination_reason"),
            "final_drain_recheck_result": "not_applicable",
        }

    def fake_collect_metrics(db_path):
        collect_metrics_calls.append(db_path)
        return {
            "db_exists": True,
            "trade_count": 0,
            "net_pnl": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 1.0,
            "gross_profit": 0.0,
            "gross_loss_abs": 0.0,
            "decisions_count": 0,
            "equity_points": 0,
            "symbol_stats": {},
            "event_counts": {},
        }

    def fake_analyze_process_logs(out_log, err_log):
        analyze_calls.append((out_log, err_log))
        return {
            "error_count": 0,
            "warning_count": 0,
            "sample_errors": [],
        }

    def fake_normalize_process_returncode(**kwargs):
        normalize_calls.append(kwargs)
        return int(kwargs.get("raw_returncode") or 0)

    def fake_finalize_post_promotion_forced_cycle_trigger_contract(**kwargs):
        finalize_contract_calls.append(kwargs)
        return {
            "requested": False,
            "started": False,
            "completed": False,
            "failed": False,
        }

    monkeypatch.setattr(module, "_init_db_schema", fake_init_db_schema)
    monkeypatch.setattr(module, "_variant_env", fake_variant_env)
    monkeypatch.setattr(
        module,
        "_sqlite_enqueue_window_sentinel_path",
        fake_sqlite_enqueue_window_sentinel_path,
    )
    monkeypatch.setattr(
        module,
        "_clear_sqlite_enqueue_window_sentinel",
        fake_clear_sqlite_enqueue_window_sentinel,
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_pending_open_positions", fake_pending_open_positions)
    monkeypatch.setattr(module, "_close_drain_snapshot", fake_close_drain_snapshot)
    monkeypatch.setattr(
        module,
        "_probe_real_post_promotion_reevaluation",
        fake_probe_real_post_promotion_reevaluation,
    )
    monkeypatch.setattr(module, "_pending_open_symbols", fake_pending_open_symbols)
    monkeypatch.setattr(module, "_enqueue_close_requests", fake_enqueue_close_requests)
    monkeypatch.setattr(
        module,
        "_resolve_final_shutdown_state",
        fake_resolve_final_shutdown_state,
    )
    monkeypatch.setattr(module, "_collect_metrics", fake_collect_metrics)
    monkeypatch.setattr(module, "_analyze_process_logs", fake_analyze_process_logs)
    monkeypatch.setattr(
        module,
        "_normalize_process_returncode",
        fake_normalize_process_returncode,
    )
    monkeypatch.setattr(
        module,
        "_finalize_post_promotion_forced_cycle_trigger_contract",
        fake_finalize_post_promotion_forced_cycle_trigger_contract,
    )
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )

    result = module._run_variant(
        "after",
        0,
        "run-close-drain-failure",
        use_mock=False,
        market_type="futures",
        run_symbols="BTCUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=10,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///source.db",
        alpha_bootstrap_source_db_glob="source.db",
        variant_overrides={
            "ENTRY_STRATEGY_SIDE_ALLOWLIST": "BTCUSDTM:TRENDFOLLOWING:buy"
        },
    )

    enqueue_reasons = [call["reason"] for call in enqueue_close_calls]

    assert init_calls
    assert variant_env_calls[0]["variant"] == "after"
    assert len(sentinel_calls) == 1
    assert len(clear_calls) == 1
    assert len(pending_calls) >= 2
    assert len(close_snapshot_calls) >= 3
    assert len(reeval_calls) >= 2
    assert len(pending_symbol_calls) >= 1
    assert "controlled_kpi_window_end" in enqueue_reasons
    assert "controlled_kpi_final_drain_retry" in enqueue_reasons
    assert len(resolve_shutdown_calls) == 1
    assert len(collect_metrics_calls) == 1
    assert len(analyze_calls) == 1
    assert len(normalize_calls) == 1
    assert len(finalize_contract_calls) == 1
    assert fake_process.terminate_count == 1
    assert fake_process.kill_count == 1
    assert result["variant"] == "after"
    assert result["research_post_promotion_reeval_grace_sec"] == 5.0
    assert result["runner_shutdown_reason"] == "deterministic_stall_pending_close_drain"
    assert result["shutdown_classification"] == "deterministic_stall_pending_close_drain"
    assert result["process_stop_mode"] == "wrapper_kill_after_failure"
    assert result["process_returncode_raw"] == 1
    assert result["process_returncode"] == 1
    assert result["log_health"]["error_count"] == 0
    assert result["diagnostic_env_flags"]["LIVE"] == "0"


def test_enqueue_post_promotion_force_cycle_request_locked_db_fails_without_retry(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    db_path, conn = _make_runtime_db(tmp_path)
    conn.close()

    connect_calls = {"count": 0}

    def fake_connect(*args, **kwargs):
        connect_calls["count"] += 1
        raise module.sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(module.sqlite3, "connect", fake_connect)

    diag_events = []

    def diag_cb(event, **kwargs):
        diag_events.append((event, kwargs))

    row_id = module._enqueue_post_promotion_force_cycle_request(
        db_path,
        {
            "symbol": "BTCUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "promotion_runtime_seq": 7,
        },
        diag_cb=diag_cb,
    )

    assert row_id is None
    assert connect_calls["count"] == 1
    assert [name for name, _ in diag_events][:1] == ["handoff_parent_enqueue_enter"]
    assert any(name == "forced_cycle_failed" for name, _ in diag_events)
    failed_payload = next(
        payload for name, payload in diag_events if name == "forced_cycle_failed"
    )
    assert failed_payload["forced_cycle_exit_reason"].startswith("enqueue_error:")
    assert failed_payload["exception_class"] == "OperationalError"


def test_probe_forced_post_promotion_cycle_uses_row_ids_and_handles_non_dict_payload(
    controlled_kpi_run_module,
    monkeypatch,
    tmp_path,
):
    module = controlled_kpi_run_module
    db_path, conn = _make_runtime_db(tmp_path)
    try:
        conn.execute(
            "INSERT INTO logs(id, timestamp, event, details) VALUES (?, ?, ?, ?)",
            (101, "2026-04-16T00:00:01Z", "forced_cycle_requested", "LIST_PAYLOAD"),
        )
        conn.execute(
            "INSERT INTO logs(id, timestamp, event, details) VALUES (?, ?, ?, ?)",
            (
                102,
                "2026-04-16T00:00:02Z",
                "post_promotion_force_cycle_request",
                json.dumps(
                    {
                        "promotion_runtime_seq": 77,
                        "forced_cycle_request_runtime_seq": 7001,
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO logs(id, timestamp, event, details) VALUES (?, ?, ?, ?)",
            (
                103,
                "2026-04-16T00:00:03Z",
                "forced_cycle_started",
                json.dumps(
                    {
                        "promotion_runtime_seq": 77,
                        "forced_cycle_runtime_seq": 8001,
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO logs(id, timestamp, event, details) VALUES (?, ?, ?, ?)",
            (
                104,
                "2026-04-16T00:00:04Z",
                "forced_cycle_completed",
                json.dumps(
                    {
                        "promotion_runtime_seq": 77,
                        "forced_cycle_runtime_seq": 9001,
                        "forced_cycle_exit_reason": "completed",
                        "result_classification": "done",
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    real_parse_json_payload = module._parse_json_payload

    def fake_parse_json_payload(raw):
        if raw == "LIST_PAYLOAD":
            return []
        return real_parse_json_payload(raw)

    monkeypatch.setattr(module, "_parse_json_payload", fake_parse_json_payload)

    cycle = module._probe_forced_post_promotion_cycle(db_path)

    assert cycle["requested"] is True
    assert cycle["started"] is True
    assert cycle["completed"] is True
    assert cycle["failed"] is False
    assert cycle["promotion_runtime_seq"] == 77
    assert cycle["forced_cycle_request_runtime_seq"] == 102
    assert cycle["forced_cycle_runtime_seq"] == 104
    assert cycle["forced_cycle_exit_reason"] == "completed"
    assert cycle["forced_cycle_result_classification"] == "done"
