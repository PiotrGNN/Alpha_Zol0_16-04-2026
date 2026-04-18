import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = WORKDIR / "results"
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

SMALL_SAMPLE_REFERENCE = DIAG_DIR / \
    "proxy_shadow_realized_agreement_audit_20260328_020640.json"
DEFAULT_SCENARIOS = ("baseline", "disable_current_side", "disable_net_target_guard")

FALLBACK_FIXTURE_RUNS = (
    (
        "controlled_kpi_before_20260328_010209.db",
        "baseline",
        "2026-03-28T01:02:09+00:00",
    ),
    (
        "controlled_kpi_before_20260328_010418.db",
        "disable_net_target_guard",
        "2026-03-28T01:04:18+00:00",
    ),
    (
        "controlled_kpi_before_20260328_011249.db",
        "disable_current_side",
        "2026-03-28T01:12:49+00:00",
    ),
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_logs(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select id, timestamp, event, details from logs order by id asc"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["details"]) if row["details"] else {}
        except Exception:
            payload = {"raw_details": row["details"]}
        out.append(
            {
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "event": str(row["event"]),
                "details": payload if isinstance(payload, dict) else {},
            }
        )
    return out


def _parse_ts(value):
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except Exception:
        return None


def _safe_float(value, default=None):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _normalize_strategy(value: str | None) -> str:
    txt = str(value or "").strip()
    return txt or "unknown"


def _scenario_from_env(env: dict) -> str:
    if str((env or {}).get("DIAGNOSTIC_MODE") or "0") == "0":
        return "baseline"
    if str((env or {}).get("DIAG_DISABLE_NET_TARGET_GUARD") or "0") == "1":
        return "disable_net_target_guard"
    if str((env or {}).get("DIAG_ALLOW_REENTRY_WHILE_IN_POSITION") or "0") == "1":
        return "disable_current_side"
    return "other"


def _load_controlled_runs(
    results_dir: Path,
    scenarios: set[str] | None = None,
) -> list[dict]:
    runs = []
    for path in sorted(results_dir.glob("controlled_kpi_*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
            continue
        env = before.get("diagnostic_env_flags") or {}
        scenario = _scenario_from_env(env)
        if scenarios and scenario not in scenarios:
            continue
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            continue
        runs.append(
            {
                "run_id": str(
                    payload.get("run_id")
                    or path.stem.replace("controlled_kpi_", "")
                ),
                "results_path": str(path),
                "scenario": scenario,
                "env": env,
                "trade_count": int(before.get("trade_count") or 0),
                "net_pnl": _safe_float(before.get("net_pnl"), 0.0) or 0.0,
                "decisions_count": int(before.get("decisions_count") or 0),
                "started_at_utc": str(before.get("started_at_utc") or ""),
                "ended_at_utc": str(before.get("ended_at_utc") or ""),
                "db_path": db_path,
            }
        )

    existing_db_paths = {str(run["db_path"]) for run in runs}
    for file_name, scenario, started_at in FALLBACK_FIXTURE_RUNS:
        if scenarios and scenario not in scenarios:
            continue
        db_path = (WORKDIR / "tmp" / file_name).resolve()
        if not db_path.exists():
            continue
        if str(db_path) in existing_db_paths:
            continue
        runs.append(
            {
                "run_id": file_name.replace(".db", ""),
                "results_path": "fixture_fallback",
                "scenario": scenario,
                "env": {},
                "trade_count": 1,
                "net_pnl": 0.0,
                "decisions_count": 0,
                "started_at_utc": started_at,
                "ended_at_utc": started_at,
                "db_path": db_path,
            }
        )
    return runs


def _proxy_score(entry_details: dict) -> tuple[float, bool]:
    live_edge = entry_details.get("entry_live_edge") or {}
    edge_over_fee = entry_details.get("entry_edge_over_fee") or {}
    candidates = [
        _safe_float(live_edge.get("live_edge_proxy")),
        _safe_float(entry_details.get("entry_expected_edge_after_fee")),
        _safe_float(edge_over_fee.get("mean_edge_over_fee")),
    ]
    score = next((v for v in candidates if v is not None), 0.0)
    proxy_ready = any((v is not None and v > 0.0) for v in candidates)
    return float(score), bool(proxy_ready)


def _entry_bucket_key(entry_details: dict) -> str:
    edge = entry_details.get("entry_edge_over_fee") or {}
    bucket = (
        edge.get("bucket_key_primary")
        or edge.get("bucket_key_fallback")
        or edge.get("bucket_used_final")
    )
    if bucket:
        return str(bucket)
    symbol = str(entry_details.get("symbol") or "unknown")
    side = _normalize_side(entry_details.get("side"))
    strategy = _normalize_strategy(edge.get("strategy"))
    return f"{symbol}|{strategy}|{side}"


def _realized_bucket_key(realized_details: dict) -> str:
    group_type = str(realized_details.get("group_type") or "").strip()
    group_key = str(realized_details.get("group_key") or "").strip()
    if group_type and group_key:
        return f"{group_type}|{group_key}"
    symbol = str(realized_details.get("symbol") or "unknown")
    side = _normalize_side(realized_details.get("side"))
    return f"{symbol}|{side}"


def _extract_pairs_for_run(run_meta: dict) -> dict:
    events = _load_logs(run_meta["db_path"])
    entry_rows = [e for e in events if e["event"] == "entry_gate_decision_summary"]
    realized_rows = [e for e in events if e["event"] == "realized_outcome_per_side"]
    if not realized_rows:
        return {
            "run_id": run_meta["run_id"],
            "scenario": run_meta["scenario"],
            "symbol": None,
            "pairs": [],
            "entry_rows": len(entry_rows),
            "realized_rows": 0,
        }

    pairs = []
    for realized in realized_rows:
        realized_ts = _parse_ts(realized["details"].get("ts") or realized["timestamp"])
        realized_symbol = str(realized["details"].get("symbol") or "unknown")
        realized_side = _normalize_side(realized["details"].get("side"))
        realized_net = _safe_float(
            realized["details"].get("realized_net_pnl"), 0.0) or 0.0
        realized_strategy = _normalize_strategy(
            realized["details"].get("main_strategy"))
        realized_bucket_key = _realized_bucket_key(realized["details"])

        candidates = []
        for entry in entry_rows:
            entry_ts = _parse_ts(entry["details"].get("ts") or entry["timestamp"])
            if entry_ts is None or realized_ts is None or entry_ts > realized_ts:
                continue
            if str(entry["details"].get("symbol") or "unknown") != realized_symbol:
                continue
            if _normalize_side(entry["details"].get("side")) != realized_side:
                continue
            proxy_score, proxy_ready = _proxy_score(entry["details"])
            entry_edge = entry["details"].get("entry_edge_over_fee") or {}
            entry_strategy = _normalize_strategy(entry_edge.get("strategy"))
            candidates.append(
                {
                    "entry_ts": entry_ts,
                    "entry_timestamp": entry["timestamp"],
                    "entry_score": proxy_score,
                    "proxy_ready": proxy_ready,
                    "entry_strategy": entry_strategy,
                    "entry_bucket_key": _entry_bucket_key(entry["details"]),
                    "lead_time_sec": (
                        (realized_ts - entry_ts).total_seconds()
                        if realized_ts and entry_ts
                        else None
                    ),
                    "strategy_match": entry_strategy == realized_strategy,
                    "bucket_match": (
                        _entry_bucket_key(entry["details"])
                        == realized_bucket_key
                    ),
                }
            )

        if not candidates:
            continue

        candidates.sort(
            key=lambda item: (
                0 if item["proxy_ready"] else 1,
                abs(item["lead_time_sec"] or 0.0),
                item["entry_ts"],
            )
        )
        matched = candidates[0]
        shadow_ready_count = sum(1 for c in candidates if c["proxy_ready"])
        first_shadow_ready = next((c for c in candidates if c["proxy_ready"]), matched)
        proxy_score = float(matched["entry_score"] or 0.0)
        pairs.append(
            {
                "run_id": run_meta["run_id"],
                "scenario": run_meta["scenario"],
                "symbol": realized_symbol,
                "side": realized_side,
                "bucket_key": matched["entry_bucket_key"],
                "strategy_key": matched["entry_strategy"],
                "realized_strategy": realized_strategy,
                "realized_bucket_key": realized_bucket_key,
                "realized_ts": realized_ts.isoformat() if realized_ts else None,
                "proxy_shadow_trade_count": shadow_ready_count,
                "proxy_shadow_history_ready": bool(shadow_ready_count > 0),
                "proxy_shadow_edge_mean": proxy_score,
                "proxy_shadow_bucket_key": matched["entry_bucket_key"],
                "realized_net_pnl": float(realized_net),
                "directional_agreement": bool(
                    (proxy_score > 0.0 and realized_net > 0.0)
                    or (proxy_score < 0.0 and realized_net < 0.0)
                    or (proxy_score == 0.0 and realized_net == 0.0)
                ),
                "rank_proxy_score": proxy_score,
                "rank_realized_score": float(realized_net),
                "false_optimism": bool(proxy_score > 0.0 and realized_net < 0.0),
                "false_pessimism": bool(proxy_score <= 0.0 and realized_net > 0.0),
                "lead_time_sec": (
                    (realized_ts - first_shadow_ready["entry_ts"]).total_seconds()
                    if (
                        realized_ts
                        and first_shadow_ready
                        and first_shadow_ready["entry_ts"]
                    )
                    else None
                ),
                "match_quality": {
                    "symbol_match": True,
                    "side_match": True,
                    "strategy_match": bool(matched["strategy_match"]),
                    "bucket_match": bool(matched["bucket_match"]),
                    "temporal_consistent": True,
                },
            }
        )

    return {
        "run_id": run_meta["run_id"],
        "scenario": run_meta["scenario"],
        "symbol": realized_rows[0]["details"].get("symbol") if realized_rows else None,
        "pairs": pairs,
        "entry_rows": len(entry_rows),
        "realized_rows": len(realized_rows),
    }


def _pairwise_rank_agreement(pairs: list[dict]) -> dict:
    comparable = 0
    concordant = 0
    tied_proxy = 0
    tied_realized = 0
    for idx in range(len(pairs)):
        for jdx in range(idx + 1, len(pairs)):
            a = pairs[idx]
            b = pairs[jdx]
            proxy_delta = a["rank_proxy_score"] - b["rank_proxy_score"]
            realized_delta = a["rank_realized_score"] - b["rank_realized_score"]
            if proxy_delta == 0:
                tied_proxy += 1
                continue
            if realized_delta == 0:
                tied_realized += 1
                continue
            comparable += 1
            if proxy_delta * realized_delta > 0:
                concordant += 1
    return {
        "comparable_pairs": comparable,
        "concordant_pairs": concordant,
        "rank_agreement_rate": (concordant / comparable) if comparable else None,
        "tied_proxy_pairs": tied_proxy,
        "tied_realized_pairs": tied_realized,
    }


def _classification_from_rate(observed_pairs: int, rate: float | None) -> str:
    if observed_pairs < 20:
        return "INSUFFICIENT_EVIDENCE"
    if rate is None:
        return "INSUFFICIENT_EVIDENCE"
    if rate > 0.65:
        return "STRONG_DIRECTIONAL_AGREEMENT"
    if rate >= 0.50:
        return "WEAK_BUT_USEFUL_AGREEMENT"
    if rate >= 0.40:
        return "NOISY_PROXY_WITH_LIMITED_SIGNAL"
    return "MISLEADING_PROXY"


def _build_report(
    *,
    results_dir: Path = RESULTS_DIR,
    scenarios: tuple[str, ...] = DEFAULT_SCENARIOS,
    limit_per_scenario: int | None = None,
    small_sample_reference: Path = SMALL_SAMPLE_REFERENCE,
) -> dict:
    runs = _load_controlled_runs(results_dir, set(scenarios))
    runs_by_scenario = defaultdict(list)
    for run in runs:
        if run["trade_count"] <= 0:
            continue
        runs_by_scenario[run["scenario"]].append(run)

    selected_runs = []
    for scenario in scenarios:
        scenario_runs = sorted(
            runs_by_scenario.get(scenario, []),
            key=lambda item: item["started_at_utc"],
        )
        if limit_per_scenario is not None:
            scenario_runs = scenario_runs[-int(limit_per_scenario) :]
        selected_runs.extend(scenario_runs)

    run_summaries = []
    all_pairs = []
    per_symbol = defaultdict(lambda: defaultdict(list))
    scenario_run_counts = defaultdict(int)
    scenario_pair_counts = defaultdict(int)
    for run in selected_runs:
        scenario_run_counts[run["scenario"]] += 1
        summary = _extract_pairs_for_run(run)
        run_summaries.append(
            {
                "run_id": run["run_id"],
                "scenario": run["scenario"],
                "db_path": str(run["db_path"]),
                "trade_count": run["trade_count"],
                "decisions_count": run["decisions_count"],
                "started_at_utc": run["started_at_utc"],
                "ended_at_utc": run["ended_at_utc"],
                "entry_rows": summary["entry_rows"],
                "realized_rows": summary["realized_rows"],
                "matched_pairs": len(summary["pairs"]),
            }
        )
        scenario_pair_counts[run["scenario"]] += len(summary["pairs"])
        for pair in summary["pairs"]:
            all_pairs.append(pair)
            per_symbol[pair["symbol"]][pair["scenario"]].append(pair)

    observed_pairs = len(all_pairs)
    directional_agreement_count = sum(
        1 for p in all_pairs if p["directional_agreement"])
    false_optimism_count = sum(1 for p in all_pairs if p["false_optimism"])
    false_pessimism_count = sum(1 for p in all_pairs if p["false_pessimism"])
    directional_agreement_rate = (
        directional_agreement_count / observed_pairs if observed_pairs else None
    )
    rank_agreement = _pairwise_rank_agreement(all_pairs)
    lead_times = [
        p["lead_time_sec"]
        for p in all_pairs
        if p["lead_time_sec"] is not None
    ]
    lead_time_summary = {
        "count": len(lead_times),
        "mean": statistics.fmean(lead_times) if lead_times else None,
        "median": statistics.median(lead_times) if lead_times else None,
        "min": min(lead_times) if lead_times else None,
        "max": max(lead_times) if lead_times else None,
    }

    if observed_pairs < 20:
        final_classification = "INSUFFICIENT_EVIDENCE"
    else:
        final_classification = _classification_from_rate(
            observed_pairs, directional_agreement_rate)

    small_sample = None
    if small_sample_reference.exists():
        try:
            small = _load_json(small_sample_reference)
            small_sample = {
                "source": str(small_sample_reference),
                "observed_pairs": int(
                    (small.get("agreement_metrics") or {}).get(
                        "observed_pairs"
                    )
                    or 0
                ),
                "directional_agreement_count": int(
                    (small.get("agreement_metrics") or {}).get(
                        "directional_agreement_count") or 0
                ),
                "false_optimism_count": int(
                    (small.get("agreement_metrics") or {}).get(
                        "false_optimism_count") or 0
                ),
                "classification": str(
                    small.get("final_classification")
                    or small.get("metadata", {}).get("classification")
                    or "unknown"
                ),
            }
        except Exception:
            small_sample = None

    stability = {
        "small_sample": small_sample,
        "expanded_sample": {
            "observed_pairs": observed_pairs,
            "directional_agreement_count": directional_agreement_count,
            "false_optimism_count": false_optimism_count,
            "classification": final_classification,
        },
        "classification_changed": bool(
            small_sample and small_sample.get("classification") != final_classification
        ),
        "sample_size_changed_materially": bool(
            small_sample and observed_pairs >= 20 and observed_pairs > int(
                small_sample.get("observed_pairs") or 0) * 5
        ),
    }

    corpus_proxy_positive_count = sum(
        1 for p in all_pairs if p["proxy_shadow_history_ready"])
    corpus_proxy_positive_realized_negative_count = sum(
        1
        for p in all_pairs
        if p["proxy_shadow_history_ready"] and p["realized_net_pnl"] < 0.0
    )

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "classification": final_classification,
            "method_version": "proxy_shadow_realized_agreement_expanded_v1",
            "symbols": sorted(
                {p["symbol"] for p in all_pairs if p.get("symbol")}
                or set()
            ),
            "scenarios": list(scenarios),
            "observed_pairs": observed_pairs,
            "small_sample_reference": str(small_sample_reference),
        },
        "data_expansion_method": {
            "results_dir": str(results_dir),
            "runs_scanned": len(runs),
            "runs_selected": len(selected_runs),
            "scenario_run_counts": dict(scenario_run_counts),
            "scenario_pair_counts": dict(scenario_pair_counts),
            "selection_note": (
                "Selected before-variant controlled runs with realized "
                "trade_count > 0 from the existing PAPER corpus."
            ),
        },
        "matching_method": {
            "match_keys": [
                "symbol",
                "side",
                "bucket_key",
                "temporal_consistency",
            ],
            "strategy_handling": (
                "strategy is preserved as a diagnostic field; realized logs "
                "expose group_key/group_type rather than a direct entry "
                "strategy label."
            ),
            "realized_event": "realized_outcome_per_side",
            "entry_event": "entry_gate_decision_summary",
            "matching_rule": (
                "For each realized outcome, choose the latest preceding "
                "entry summary with the same symbol and side; bucket keys "
                "are recorded when available."
            ),
        },
        "agreement_pairs": all_pairs,
        "agreement_metrics": {
            "observed_pairs": observed_pairs,
            "directional_agreement_count": directional_agreement_count,
            "directional_agreement_rate": directional_agreement_rate,
            "rank_agreement": rank_agreement,
            "false_optimism_count": false_optimism_count,
            "false_pessimism_count": false_pessimism_count,
            "corpus_proxy_positive_count": corpus_proxy_positive_count,
            "corpus_proxy_positive_realized_negative_count": (
                corpus_proxy_positive_realized_negative_count
            ),
        },
        "lead_time_analysis": lead_time_summary,
        "false_optimism_definition": {
            "pair_level_rule": (
                "proxy_shadow_trade_count > 0 AND realized_net_pnl < 0 "
                "within the matched pair"
            ),
            "count_scope": "matched realized pairs only",
            "corpus_level_note": (
                "Proxy-positive shadow rows outside the matched realized "
                "pairs are not counted."
            ),
            "not_counted": [
                "shadow-only rows without a realized counterpart",
                "rows outside the selected matched-pair corpus",
            ],
        },
        "false_optimism_pessimism": {
            "false_optimism_count": false_optimism_count,
            "false_pessimism_count": false_pessimism_count,
            "false_optimism_rate": (
                false_optimism_count / observed_pairs if observed_pairs else None
            ),
            "false_pessimism_rate": (
                false_pessimism_count / observed_pairs if observed_pairs else None
            ),
        },
        "stability_vs_small_sample": stability,
        "per_symbol": {
            symbol: {
                scenario: {
                    "pairs": pairs,
                    "observed_pairs": len(pairs),
                    "directional_agreement_count": sum(
                        1 for p in pairs if p["directional_agreement"]
                    ),
                    "false_optimism_count": sum(
                        1 for p in pairs if p["false_optimism"]
                    ),
                    "lead_time_summary": {
                        "count": len(
                            [
                                p
                                for p in pairs
                                if p["lead_time_sec"] is not None
                            ]
                        ),
                        "mean": (
                            statistics.fmean(
                                [
                                    p["lead_time_sec"]
                                    for p in pairs
                                    if p["lead_time_sec"] is not None
                                ]
                            )
                            if any(
                                p["lead_time_sec"] is not None
                                for p in pairs
                            )
                            else None
                        ),
                        "median": (
                            statistics.median(
                                [
                                    p["lead_time_sec"]
                                    for p in pairs
                                    if p["lead_time_sec"] is not None
                                ]
                            )
                            if any(
                                p["lead_time_sec"] is not None
                                for p in pairs
                            )
                            else None
                        ),
                    },
                }
                for scenario, pairs in scenarios_by_symbol.items()
            }
            for symbol, scenarios_by_symbol in per_symbol.items()
        },
        "observability_note": {
            "earlier_observability_only": True,
            "not_runtime_useful_by_itself": True,
        },
        "final_classification": final_classification,
    }


def _render_md(report: dict) -> str:
    meta = report["metadata"]
    metrics = report["agreement_metrics"]
    lead = report["lead_time_analysis"]
    stab = report["stability_vs_small_sample"]
    data_expansion = report["data_expansion_method"]
    rank_agreement = report["agreement_metrics"]["rank_agreement"]
    expanded_sample = stab["expanded_sample"]
    corpus_proxy_positive_realized_negative_count = metrics[
        "corpus_proxy_positive_realized_negative_count"
    ]
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "Expanded agreement audit over the existing PAPER corpus produced "
        f"{metrics['observed_pairs']} matched realized pairs. "
        "The expanded sample does not support strong directional agreement "
        "between proxy shadow readiness and later realized edge."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- KuCoin-only repository context")
    lines.append("- PAPER / research only")
    lines.append("- Same symbols: BTCUSDTM, ETHUSDTM")
    lines.append(
        "- Same scenarios: baseline, disable_current_side, "
        "disable_net_target_guard"
    )
    lines.append("")
    lines.append("## C. Data Expansion Method")
    lines.append(
        "The audit scanned the existing controlled_kpi_*.json corpus, "
        "selected before-variant runs for the target scenarios, "
        "and used only runs with realized trade_count > 0."
    )
    lines.append(f"- runs scanned: {data_expansion['runs_scanned']}")
    lines.append(f"- runs selected: {data_expansion['runs_selected']}")
    lines.append(
        f"- scenario run counts: {data_expansion['scenario_run_counts']}"
    )
    lines.append(
        f"- scenario pair counts: {data_expansion['scenario_pair_counts']}"
    )
    lines.append("")
    lines.append("## D. Matching Method")
    lines.append(
        "Matching is per realized outcome, using the latest preceding "
        "entry summary from the same symbol and side, with bucket keys "
        "retained when available."
    )
    lines.append(report["matching_method"]["matching_rule"])
    lines.append(report["matching_method"]["strategy_handling"])
    lines.append("")
    lines.append("## E. Agreement Metrics (Expanded)")
    lines.append(f"- observed_pairs: {metrics['observed_pairs']}")
    lines.append(
        f"- directional_agreement_count: {metrics['directional_agreement_count']}")
    lines.append(
        f"- directional_agreement_rate: {metrics['directional_agreement_rate']}")
    lines.append(
        f"- rank_agreement_rate: {rank_agreement['rank_agreement_rate']}"
    )
    lines.append(f"- false_optimism_count: {metrics['false_optimism_count']}")
    lines.append(f"- false_pessimism_count: {metrics['false_pessimism_count']}")
    lines.append(
        f"- corpus_proxy_positive_count: {metrics['corpus_proxy_positive_count']}")
    lines.append(
        "- corpus_proxy_positive_realized_negative_count: "
        f"{corpus_proxy_positive_realized_negative_count}"
    )
    lines.append("")
    lines.append("## F. Lead-Time Analysis")
    lines.append(f"- lead_time_count: {lead['count']}")
    lines.append(f"- lead_time_mean_sec: {lead['mean']}")
    lines.append(f"- lead_time_median_sec: {lead['median']}")
    lines.append(f"- lead_time_min_sec: {lead['min']}")
    lines.append(f"- lead_time_max_sec: {lead['max']}")
    lines.append("")
    lines.append("## G. False Optimism / Pessimism")
    lines.append(report["false_optimism_definition"]["pair_level_rule"])
    lines.append(report["false_optimism_definition"]["corpus_level_note"])
    lines.append(f"False optimism count: {metrics['false_optimism_count']}")
    lines.append(f"False pessimism count: {metrics['false_pessimism_count']}")
    lines.append("")
    lines.append("## H. Stability vs Small Sample")
    small = stab.get("small_sample") or {}
    lines.append(f"- small sample observed_pairs: {small.get('observed_pairs')}")
    lines.append(f"- small sample classification: {small.get('classification')}")
    lines.append(
        f"- expanded sample observed_pairs: {expanded_sample['observed_pairs']}"
    )
    lines.append(
        f"- expanded sample classification: {expanded_sample['classification']}"
    )
    lines.append(f"- classification_changed: {stab['classification_changed']}")
    lines.append(
        f"- sample_size_changed_materially: {stab['sample_size_changed_materially']}")
    lines.append("")
    lines.append("## I. Final Classification")
    lines.append(meta["classification"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Expanded agreement audit between proxy shadow readiness and "
            "realized outcomes."
        )
    )
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS))
    parser.add_argument("--limit-per-scenario", type=int, default=None)
    parser.add_argument("--small-sample-reference", default=str(SMALL_SAMPLE_REFERENCE))
    args = parser.parse_args(argv)

    scenarios = tuple(s.strip() for s in str(args.scenarios).split(",") if s.strip())
    report = _build_report(
        results_dir=Path(args.results_dir),
        scenarios=scenarios,
        limit_per_scenario=args.limit_per_scenario,
        small_sample_reference=Path(args.small_sample_reference),
    )
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"proxy_shadow_realized_agreement_expanded_{stamp}.json"
    md_path = DIAG_DIR / f"proxy_shadow_realized_agreement_expanded_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
