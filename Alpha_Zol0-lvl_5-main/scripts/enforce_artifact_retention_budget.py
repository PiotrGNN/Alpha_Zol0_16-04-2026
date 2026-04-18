import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = WORKDIR / "artifacts" / "diagnostics"


def _default_policy() -> dict[str, Any]:
    gib = 1024**3
    mib = 1024**2
    return {
        "file_limits": [
            {
                "path": "logs/bot.log",
                "max_bytes": 2 * gib,
                "tail_bytes": 256 * mib,
            },
            {
                "path": "autopsy/decision_log.csv",
                "max_bytes": 1 * gib,
                "tail_bytes": 128 * mib,
            },
            {
                "path": "logs/bot_runtime.err",
                "max_bytes": 512 * mib,
                "tail_bytes": 64 * mib,
            },
        ],
        "directory_retention": [
            {
                "path": "reports/paper_runtime_patch_validation",
                "glob": "repair_iteration_*",
                "keep_latest": 40,
            }
        ],
        "file_retention": [
            {
                "path": "tmp",
                "glob": "controlled_kpi_after_*",
                "keep_latest": 60,
            }
        ],
        "hot_directory_budgets": [
            {"path": "logs", "max_bytes": 3 * gib},
            {"path": "autopsy", "max_bytes": 2 * gib},
            {"path": "tmp", "max_bytes": 6 * gib},
        ],
    }


def _safe_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for p in path.rglob("*"):
        if p.is_file():
            total += _safe_size(p)
    return int(total)


def _truncate_to_tail(path: Path, tail_bytes: int) -> tuple[int, int]:
    size_before = _safe_size(path)
    tail_bytes = max(0, int(tail_bytes))
    if size_before <= tail_bytes:
        return size_before, size_before
    with path.open("rb") as fh:
        fh.seek(size_before - tail_bytes)
        blob = fh.read(tail_bytes)
    with path.open("wb") as fh:
        fh.write(blob)
    size_after = _safe_size(path)
    return size_before, size_after


def _iter_retention_targets(root: Path, spec: dict[str, Any]) -> list[Path]:
    base = (root / str(spec.get("path") or "")).resolve()
    if not base.exists():
        return []
    glob = str(spec.get("glob") or "*")
    dirs = [p for p in base.glob(glob) if p.is_dir()]
    dirs.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return dirs


def _iter_file_retention_targets(root: Path, spec: dict[str, Any]) -> list[Path]:
    base = (root / str(spec.get("path") or "")).resolve()
    if not base.exists():
        return []
    glob = str(spec.get("glob") or "*")
    files = [p for p in base.glob(glob) if p.is_file()]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return files


def enforce_policy(
    root: Path,
    policy: dict[str, Any],
    apply: bool,
) -> dict[str, Any]:
    root = root.resolve()
    actions: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    # File-level truncation policy.
    for spec in policy.get("file_limits") or []:
        rel = str(spec.get("path") or "")
        if not rel:
            continue
        target = (root / rel).resolve()
        if not target.exists() or not target.is_file():
            checks.append(
                {
                    "kind": "file_limit",
                    "path": rel,
                    "exists": False,
                    "status": "missing",
                }
            )
            continue
        size_before = _safe_size(target)
        max_bytes = int(spec.get("max_bytes") or 0)
        tail_bytes = int(spec.get("tail_bytes") or 0)
        over_limit = max_bytes > 0 and size_before > max_bytes
        entry: dict[str, Any] = {
            "kind": "file_limit",
            "path": rel,
            "size_before": size_before,
            "max_bytes": max_bytes,
            "tail_bytes": tail_bytes,
            "over_limit": over_limit,
            "action": "none",
        }
        if over_limit:
            entry["action"] = "truncate_tail"
            if apply:
                before, after = _truncate_to_tail(target, tail_bytes)
                entry["applied"] = True
                entry["size_after"] = after
                entry["bytes_reclaimed"] = max(0, before - after)
            else:
                entry["applied"] = False
                entry["size_after"] = max(0, tail_bytes)
                entry["bytes_reclaimed"] = max(0, size_before - tail_bytes)
        checks.append(entry)
        if over_limit:
            actions.append(entry)

    # Directory retention by count.
    for spec in policy.get("directory_retention") or []:
        keep_latest = int(spec.get("keep_latest") or 0)
        targets = _iter_retention_targets(root, spec)
        base_rel = str(spec.get("path") or "")
        drop = targets[keep_latest:] if keep_latest >= 0 else []
        retained = [str(p.relative_to(root)) for p in targets[:keep_latest]]
        drop_rel = [str(p.relative_to(root)) for p in drop]
        entry = {
            "kind": "directory_retention",
            "path": base_rel,
            "glob": str(spec.get("glob") or "*"),
            "keep_latest": keep_latest,
            "found": len(targets),
            "retained": retained,
            "to_delete": drop_rel,
            "deleted": [],
            "applied": False,
        }
        if drop and apply:
            for folder in drop:
                shutil.rmtree(folder, ignore_errors=True)
                entry["deleted"].append(str(folder.relative_to(root)))
            entry["applied"] = True
        checks.append(entry)
        if drop:
            actions.append(entry)

    # File retention by count.
    for spec in policy.get("file_retention") or []:
        keep_latest = int(spec.get("keep_latest") or 0)
        targets = _iter_file_retention_targets(root, spec)
        base_rel = str(spec.get("path") or "")
        drop = targets[keep_latest:] if keep_latest >= 0 else []
        retained = [str(p.relative_to(root)) for p in targets[:keep_latest]]
        drop_rel = [str(p.relative_to(root)) for p in drop]
        entry = {
            "kind": "file_retention",
            "path": base_rel,
            "glob": str(spec.get("glob") or "*"),
            "keep_latest": keep_latest,
            "found": len(targets),
            "retained": retained,
            "to_delete": drop_rel,
            "deleted": [],
            "applied": False,
            "bytes_reclaimed": 0,
        }
        if drop and apply:
            reclaimed = 0
            for file_path in drop:
                reclaimed += _safe_size(file_path)
                try:
                    file_path.unlink(missing_ok=True)
                except Exception:
                    continue
                entry["deleted"].append(str(file_path.relative_to(root)))
            entry["applied"] = True
            entry["bytes_reclaimed"] = reclaimed
        checks.append(entry)
        if drop:
            actions.append(entry)

    # Hot directory budget checks.
    for spec in policy.get("hot_directory_budgets") or []:
        rel = str(spec.get("path") or "")
        max_bytes = int(spec.get("max_bytes") or 0)
        path = (root / rel).resolve()
        size_now = _dir_size(path)
        over = max_bytes > 0 and size_now > max_bytes
        checks.append(
            {
                "kind": "hot_directory_budget",
                "path": rel,
                "size_bytes": size_now,
                "max_bytes": max_bytes,
                "over_budget": over,
            }
        )

    over_budget_paths = [
        c.get("path")
        for c in checks
        if c.get("kind") == "hot_directory_budget" and c.get("over_budget")
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "apply": bool(apply),
        "actions_count": len(actions),
        "checks": checks,
        "actions": actions,
        "over_budget_paths": over_budget_paths,
        "budget_status": "PASS" if not over_budget_paths else "FAIL",
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Artifact Retention Budget Report", ""]
    lines.append(f"- generated_at: {report.get('generated_at')}")
    lines.append(f"- apply: {report.get('apply')}")
    lines.append(f"- actions_count: {report.get('actions_count')}")
    lines.append(f"- budget_status: {report.get('budget_status')}")
    lines.append("")
    lines.append("## Over-Budget Paths")
    for path in report.get("over_budget_paths") or []:
        lines.append(f"- {path}")
    if not (report.get("over_budget_paths") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Actions")
    for action in report.get("actions") or []:
        lines.append(
            "- "
            f"kind={action.get('kind')} "
            f"path={action.get('path')} "
            f"action={action.get('action', 'n/a')} "
            f"applied={action.get('applied')}"
        )
    if not (report.get("actions") or []):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Enforce file retention and workspace size budgets for runtime artifacts."
        )
    )
    parser.add_argument("--root", default=str(WORKDIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--policy-json",
        default="",
        help="Optional external policy JSON path.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    policy = _default_policy()
    if str(args.policy_json or "").strip():
        policy_path = Path(args.policy_json).resolve()
        policy = json.loads(policy_path.read_text(encoding="utf-8"))

    report = enforce_policy(root=root, policy=policy, apply=bool(args.apply))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"artifact_retention_budget_{stamp}.json"
    md_path = out_dir / f"artifact_retention_budget_{stamp}.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    print(f"RETENTION_REPORT_JSON={json_path}")
    print(f"RETENTION_REPORT_MD={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
