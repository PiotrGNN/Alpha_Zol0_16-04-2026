import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _decision_for_patch(
    row: dict[str, Any],
    runtime_target_pass: bool,
) -> dict[str, Any]:
    patch_id = str(row.get("patch_id") or "")
    subprocess_rc = _safe_int(row.get("subprocess_returncode"), 0)
    after = row.get("after") or {}
    process_rc = _safe_int(after.get("process_returncode"), 0)
    delta_pf = _safe_float(row.get("delta_profit_factor_vs_baseline"), 0.0)
    net_pnl = _safe_float(row.get("net_pnl"), 0.0)
    real_pf_gain = bool(row.get("real_pf_gain"))

    hard_runner_ok = subprocess_rc == 0 and process_rc == 0
    hard_promote = bool(
        patch_id != "baseline_locked"
        and hard_runner_ok
        and runtime_target_pass
        and real_pf_gain
        and net_pnl >= 0.0
    )

    hard_rollback = bool(
        patch_id != "baseline_locked"
        and (subprocess_rc != 0 and delta_pf <= 0.0)
        or (net_pnl < 0.0 and delta_pf < 0.0 and not runtime_target_pass)
    )

    if patch_id == "baseline_locked":
        action = "hold"
        reason = "baseline_reference"
    elif hard_promote:
        action = "promote"
        reason = "all_hard_gates_passed"
    elif hard_rollback:
        action = "rollback"
        reason = "hard_gate_failure_with_negative_delta"
    else:
        action = "hold"
        reason = "insufficient_hard_gate_confirmation"

    return {
        "patch_id": patch_id,
        "action": action,
        "reason": reason,
        "subprocess_returncode": subprocess_rc,
        "process_returncode": process_rc,
        "runtime_target_pass": bool(runtime_target_pass),
        "real_pf_gain": bool(real_pf_gain),
        "delta_profit_factor_vs_baseline": float(delta_pf),
        "net_pnl": float(net_pnl),
    }


def _render_md(payload: dict[str, Any]) -> str:
    lines = []
    lines.append("# Hard Rollout Gates")
    lines.append("")
    lines.append("## Decisions")
    for row in payload.get("decisions") or []:
        lines.append(
            f"- {row['patch_id']}: action={row['action']} reason={row['reason']} "
            f"subprocess_rc={row['subprocess_returncode']} "
            f"process_rc={row['process_returncode']}"
        )
    lines.append("")
    rec = payload.get("recommendation") or {}
    lines.append("## Recommendation")
    lines.append(f"- patch: {rec.get('patch_id')}")
    lines.append(f"- action: {rec.get('action')}")
    lines.append(f"- reason: {rec.get('reason')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-evaluate rollout decisions with hard process-returncode gates"
    )
    parser.add_argument("--summary-json", required=True)
    args = parser.parse_args(argv)

    summary_path = Path(args.summary_json).resolve()
    summary = _load_json(summary_path)

    run_rows = summary.get("patch_runs") or []
    matrix_rows = (summary.get("patch_isolation_matrix") or {}).get("rows") or []
    runtime_map = summary.get("runtime_target_verification") or {}

    matrix_by_patch = {str(row.get("patch_id") or ""): row for row in matrix_rows}
    merged_rows = []
    for run_row in run_rows:
        patch_id = str(run_row.get("patch_id") or "")
        merged = dict(matrix_by_patch.get(patch_id) or {})
        merged.update(
            {
                "patch_id": patch_id,
                "subprocess_returncode": run_row.get("subprocess_returncode"),
                "after": run_row.get("after") or {},
            }
        )
        merged_rows.append(merged)

    decisions = []
    for row in merged_rows:
        patch_id = str(row.get("patch_id") or "")
        runtime_target_pass = bool(
            ((runtime_map.get(patch_id) or {}).get("runtime_target_pass"))
        )
        decisions.append(_decision_for_patch(row, runtime_target_pass))

    promote_candidates = [d for d in decisions if d.get("action") == "promote"]
    if promote_candidates:
        promote_candidates.sort(
            key=lambda d: float(d.get("delta_profit_factor_vs_baseline") or 0.0),
            reverse=True,
        )
        recommendation = {
            "patch_id": promote_candidates[0]["patch_id"],
            "action": "promote",
            "reason": "best_patch_passing_all_hard_gates",
        }
    else:
        hold_candidates = [
            d
            for d in decisions
            if d.get("action") == "hold" and d.get("patch_id") != "baseline_locked"
        ]
        if hold_candidates:
            hold_candidates.sort(
                key=lambda d: float(d.get("delta_profit_factor_vs_baseline") or 0.0),
                reverse=True,
            )
            recommendation = {
                "patch_id": hold_candidates[0]["patch_id"],
                "action": "hold",
                "reason": "no_patch_passed_hard_promote_gates",
            }
        else:
            recommendation = {
                "patch_id": "baseline_locked",
                "action": "rollback",
                "reason": "all_nonbaseline_patches_failed_hard_gates",
            }

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_summary": str(summary_path),
        "decisions": decisions,
        "recommendation": recommendation,
    }

    out_json = summary_path.parent / "rollout_gate_hardening.json"
    out_md = summary_path.parent / "rollout_gate_hardening.md"
    out_json.write_text(
        json.dumps(output, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    out_md.write_text(_render_md(output), encoding="utf-8")

    print(f"HARDENING_JSON={out_json}")
    print(f"HARDENING_MD={out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
