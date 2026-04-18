import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
READINESS_DIR = WORKDIR / "reports" / "paper_readiness"
DEFAULT_OUT_DIR = WORKDIR / "artifacts" / "diagnostics"


@dataclass
class DriverStat:
    driver_id: str
    occurrences: int = 0
    edge_delta_sum: float = 0.0
    negative_impact_sum: int = 0
    changed_decisions_sum: int = 0

    def score(self) -> float:
        penalty_edge = max(0.0, -self.edge_delta_sum)
        return penalty_edge + 0.01 * float(self.negative_impact_sum) + 0.01 * float(
            self.changed_decisions_sum
        )


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _drivers_for_payload(econ: dict) -> list[str]:
    drivers = []
    avg_edge_delta = _safe_float(econ.get("avg_edge_delta"), 0.0)
    positive = _safe_int(econ.get("positive_impact_count"), 0)
    negative = _safe_int(econ.get("negative_impact_count"), 0)
    changed = _safe_int(econ.get("changed_decisions"), 0)
    if avg_edge_delta < 0:
        drivers.append("EDGE_DELTA_NEGATIVE")
    if negative > positive:
        drivers.append("NEGATIVE_IMPACT_DOMINATES")
    if changed > 0:
        drivers.append("DECISION_CHURN")
    if not drivers:
        drivers.append("UNSPECIFIED_NO_GO")
    return drivers


def build_ranking(readiness_dir: Path) -> dict:
    files = sorted(readiness_dir.glob("paper_readiness_gate_*.json"))
    stats = {}
    no_go_samples = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        econ = payload.get("economics_context") or {}
        go_no_go = str(econ.get("go_no_go") or "").strip().upper()
        if go_no_go != "NO-GO":
            continue
        avg_edge_delta = _safe_float(econ.get("avg_edge_delta"), 0.0)
        negative_impact = _safe_int(econ.get("negative_impact_count"), 0)
        changed_decisions = _safe_int(econ.get("changed_decisions"), 0)
        sample = {
            "path": str(path),
            "timestamp": payload.get("timestamp"),
            "avg_edge_delta": avg_edge_delta,
            "negative_impact_count": negative_impact,
            "changed_decisions": changed_decisions,
        }
        no_go_samples.append(sample)
        for driver in _drivers_for_payload(econ):
            stat = stats.setdefault(driver, DriverStat(driver_id=driver))
            stat.occurrences += 1
            stat.edge_delta_sum += avg_edge_delta
            stat.negative_impact_sum += negative_impact
            stat.changed_decisions_sum += changed_decisions

    ranking = [asdict(stat) | {"score": stat.score()} for stat in stats.values()]
    ranking.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness_dir": str(readiness_dir.resolve()),
        "readiness_reports_total": len(files),
        "no_go_reports_total": len(no_go_samples),
        "driver_ranking": ranking,
        "top_samples": no_go_samples[:20],
    }


def _render_markdown(payload: dict) -> str:
    lines = ["# Economic NO-GO Driver Ranking", ""]
    lines.append(f"- generated_at: {payload.get('generated_at')}")
    lines.append(f"- readiness_reports_total: {payload.get('readiness_reports_total')}")
    lines.append(f"- no_go_reports_total: {payload.get('no_go_reports_total')}")
    lines.append("")
    lines.append("## Ranked Drivers")
    lines.append("| Driver | Occurrences | edge_delta_sum | negative_impact_sum | changed_decisions_sum | score |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in payload.get("driver_ranking") or []:
        lines.append(
            "| "
            f"{row.get('driver_id')} | "
            f"{row.get('occurrences')} | "
            f"{float(row.get('edge_delta_sum') or 0.0):.6f} | "
            f"{int(row.get('negative_impact_sum') or 0)} | "
            f"{int(row.get('changed_decisions_sum') or 0)} | "
            f"{float(row.get('score') or 0.0):.6f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank recurring NO-GO economic drivers from readiness reports."
    )
    parser.add_argument("--readiness-dir", default=str(READINESS_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args(argv)

    readiness_dir = Path(args.readiness_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = build_ranking(readiness_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"economic_no_go_driver_ranking_{stamp}.json"
    md_path = out_dir / f"economic_no_go_driver_ranking_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    print(f"RANKING_JSON={json_path}")
    print(f"RANKING_MD={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
