import json
from pathlib import Path

from scripts.discover_new_alpha_search_space import (
    classify_research_universe,
    source_parity_contract,
)


def _candles(closes):
    return [
        {
            "timestamp": 1_700_000_000_000 + idx * 60_000,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000.0,
            "turnover": 1000.0 * close,
        }
        for idx, close in enumerate(closes)
    ]


def test_public_kline_candidate_without_overlap_is_not_runtime_admissible():
    report = classify_research_universe(
        histories={
            "ADAUSDTM": _candles(
                [1.00, 1.001, 1.002, 1.006, 1.012, 1.018, 1.024, 1.030, 1.036]
            ),
        },
        min_expected_net_usdt=0.08,
        free_equity_usdt=1000.0,
        spread_bps=1.0,
    )

    selected = report["selected_hypothesis"]
    assert selected["expected_net_after_full_cost"] >= 0.08
    assert selected["runtime_admissible"] is False
    assert (
        selected["runtime_admissibility_classification"]
        == "RESEARCH_RUNTIME_SOURCE_MISMATCH_NOT_RUNTIME_ADMISSIBLE"
    )
    assert report["runtime_admissible_candidate_count"] == 0


def test_source_labels_are_preserved_in_research_artifact():
    report = classify_research_universe(
        histories={
            "ADAUSDTM": _candles(
                [1.00, 1.001, 1.002, 1.006, 1.012, 1.018, 1.024, 1.030]
            )
        },
        min_expected_net_usdt=0.08,
        free_equity_usdt=1000.0,
        spread_bps=1.0,
    )

    selected = report["selected_hypothesis"]
    assert selected["research_source"] == "kucoin_public_futures_klines"
    assert selected["candidate_source"] == "fresh_kucoin_public_klines_research"
    assert selected["expected_runtime_admission_source"] == "rolling_quote_window"
    assert selected["source_overlap_proven"] is False


def test_runtime_smoke_artifact_source_label_can_be_derived(tmp_path):
    artifact = tmp_path / "fresh_alpha_candidate_runtime_smoke_current.json"
    artifact.write_text(
        json.dumps(
            {
                "candidate": {
                    "runtime_profile_keys_top": {
                        "AVAXUSDTM|rolling_quote_window|n=115|span=788": 4
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    contract = source_parity_contract(
        research_source="kucoin_public_futures_klines",
        candidate_source="fresh_kucoin_public_klines_research",
        runtime_source="rolling_quote_window",
        source_overlap_proven=False,
    )

    assert "rolling_quote_window" in next(
        iter(payload["candidate"]["runtime_profile_keys_top"])
    )
    assert contract["runtime_source"] == "rolling_quote_window"


def test_source_mismatch_final_classification_is_explicit_fail_closed():
    contract = source_parity_contract(
        research_source="kucoin_public_futures_klines",
        candidate_source="fresh_kucoin_public_klines_research",
        runtime_source="rolling_quote_window",
        source_overlap_proven=False,
    )

    assert contract["runtime_admissible"] is False
    assert (
        contract["classification"]
        == "RESEARCH_RUNTIME_SOURCE_MISMATCH_NOT_RUNTIME_ADMISSIBLE"
    )
    assert contract["fail_closed"] is True


def test_source_parity_proven_candidate_can_proceed_without_threshold_change():
    contract = source_parity_contract(
        research_source="kucoin_public_futures_klines",
        candidate_source="fresh_kucoin_public_klines_research",
        runtime_source="rolling_quote_window",
        source_overlap_proven=True,
    )

    assert contract["runtime_admissible"] is True
    assert contract["classification"] == "RESEARCH_RUNTIME_SOURCE_PARITY_PROVEN"
    assert contract["threshold_mutation"] is False
