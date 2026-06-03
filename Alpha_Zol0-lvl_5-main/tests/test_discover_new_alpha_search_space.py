from scripts.discover_new_alpha_search_space import classify_research_universe


def _candles(closes):
    out = []
    for idx, close in enumerate(closes):
        out.append(
            {
                "timestamp": 1_700_000_000_000 + idx * 60_000,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
                "turnover": 1000.0 * close,
            }
        )
    return out


def test_classify_research_universe_finds_candidate_above_full_cost_floor():
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

    assert report["classification"] == "NEW_ALPHA_CANDIDATE_FOUND_FOR_PAPER_VALIDATION"
    assert report["selected_hypothesis"]["symbol"] == "ADAUSDTM"
    assert report["selected_hypothesis"]["expected_net_after_full_cost"] >= 0.08
    assert report["selected_hypothesis"]["source"] == "fresh_kucoin_public_klines_research"


def test_classify_research_universe_rejects_flat_history_without_candidate():
    report = classify_research_universe(
        histories={
            "ADAUSDTM": _candles([1.00, 1.00, 1.00, 1.00, 1.00, 1.00]),
        },
        min_expected_net_usdt=0.08,
        free_equity_usdt=1000.0,
        spread_bps=1.0,
    )

    assert report["classification"] == "NO_NEW_ALPHA_CANDIDATE_FOUND"
    assert report["selected_hypothesis"] is None
    assert report["evaluated_symbol_count"] == 1
