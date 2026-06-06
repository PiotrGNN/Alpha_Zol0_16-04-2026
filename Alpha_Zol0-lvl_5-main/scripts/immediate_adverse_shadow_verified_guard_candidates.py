from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


TERMINAL_EVENT = "immediate_adverse_shadow_outcome"
LOSS_CLASS = "IMMEDIATE_ADVERSE_LOSS"
WINNER_CLASS = "MISSED_WINNER"
OPEN_OR_SPARSE_CLASSES = {
    "SHADOW_OPEN_AT_SHUTDOWN",
    "SHADOW_EXPIRED_NO_TERMINAL_MOVE",
    "SHADOW_INSUFFICIENT_QUOTES",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _classification(row: Dict[str, Any]) -> str:
    return str(
        row.get("terminal_classification")
        or row.get("shadow_outcome_classification")
        or ""
    )


def _proxy_net(row: Dict[str, Any]) -> float:
    return _safe_float(
        row.get("proxy_net_result", row.get("realized_proxy_net", 0.0)),
        0.0,
    )


def _rule_key(row: Dict[str, Any]) -> str:
    return (
        f"{str(row.get('symbol') or '').strip().upper()}:"
        f"{str(row.get('side') or '').strip().lower()}:"
        f"{str(row.get('strategy') or '').strip()}"
    )


def _evaluate_group(rule_key: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = Counter(_classification(row) for row in rows)
    terminal_count = len(rows)
    missed_winner_net = sum(
        max(0.0, _proxy_net(row))
        for row in rows
        if _classification(row) == WINNER_CLASS
    )
    immediate_adverse_loss_net = sum(
        min(0.0, _proxy_net(row))
        for row in rows
        if _classification(row) == LOSS_CLASS
    )
    avoided_loss_proxy_net_abs = abs(immediate_adverse_loss_net)
    missed_winner_count = int(counts.get(WINNER_CLASS, 0))
    immediate_adverse_loss_count = int(counts.get(LOSS_CLASS, 0))
    sparse_or_open_count = sum(int(counts.get(key, 0)) for key in OPEN_OR_SPARSE_CLASSES)
    missed_winner_rate = (
        missed_winner_count / terminal_count if terminal_count > 0 else 1.0
    )
    sparse_or_open_rate = sparse_or_open_count / terminal_count if terminal_count else 1.0
    net_shadow_benefit = avoided_loss_proxy_net_abs - missed_winner_net

    failed_criteria: List[str] = []
    if terminal_count < 10:
        failed_criteria.append("terminal_outcome_count_lt_10")
    if immediate_adverse_loss_count < 3:
        failed_criteria.append("immediate_adverse_loss_count_lt_3")
    if missed_winner_rate > 0.35:
        failed_criteria.append("missed_winner_rate_gt_0.35")
    if net_shadow_benefit <= 0.0:
        failed_criteria.append("net_shadow_benefit_nonpositive")
    if avoided_loss_proxy_net_abs <= missed_winner_net:
        failed_criteria.append("avoided_loss_not_gt_missed_winner_proxy_net")
    if sparse_or_open_rate >= 0.50:
        failed_criteria.append("sparse_or_open_artifact_dominates")
    if rule_key.count(":") != 2 or any(not part for part in rule_key.split(":")):
        failed_criteria.append("rule_not_exact_symbol_side_strategy")

    return {
        "rule_key": rule_key,
        "rule_scope": "symbol_side_strategy",
        "terminal_outcome_count": terminal_count,
        "classification_counts": dict(sorted(counts.items())),
        "immediate_adverse_loss_count": immediate_adverse_loss_count,
        "missed_winner_count": missed_winner_count,
        "sparse_or_open_count": sparse_or_open_count,
        "missed_winner_rate": missed_winner_rate,
        "sparse_or_open_rate": sparse_or_open_rate,
        "missed_winner_proxy_net": missed_winner_net,
        "immediate_adverse_loss_proxy_net": immediate_adverse_loss_net,
        "avoided_loss_proxy_net_abs": avoided_loss_proxy_net_abs,
        "net_shadow_benefit": net_shadow_benefit,
        "failed_criteria": failed_criteria,
        "passed": not failed_criteria,
    }


def evaluate_guard_candidates(outcomes: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    valid_outcomes = [dict(row) for row in outcomes if _rule_key(dict(row)).count(":") == 2]
    for row in valid_outcomes:
        grouped[_rule_key(row)].append(row)

    candidates = [_evaluate_group(key, rows) for key, rows in grouped.items()]
    candidates.sort(
        key=lambda item: (
            not bool(item["passed"]),
            -float(item["net_shadow_benefit"]),
            -int(item["terminal_outcome_count"]),
            str(item["rule_key"]),
        )
    )
    passed = [candidate for candidate in candidates if candidate["passed"]]
    return {
        "final_classification": (
            "SHADOW_VERIFIED_GUARD_RULE_FOUND"
            if passed
            else "NO_SHADOW_VERIFIED_GUARD_RULE_FOUND"
        ),
        "terminal_outcome_count": len(valid_outcomes),
        "candidate_count": len(candidates),
        "passed_candidate_count": len(passed),
        "candidates": candidates,
    }


def load_shadow_outcomes_from_db(db_path: Path) -> List[Dict[str, Any]]:
    with sqlite3.connect(str(db_path)) as connection:
        rows = connection.execute(
            "select details from logs where event = ? order by id",
            (TERMINAL_EVENT,),
        ).fetchall()
    outcomes: List[Dict[str, Any]] = []
    for (details,) in rows:
        try:
            payload = json.loads(details or "{}")
        except Exception:
            continue
        if isinstance(payload, dict):
            outcomes.append(payload)
    return outcomes


def render_markdown(report: Dict[str, Any], *, db_path: Path, json_path: Path | None) -> str:
    lines = [
        "# Immediate Adverse Shadow Verified Guard Candidates",
        "",
        f"- db: `{db_path}`",
        f"- source_json: `{json_path}`" if json_path else "- source_json: null",
        f"- final_classification: `{report['final_classification']}`",
        f"- terminal_outcome_count: {report['terminal_outcome_count']}",
        f"- candidate_count: {report['candidate_count']}",
        f"- passed_candidate_count: {report['passed_candidate_count']}",
        "",
        "## Candidates",
        "",
    ]
    if not report["candidates"]:
        lines.append("- no candidates")
    for candidate in report["candidates"]:
        lines.extend(
            [
                f"### `{candidate['rule_key']}`",
                f"- passed: {candidate['passed']}",
                f"- terminal_outcome_count: {candidate['terminal_outcome_count']}",
                f"- classification_counts: `{candidate['classification_counts']}`",
                f"- missed_winner_rate: {candidate['missed_winner_rate']:.6f}",
                f"- avoided_loss_proxy_net_abs: {candidate['avoided_loss_proxy_net_abs']:.12f}",
                f"- missed_winner_proxy_net: {candidate['missed_winner_proxy_net']:.12f}",
                f"- net_shadow_benefit: {candidate['net_shadow_benefit']:.12f}",
                f"- failed_criteria: `{candidate['failed_criteria']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--json", default=None)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()

    db_path = Path(args.db)
    json_path = Path(args.json) if args.json else None
    outcomes = load_shadow_outcomes_from_db(db_path)
    report = evaluate_guard_candidates(outcomes)
    report["source_db"] = str(db_path)
    report["source_json"] = str(json_path) if json_path else None

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(
        render_markdown(report, db_path=db_path, json_path=json_path),
        encoding="utf-8",
    )
    print(json.dumps({"out_json": str(out_json), "out_md": str(out_md), **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
