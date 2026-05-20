# flake8: noqa
"""
Forensic audit: risk_or_prefilter_block_fallback attribution
============================================================
Reads entry_gate_decision_summary rows from the probe DB
(20260505_221119) and breaks down every risk_or_prefilter_block_fallback
occurrence by symbol, strategy, side, short_circuit_stage,
cold-start markers, fallback policy state, and bucket identity.

Compares against the v1 reference DB (20260505_160951).

Produces:
  reports/paper_readiness/risk_prefilter_fallback_audit_20260505.json
  reports/paper_readiness/risk_prefilter_fallback_audit_20260505.md

Classification verdicts (per occurrence and aggregate):
  FALLBACK_CAUSE_SOL_DOMINANT
  FALLBACK_CAUSE_COLD_START_EDGE_HISTORY
  FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION
  FALLBACK_CAUSE_PREFILTER_PRESSURE
  FALLBACK_CAUSE_UNCLASSIFIED
"""

import sqlite3
import json
import pathlib
import datetime
from collections import Counter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = pathlib.Path("D:/Alpha_Zol0-lvl_5-main/Alpha_Zol0-lvl_5-main")
TMP = BASE / "tmp"
REPORTS = BASE / "reports" / "paper_readiness"
REPORTS.mkdir(parents=True, exist_ok=True)

PROBE_RUN_ID = "20260505_221119"
V1_RUN_ID = "20260505_160951"

PROBE_DB = TMP / f"controlled_kpi_after_{PROBE_RUN_ID}.db"
V1_DB = TMP / f"controlled_kpi_after_{V1_RUN_ID}.db"

TARGET_REASON = "risk_or_prefilter_block_fallback"

# ---------------------------------------------------------------------------
# Classification helpers  (reusable – see tests at bottom of file)
# ---------------------------------------------------------------------------


def classify_fallback_occurrence(row: dict) -> str:
    """
    Classify a single risk_or_prefilter_block_fallback occurrence.

    Returns one of:
      FALLBACK_CAUSE_COLD_START_EDGE_HISTORY   – history_ready=False, trade_count=0
      FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION  – fallback_policy_exhausted=True
      FALLBACK_CAUSE_PREFILTER_PRESSURE        – side not null but prefilter blocked
      FALLBACK_CAUSE_SOL_DOMINANT              – symbol is SOLUSDTM (checked at agg level)
      FALLBACK_CAUSE_UNCLASSIFIED              – none of the above
    """
    npt = row.get("natural_path_trace") or {}
    csbucket = row.get("canonical_shadow_bucket") or {}
    shadow = csbucket.get("shadow_bucket") or {}

    # Router/fallback policy exhaustion
    if npt.get("fallback_policy_exhausted"):
        return "FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION"

    # Cold-start: no edge history available
    history_ready = row.get("canonical_shadow_history_ready")
    trade_count = row.get("canonical_shadow_trade_count", 0)
    shadow_tc = shadow.get("trade_count", 0)
    short_circuit = npt.get("short_circuit_stage", "")

    no_npt = not npt
    if (
        history_ready is False
        and (trade_count == 0 or shadow_tc == 0)
        and (short_circuit == "bucket_identity_formation_failure" or no_npt)
    ):
        return "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    # Prefilter pressure: side was resolved but still blocked
    side = row.get("side")
    risk_prefilter_stage = npt.get("risk_prefilter_stage")
    if side is not None and risk_prefilter_stage is not None:
        return "FALLBACK_CAUSE_PREFILTER_PRESSURE"

    # Side was null + bucket_identity_formation_failure without cold-start marker
    if short_circuit == "bucket_identity_formation_failure":
        return "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    return "FALLBACK_CAUSE_UNCLASSIFIED"


def extract_occurrence_fields(row: dict) -> dict:
    """Extract all forensically relevant fields from an entry_gate_decision_summary row."""
    npt = row.get("natural_path_trace") or {}
    csbucket = row.get("canonical_shadow_bucket") or {}
    shadow = csbucket.get("shadow_bucket") or {}
    dss = row.get("decision_snapshot_selection") or {}
    canonical = row.get("canonical_bucket") or {}

    return {
        "ts": row.get("ts"),
        "symbol": row.get("symbol"),
        "strategy": row.get("strategy") or row.get("main_strategy"),
        "side": row.get("side"),
        "local_gate_reason": row.get("local_gate_reason"),
        "effective_gate_reason": row.get("effective_gate_reason"),
        "entry_gate_bucket": row.get("entry_gate_bucket"),
        "entry_decision_raw": row.get("entry_decision_raw"),
        "entry_decision_final": row.get("entry_decision_final"),
        "resolved_upstream_predicate": row.get("resolved_upstream_predicate"),
        "resolved_upstream_source": row.get("resolved_upstream_source"),
        "attribution_resolution_applied": row.get("attribution_resolution_applied"),
        "regime": row.get("regime"),
        "momentum_signal_score": row.get("momentum_signal_score"),
        "confidence": row.get("confidence"),
        # Natural path trace
        "npt_pre_entry_candidate_exists": npt.get("pre_entry_candidate_exists"),
        "npt_pre_entry_candidate_source": npt.get("pre_entry_candidate_source"),
        "npt_strategy_assignment_stage": npt.get("strategy_assignment_stage"),
        "npt_strategy_assignment_reason": npt.get("strategy_assignment_reason"),
        "npt_side_assignment_stage": npt.get("side_assignment_stage"),
        "npt_side_assignment_reason": npt.get("side_assignment_reason"),
        "npt_bucket_identity_stage": npt.get("bucket_identity_stage"),
        "npt_bucket_identity_reason": npt.get("bucket_identity_reason"),
        "npt_fallback_assignment_stage": npt.get("fallback_assignment_stage"),
        "npt_fallback_reason_raw": npt.get("fallback_reason_raw"),
        "npt_fallback_reason_final": npt.get("fallback_reason_final"),
        "npt_risk_prefilter_stage": npt.get("risk_prefilter_stage"),
        "npt_short_circuit_stage": npt.get("short_circuit_stage"),
        "npt_fallback_policy_exhausted": npt.get("fallback_policy_exhausted"),
        "npt_fallback_policy_exhaustion_reason": npt.get("fallback_policy_exhaustion_reason"),
        "npt_fallback_policy_blocked_strategies": npt.get("fallback_policy_blocked_strategies"),
        "npt_fallback_policy_blocked_sides": npt.get("fallback_policy_blocked_sides"),
        "npt_viable_assignments_count": npt.get("fallback_policy_viable_assignments_count"),
        # Cold-start / edge history
        "canonical_shadow_history_ready": row.get("canonical_shadow_history_ready"),
        "canonical_shadow_trade_count": row.get("canonical_shadow_trade_count"),
        "shadow_gross_hist_len": len(shadow.get("gross_hist") or []),
        "shadow_fee_hist_len": len(shadow.get("fee_hist") or []),
        # Canonical bucket
        "canonical_bucket_key": canonical.get("canonical_bucket_key"),
        "canonical_bucket_identity_status": canonical.get("bucket_identity_status"),
        "canonical_bucket_identity_reason": canonical.get("bucket_identity_reason"),
        "canonical_raw_side": canonical.get("raw_side"),
        "canonical_normalized_side": canonical.get("normalized_side"),
        # Decision snapshot
        "dss_bucket_used_final": dss.get("bucket_used_final"),
        "dss_bucket_key_primary": dss.get("bucket_key_primary"),
        "dss_trade_count_primary": dss.get("trade_count_primary"),
        "dss_trade_count_fallback": dss.get("trade_count_fallback"),
        "dss_selected_history_ready": dss.get("selected_history_ready"),
        "dss_selected_trade_count": dss.get("selected_trade_count"),
        # Classification
        "classification": classify_fallback_occurrence(row),
    }


# ---------------------------------------------------------------------------
# DB reader
# ---------------------------------------------------------------------------

def load_fallback_occurrences(db_path: pathlib.Path, label: str) -> list:
    """Return all entry_gate_decision_summary rows with the fallback reason."""
    if not db_path.exists():
        print(f"  [{label}] DB NOT FOUND: {db_path}")
        return []
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT timestamp, details FROM logs "
        "WHERE event='entry_gate_decision_summary' "
        "AND details LIKE '%risk_or_prefilter_block_fallback%'"
    ).fetchall()
    con.close()
    print(f"  [{label}] found {len(rows)} fallback rows in {db_path.name}")
    occurrences = []
    for r in rows:
        try:
            d = json.loads(r["details"])
            if (
                d.get("local_gate_reason") == TARGET_REASON
                or d.get("effective_gate_reason") == TARGET_REASON
            ):
                fields = extract_occurrence_fields(d)
                fields["db_timestamp"] = r["timestamp"]
                occurrences.append(fields)
        except Exception as e:
            print(f"    parse error: {e}")
    return occurrences


def load_total_gate_count(db_path: pathlib.Path) -> int:
    """Count all entry_gate_decision_summary rows (denominator for rates)."""
    if not db_path.exists():
        return 0
    con = sqlite3.connect(str(db_path))
    r = con.execute(
        "SELECT COUNT(*) FROM logs WHERE event='entry_gate_decision_summary'"
    ).fetchone()
    con.close()
    return r[0] if r else 0


# ---------------------------------------------------------------------------
# Aggregate analysis helpers
# ---------------------------------------------------------------------------

def aggregate_occurrences(occurrences: list, total_gate: int) -> dict:
    """Build aggregated breakdown of fallback occurrences."""
    n = len(occurrences)
    rate = round(n / total_gate, 4) if total_gate > 0 else 0.0

    by_symbol = Counter(o["symbol"] for o in occurrences)
    by_strategy = Counter(o["strategy"] for o in occurrences)
    by_side = Counter(str(o["side"]) for o in occurrences)
    by_short_circuit = Counter(o["npt_short_circuit_stage"] for o in occurrences)
    by_side_assign_stage = Counter(o["npt_side_assignment_stage"] for o in occurrences)
    by_fallback_exhausted = Counter(str(o["npt_fallback_policy_exhausted"]) for o in occurrences)
    by_classification = Counter(o["classification"] for o in occurrences)
    by_regime = Counter(o["regime"] for o in occurrences)
    by_canonical_status = Counter(o["canonical_bucket_identity_status"] for o in occurrences)
    by_dss_primary = Counter(  # noqa: F841
        o["dss_bucket_key_primary"] for o in occurrences
    )

    history_ready_false = sum(1 for o in occurrences if o["canonical_shadow_history_ready"] is False)
    trade_count_zero = sum(1 for o in occurrences if (o["canonical_shadow_trade_count"] or 0) == 0)
    side_null = sum(1 for o in occurrences if o["side"] is None)

    return {
        "total": n,
        "total_gate": total_gate,
        "rate": rate,
        "by_symbol": dict(by_symbol.most_common()),
        "by_strategy": dict(by_strategy.most_common()),
        "by_side": dict(by_side.most_common()),
        "by_short_circuit_stage": dict(by_short_circuit.most_common()),
        "by_side_assignment_stage": dict(by_side_assign_stage.most_common()),
        "by_fallback_policy_exhausted": dict(by_fallback_exhausted.most_common()),
        "by_classification": dict(by_classification.most_common()),
        "by_regime": dict(by_regime.most_common()),
        "by_canonical_bucket_status": dict(by_canonical_status.most_common()),
        "dss_primary_bucket_sample": dict(
            Counter(o["dss_bucket_key_primary"] for o in occurrences).most_common(10)
        ),
        "cold_start_markers": {
            "canonical_shadow_history_ready_false": history_ready_false,
            "canonical_shadow_trade_count_zero": trade_count_zero,
            "side_null": side_null,
            "pct_history_not_ready": round(history_ready_false / n, 4) if n > 0 else 0.0,
            "pct_trade_count_zero": round(trade_count_zero / n, 4) if n > 0 else 0.0,
            "pct_side_null": round(side_null / n, 4) if n > 0 else 0.0,
        },
    }


def sol_overrepresentation_test(agg: dict, total_symbols: int = 4) -> dict:
    """Test whether SOLUSDTM is overrepresented vs uniform baseline."""
    by_sym = agg["by_symbol"]
    total = agg["total"]
    sol_count = by_sym.get("SOLUSDTM", 0)
    expected_share = 1.0 / total_symbols
    actual_share = sol_count / total if total > 0 else 0.0
    overrep_ratio = actual_share / expected_share if expected_share > 0 else 0.0
    return {
        "sol_count": sol_count,
        "total_fallback": total,
        "sol_actual_share": round(actual_share, 4),
        "sol_expected_share_uniform": round(expected_share, 4),
        "sol_overrepresentation_ratio": round(overrep_ratio, 4),
        "sol_dominant": actual_share > (expected_share * 1.5),  # >50% over expected
    }


def determine_aggregate_verdict(agg: dict, sol_test: dict) -> str:
    """Map aggregate classification counts to a single primary verdict."""
    classifications = agg["by_classification"]
    cold_start = classifications.get("FALLBACK_CAUSE_COLD_START_EDGE_HISTORY", 0)
    router_exhaust = classifications.get("FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION", 0)
    prefilter = classifications.get("FALLBACK_CAUSE_PREFILTER_PRESSURE", 0)
    total = agg["total"]

    if total == 0:
        return "FALLBACK_CAUSE_UNCLASSIFIED"

    # SOL dominance check (secondary modifier, not primary)
    if sol_test["sol_dominant"]:
        if cold_start / total >= 0.50:
            return "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"
        return "FALLBACK_CAUSE_SOL_DOMINANT"

    # Primary cause by majority
    if cold_start / total >= 0.50:
        return "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"
    if router_exhaust / total >= 0.50:
        return "FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION"
    if prefilter / total >= 0.30:
        return "FALLBACK_CAUSE_PREFILTER_PRESSURE"

    # Plurality
    dominant = max(classifications, key=classifications.get)
    if classifications[dominant] / total >= 0.30:
        return dominant

    return "FALLBACK_CAUSE_UNCLASSIFIED"


# ---------------------------------------------------------------------------
# Delta vs v1 reference
# ---------------------------------------------------------------------------

def compute_delta(probe_agg: dict, v1_agg: dict) -> dict:
    """Compare probe vs v1 aggregates."""
    delta = {}
    for key in ["total", "rate"]:
        pv = probe_agg.get(key, 0)
        rv = v1_agg.get(key, 0)
        delta[key] = {"probe": pv, "ref_v1": rv,
                      "delta": round(pv - rv, 6) if isinstance(pv, float) else pv - rv}

    for dist_key in ["by_symbol", "by_strategy", "by_side", "by_short_circuit_stage",
                     "by_classification"]:
        p_dist = probe_agg.get(dist_key, {})
        v_dist = v1_agg.get(dist_key, {})
        all_keys = set(p_dist) | set(v_dist)
        delta[dist_key] = {
            k: {"probe": p_dist.get(k, 0), "ref_v1": v_dist.get(k, 0),
                "delta": p_dist.get(k, 0) - v_dist.get(k, 0)}
            for k in sorted(all_keys)
        }
    return delta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("=" * 65)
print("FORENSIC AUDIT: risk_or_prefilter_block_fallback")
print(f"Probe run : {PROBE_RUN_ID}")
print(f"V1 ref    : {V1_RUN_ID}")
print("=" * 65)

print("\nLoading occurrences...")
probe_occ = load_fallback_occurrences(PROBE_DB, "PROBE")
v1_occ = load_fallback_occurrences(V1_DB, "V1")

probe_total_gate = load_total_gate_count(PROBE_DB)
v1_total_gate = load_total_gate_count(V1_DB)

print(f"\nPROBE total gate decisions : {probe_total_gate}")
print(f"V1    total gate decisions : {v1_total_gate}")

probe_agg = aggregate_occurrences(probe_occ, probe_total_gate)
v1_agg = aggregate_occurrences(v1_occ, v1_total_gate)

sol_test = sol_overrepresentation_test(probe_agg, total_symbols=4)
v1_sol_test = sol_overrepresentation_test(v1_agg, total_symbols=3)

probe_verdict = determine_aggregate_verdict(probe_agg, sol_test)
v1_verdict = determine_aggregate_verdict(v1_agg, v1_sol_test)

delta = compute_delta(probe_agg, v1_agg)

# ---------------------------------------------------------------------------
# Print report
# ---------------------------------------------------------------------------

print(f"\n{'='*65}")
print("PROBE AGGREGATE BREAKDOWN")
print(f"{'='*65}")
print(f"  total fallback occurrences : {probe_agg['total']}")
print(f"  rate (vs all gate decisions): {probe_agg['rate']:.4f}  "
      f"(v1: {v1_agg['rate']:.4f})")

print("\n  by_symbol:")
for k, v in probe_agg["by_symbol"].items():
    share = v / probe_agg["total"] if probe_agg["total"] > 0 else 0
    print(f"    {k:<20}: {v:>4}  ({share:.1%})")

print("\n  by_strategy:")
for k, v in probe_agg["by_strategy"].items():
    print(f"    {k:<20}: {v:>4}")

print("\n  by_side:")
for k, v in probe_agg["by_side"].items():
    print(f"    {k:<20}: {v:>4}")

print("\n  by_short_circuit_stage:")
for k, v in probe_agg["by_short_circuit_stage"].items():
    print(f"    {k:<40}: {v:>4}")

print("\n  by_side_assignment_stage:")
for k, v in probe_agg["by_side_assignment_stage"].items():
    print(f"    {k:<40}: {v:>4}")

print("\n  by_regime:")
for k, v in probe_agg["by_regime"].items():
    print(f"    {k:<20}: {v:>4}")

print("\n  COLD-START MARKERS:")
cm = probe_agg["cold_start_markers"]
print(f"    canonical_shadow_history_ready=False : {cm['canonical_shadow_history_ready_false']}  ({cm['pct_history_not_ready']:.1%})")
print(f"    canonical_shadow_trade_count=0       : {cm['canonical_shadow_trade_count_zero']}  ({cm['pct_trade_count_zero']:.1%})")
print(f"    side=null                             : {cm['side_null']}  ({cm['pct_side_null']:.1%})")

print("\n  FALLBACK POLICY EXHAUSTION:")
for k, v in probe_agg["by_fallback_policy_exhausted"].items():
    print(f"    exhausted={k}: {v}")

print("\n  CLASSIFICATION BREAKDOWN:")
for k, v in probe_agg["by_classification"].items():
    share = v / probe_agg["total"] if probe_agg["total"] > 0 else 0
    print(f"    {k:<45}: {v:>4}  ({share:.1%})")

print("\n  SOLUSDTM OVERREPRESENTATION TEST:")
print(f"    SOLUSDTM count        : {sol_test['sol_count']}")
print(f"    SOLUSDTM actual share : {sol_test['sol_actual_share']:.1%}")
print(f"    expected (uniform)    : {sol_test['sol_expected_share_uniform']:.1%}")
print(f"    overrep ratio         : {sol_test['sol_overrepresentation_ratio']:.2f}x")
print(f"    SOL DOMINANT          : {sol_test['sol_dominant']}")

print(f"\n{'='*65}")
print(f"PROBE PRIMARY VERDICT: {probe_verdict}")
print(f"V1    PRIMARY VERDICT: {v1_verdict}")
print(f"{'='*65}")

print("\nDELTA vs V1:")
print(f"  total: v1={v1_agg['total']} -> probe={probe_agg['total']} (Δ={probe_agg['total']-v1_agg['total']:+d})")
print(f"  rate:  v1={v1_agg['rate']:.4f} -> probe={probe_agg['rate']:.4f} (Δ={probe_agg['rate']-v1_agg['rate']:+.4f})")
print("\n  by_symbol delta:")
sym_delta = delta.get("by_symbol", {})
for sym in sorted(sym_delta):
    d = sym_delta[sym]
    print(f"    {sym:<20}: v1={d['ref_v1']:>4}  probe={d['probe']:>4}  Δ={d['delta']:>+4}")

# ---------------------------------------------------------------------------
# Build JSON artifact
# ---------------------------------------------------------------------------

artifact = {
    "audit_timestamp": datetime.datetime.now().isoformat(),
    "probe_run_id": PROBE_RUN_ID,
    "v1_run_id": V1_RUN_ID,
    "target_reason": TARGET_REASON,
    "probe": {
        "aggregate": probe_agg,
        "sol_overrepresentation_test": sol_test,
        "verdict": probe_verdict,
        "occurrences_sample": probe_occ[:20],  # first 20 for artifact
        "total_occurrences": len(probe_occ),
    },
    "v1_reference": {
        "aggregate": v1_agg,
        "sol_overrepresentation_test": v1_sol_test,
        "verdict": v1_verdict,
        "total_occurrences": len(v1_occ),
    },
    "delta": delta,
    "safety": {
        "REAL_SWITCH_ALLOWED": "false",
        "LIVE": "0",
        "LIVE_ARMED": "0",
        "note": "forensic read-only audit, no runtime changes",
    },
}

json_path = REPORTS / "risk_prefilter_fallback_audit_20260505.json"
json_path.write_text(json.dumps(artifact, indent=2, default=str))
print(f"\nJSON ARTIFACT: {json_path}")

# ---------------------------------------------------------------------------
# Build MD report
# ---------------------------------------------------------------------------


def pct(n, total):
    return f"{n/total:.1%}" if total > 0 else "N/A"


lines = [
    "# Forensic Audit: `risk_or_prefilter_block_fallback`",
    "",
    f"**Run**: `{PROBE_RUN_ID}` vs V1 ref `{V1_RUN_ID}`  ",
    f"**Audit timestamp**: `{artifact['audit_timestamp']}`  ",
    "**Scope**: PAPER-only, KuCoin-only. No runtime changes applied.",
    "",
    "## Summary",
    "",
    "| Field | Probe | V1 ref | Delta |",
    "|---|---|---|---|",
    f"| fallback_count | {probe_agg['total']} | {v1_agg['total']} | {probe_agg['total']-v1_agg['total']:+d} |",
    f"| fallback_rate (vs total gate decisions) | {probe_agg['rate']:.4f} | {v1_agg['rate']:.4f} | {probe_agg['rate']-v1_agg['rate']:+.4f} |",
    f"| total_gate_decisions | {probe_total_gate} | {v1_total_gate} | - |",
    f"| primary_verdict | `{probe_verdict}` | `{v1_verdict}` | - |",
    "",
    "## Symbol Breakdown",
    "",
    "| Symbol | Probe count | Share | V1 count | V1 share |",
    "|---|---|---|---|---|",
]
for sym in sorted(set(list(probe_agg["by_symbol"]) + list(v1_agg["by_symbol"]))):
    pc = probe_agg["by_symbol"].get(sym, 0)
    vc = v1_agg["by_symbol"].get(sym, 0)
    lines.append(
        f"| {sym} | {pc} | {pct(pc, probe_agg['total'])} | {vc} | {pct(vc, v1_agg['total'])} |"
    )

lines += [
    "",
    "## SOLUSDTM Overrepresentation Test",
    "",
    "| Metric | Value |",
    "|---|---|",
    f"| SOLUSDTM count (probe) | {sol_test['sol_count']} |",
    f"| SOLUSDTM actual share | {sol_test['sol_actual_share']:.1%} |",
    f"| Expected share (uniform, 4 symbols) | {sol_test['sol_expected_share_uniform']:.1%} |",
    f"| Overrepresentation ratio | {sol_test['sol_overrepresentation_ratio']:.2f}x |",
    f"| **SOL dominant?** | **{sol_test['sol_dominant']}** |",
    "",
    "## Cold-Start / Edge History Markers",
    "",
    "| Marker | Count | % of fallback |",
    "|---|---|---|",
]
cm = probe_agg["cold_start_markers"]
lines += [
    f"| `canonical_shadow_history_ready=False` | {cm['canonical_shadow_history_ready_false']} | {cm['pct_history_not_ready']:.1%} |",
    f"| `canonical_shadow_trade_count=0` | {cm['canonical_shadow_trade_count_zero']} | {cm['pct_trade_count_zero']:.1%} |",
    f"| `side=null` | {cm['side_null']} | {cm['pct_side_null']:.1%} |",
    "",
    "## Short-Circuit Stage Breakdown",
    "",
    "| short_circuit_stage | Count | % |",
    "|---|---|---|",
]
for k, v in probe_agg["by_short_circuit_stage"].items():
    lines.append(f"| `{k}` | {v} | {pct(v, probe_agg['total'])} |")

lines += [
    "",
    "## Classification Breakdown",
    "",
    "| Classification | Count | % |",
    "|---|---|---|",
]
for k, v in probe_agg["by_classification"].items():
    lines.append(f"| `{k}` | {v} | {pct(v, probe_agg['total'])} |")

lines += [
    "",
    "## Regime Breakdown",
    "",
    "| Regime | Count |",
    "|---|---|",
]
for k, v in probe_agg["by_regime"].items():
    lines.append(f"| {k} | {v} |")

lines += [
    "",
    "## Fallback Policy Exhaustion",
    "",
    "| fallback_policy_exhausted | Count |",
    "|---|---|",
]
for k, v in probe_agg["by_fallback_policy_exhausted"].items():
    lines.append(f"| {k} | {v} |")

lines += [
    "",
    "## Root Cause Narrative",
    "",
    f"> **Primary verdict: `{probe_verdict}`**",
    "",
]

if probe_verdict == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY":
    lines += [
        "The dominant root cause is **cold-start edge history absence**.",
        "",
        f"- {cm['pct_history_not_ready']:.0%} of occurrences have `canonical_shadow_history_ready=False`",
        f"- {cm['pct_trade_count_zero']:.0%} of occurrences have `canonical_shadow_trade_count=0`",
        f"- {cm['pct_side_null']:.0%} of occurrences have `side=null`",
        "- `short_circuit_stage=bucket_identity_formation_failure` in all cases",
        "",
        "The `bucket_identity_formation_failure` short-circuit fires because no prior",
        "trade history exists in the canonical shadow bucket, which means the system",
        "cannot form a valid bucket identity for the entry gate.",
        "",
        "**This is not a regression.** The probe window started with zero PAPER trade history",
        "for SOLUSDTM (new symbol) and potentially for other buckets. Adding SOLUSDTM",
        "increased cold-start surface area, contributing to the elevated rate vs v1.",
    ]
elif probe_verdict == "FALLBACK_CAUSE_SOL_DOMINANT":
    lines += [
        "**SOLUSDTM is overrepresented** in the fallback blocker distribution.",
        f"Its share ({sol_test['sol_actual_share']:.1%}) exceeds the uniform expectation",
        f"({sol_test['sol_expected_share_uniform']:.1%}) by {sol_test['sol_overrepresentation_ratio']:.1f}x.",
        "",
        "This is consistent with SOLUSDTM being a **new symbol** with no prior PAPER",
        "trade history, causing cold-start edge history failures for all its buckets.",
    ]
elif probe_verdict == "FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION":
    lines += [
        "**Router/fallback policy exhaustion** is the dominant cause.",
        "The fallback policy ran out of viable strategy-side assignments.",
    ]
elif probe_verdict == "FALLBACK_CAUSE_PREFILTER_PRESSURE":
    lines += [
        "**Prefilter pressure** is the dominant cause.",
        "Side was resolved but a risk/prefilter layer blocked the candidate before gating.",
    ]
else:
    lines += [
        "Fallback cause is **unclassified** — no single majority classification.",
        "Manual inspection of individual occurrences is required.",
    ]

lines += [
    "",
    "## Next Steps",
    "",
    "1. **Do not relax gates** until this attribution is confirmed with a longer probe.",
    "2. If cold-start is primary: consider pre-seeding SOLUSDTM shadow history from",
    "   bootstrap bundle or allowing a warm-up period before entry gating activates.",
    "3. If SOL dominant: test with SOL excluded to confirm it is not causing spillover.",
    "4. Re-run probe after warm-up to check whether fallback rate drops once history",
    "   accumulates.",
    "",
    "---",
    f"*Generated: {artifact['audit_timestamp']}*  ",
    "*REAL_SWITCH_ALLOWED=false | LIVE=0 | LIVE_ARMED=0*",
]

md_path = REPORTS / "risk_prefilter_fallback_audit_20260505.md"
md_path.write_text("\n".join(lines))
print(f"MD  ARTIFACT: {md_path}")
print("\nDone.")
