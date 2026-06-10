from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

PROJECT_DIR = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = PROJECT_DIR / "tmp" / "control-plane"
ALLOWED_ENVIRONMENTS = {"local", "staging", "ops", "paper"}
SENSITIVE_MARKERS = (
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "DATABASE_URL",
)
FORBIDDEN_COMMAND_FRAGMENTS = ("live", "real-money", "promote")


@dataclass(frozen=True)
class Result:
    status: str
    command: str
    detail: str
    exit_code: int
    evidence: dict


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if any(marker in key.upper() for marker in SENSITIVE_MARKERS)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _write_evidence(result: Result, path: str | None) -> None:
    target = Path(path) if path else None
    if target is None:
        return
    if not target.is_absolute():
        target = PROJECT_DIR / target
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **asdict(result),
        "evidence": _redact(result.evidence),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "secrets_redacted": True,
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(
    command: Sequence[str],
    *,
    cwd: Path = PROJECT_DIR,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=merged_env,
        text=True,
        capture_output=capture,
        check=False,
    )


def _compose_files(environment: str) -> list[str]:
    files = ["-f", "compose.yml"]
    if environment == "local":
        files += ["-f", "compose.local.yml"]
    elif environment == "staging":
        files += ["-f", "compose.staging.yml"]
    return files


def _compose_command(environment: str, *args: str) -> list[str]:
    return ["docker", "compose", *_compose_files(environment), *args]


def _status_from_exit(code: int) -> str:
    return "PASS" if code == 0 else "FAILED"


def _simple_process(command_name: str, command: Sequence[str], *, cwd: Path = PROJECT_DIR) -> Result:
    completed = _run(command, cwd=cwd)
    return Result(
        status=_status_from_exit(completed.returncode),
        command=command_name,
        detail="command completed" if completed.returncode == 0 else "command failed",
        exit_code=completed.returncode,
        evidence={"argv": list(command)},
    )


def setup(_: argparse.Namespace) -> Result:
    required = ["docker", "python"]
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        return Result("BLOCKED", "setup", "missing required executables", 2, {"missing": missing})
    local_env = PROJECT_DIR / ".env.local"
    example = PROJECT_DIR / ".env.local.example"
    created = False
    if not local_env.exists() and example.exists():
        local_env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        created = True
    return Result("PASS", "setup", "local control-plane prerequisites prepared", 0, {"env_created": created})


def doctor(args: argparse.Namespace) -> Result:
    environment = args.environment
    checks: dict[str, bool] = {
        "environment_allowed": environment in ALLOWED_ENVIRONMENTS,
        "docker_present": shutil.which("docker") is not None,
        "python_present": shutil.which("python") is not None or shutil.which("python3") is not None,
        "compose_root_present": (PROJECT_DIR / "compose.yml").exists(),
        "dashboard_dockerfile_present": (PROJECT_DIR / "Dockerfile.dashboard").exists(),
        "caddyfile_present": (PROJECT_DIR / "Caddyfile").exists(),
    }
    if environment == "local":
        checks["local_overlay_present"] = (PROJECT_DIR / "compose.local.yml").exists()
    if environment == "staging":
        checks["staging_overlay_present"] = (PROJECT_DIR / "compose.staging.yml").exists()
        checks["scorecard_configured"] = bool(os.getenv("PAID_BETA_TRADING_SCORECARD_FILE"))
    failed = sorted(name for name, passed in checks.items() if not passed)
    return Result(
        "PASS" if not failed else "BLOCKED",
        "doctor",
        "all checks passed" if not failed else "environment prerequisites incomplete",
        0 if not failed else 2,
        {"environment": environment, "checks": checks, "failed": failed},
    )


def up(args: argparse.Namespace) -> Result:
    environment = args.environment
    if environment not in {"local", "staging"}:
        return Result("BLOCKED", "up", "up supports only local or staging", 2, {"environment": environment})
    command = _compose_command(environment, "--profile", environment, "up", "-d", "--build")
    return _simple_process("up", command)


def down(args: argparse.Namespace) -> Result:
    return _simple_process("down", _compose_command(args.environment, "down"))


def restart(args: argparse.Namespace) -> Result:
    completed = _run(_compose_command(args.environment, "restart"))
    return Result(_status_from_exit(completed.returncode), "restart", "services restarted" if completed.returncode == 0 else "restart failed", completed.returncode, {"environment": args.environment})


def status(args: argparse.Namespace) -> Result:
    command = _compose_command(args.environment, "ps", "--format", "json")
    completed = _run(command, capture=True)
    output = completed.stdout.strip()
    services: object = []
    if output:
        try:
            services = json.loads(output)
        except json.JSONDecodeError:
            services = output.splitlines()
    return Result(_status_from_exit(completed.returncode), "status", "compose status collected", completed.returncode, {"environment": args.environment, "services": services})


def logs(args: argparse.Namespace) -> Result:
    command = _compose_command(args.environment, "logs", "--tail", str(args.tail))
    if args.follow:
        command.append("--follow")
    return _simple_process("logs", command)


def open_app(args: argparse.Namespace) -> Result:
    url = args.url or ("http://localhost" if args.environment == "local" else os.getenv("PAID_BETA_APP_URL", ""))
    if not url:
        return Result("BLOCKED", "open", "application URL is not configured", 2, {"environment": args.environment})
    opened = webbrowser.open(url)
    return Result("PASS" if opened else "BLOCKED", "open", "browser launch requested", 0 if opened else 2, {"url": url})


def test_paid_beta(_: argparse.Namespace) -> Result:
    tests = [
        "tests/test_paid_beta_security.py",
        "tests/test_paid_beta_contract.py",
        "tests/test_paid_beta_api.py",
        "tests/test_paid_beta_p0.py",
        "tests/test_paid_beta_closed_beta_rehearsal.py",
        "tests/test_paid_beta_preflight.py",
        "tests/test_paid_beta_economics_import.py",
        "tests/test_paid_beta_mailer_rehearsal.py",
    ]
    return _simple_process("test-paid-beta", [sys.executable, "-m", "pytest", "-q", *tests])


def test_full(_: argparse.Namespace) -> Result:
    return _simple_process("test-full", [sys.executable, "-m", "pytest", "-q"])


def test_default(args: argparse.Namespace) -> Result:
    return test_paid_beta(args)


def preflight(args: argparse.Namespace) -> Result:
    command = [sys.executable, "scripts/paid_beta_preflight.py"]
    if args.network:
        command.append("--network")
    if args.output:
        command += ["--json-output", args.output]
    completed = _run(command)
    status_value = "PASS" if completed.returncode == 0 else "BLOCKED"
    return Result(status_value, "preflight", "preflight completed", completed.returncode, {"network": args.network})


def rehearsal(_: argparse.Namespace) -> Result:
    return _simple_process(
        "rehearsal",
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_paid_beta_preflight.py",
            "tests/test_paid_beta_economics_import.py",
            "tests/test_paid_beta_mailer_rehearsal.py",
            "tests/test_paid_beta_closed_beta_rehearsal.py",
        ],
    )


def stripe_listen(args: argparse.Namespace) -> Result:
    if shutil.which("stripe") is None:
        return Result("BLOCKED", "stripe-listen", "Stripe CLI is not installed", 2, {})
    forward_to = args.forward_to or "http://localhost/billing/webhook"
    return _simple_process("stripe-listen", ["stripe", "listen", "--forward-to", forward_to])


def stripe_trigger(args: argparse.Namespace) -> Result:
    if shutil.which("stripe") is None:
        return Result("BLOCKED", "stripe-trigger", "Stripe CLI is not installed", 2, {})
    allowed = {
        "checkout.session.completed",
        "invoice.payment_failed",
        "invoice.paid",
        "customer.subscription.deleted",
        "refund.created",
    }
    if args.event not in allowed:
        return Result("BLOCKED", "stripe-trigger", "event is not in the approved rehearsal set", 2, {"event": args.event})
    return _simple_process("stripe-trigger", ["stripe", "trigger", args.event])


def backup(_: argparse.Namespace) -> Result:
    command = ["bash", "scripts/paid_beta_backup_restore_smoke.sh"]
    return _simple_process("backup", command)


def restore_check(_: argparse.Namespace) -> Result:
    return _simple_process("restore-check", ["bash", "scripts/paid_beta_staging_backup_restore_rehearsal.sh"])


def economics_validate(args: argparse.Namespace) -> Result:
    return _simple_process(
        "economics-validate",
        [sys.executable, "scripts/import_paid_beta_economics_period.py", args.payload, "--dry-run"],
    )


def economics_import(args: argparse.Namespace) -> Result:
    command = [sys.executable, "scripts/import_paid_beta_economics_period.py", args.payload]
    if args.base_url:
        command += ["--base-url", args.base_url]
    completed = _run(command)
    status_value = "PASS" if completed.returncode == 0 else "BLOCKED" if completed.returncode == 2 else "FAILED"
    return Result(status_value, "economics-import", "weekly import completed", completed.returncode, {"payload": args.payload, "base_url": args.base_url})


def paper_start(args: argparse.Namespace) -> Result:
    command = [sys.executable, "scripts/controlled_kpi_run.py", "--variant-only", "before", "--before-min", str(args.minutes)]
    return _simple_process("paper-start", command)


def paper_status(_: argparse.Namespace) -> Result:
    candidates = sorted((PROJECT_DIR / "results").glob("controlled_kpi_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    latest = str(candidates[0].relative_to(PROJECT_DIR)) if candidates else None
    return Result("PASS" if latest else "BLOCKED", "paper-status", "latest PAPER artifact located" if latest else "no PAPER artifact found", 0 if latest else 2, {"latest": latest})


def scorecard_build(_: argparse.Namespace) -> Result:
    script = PROJECT_DIR / "scripts" / "profitability_audit_scorecard.py"
    if not script.exists():
        return Result("BLOCKED", "scorecard-build", "scorecard builder script not found", 2, {})
    return _simple_process("scorecard-build", [sys.executable, str(script.relative_to(PROJECT_DIR))])


def scorecard_check(_: argparse.Namespace) -> Result:
    configured = os.getenv("PAID_BETA_TRADING_SCORECARD_PATH", "analysis/zol0_profitability_audit_scorecard.json")
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    if not path.exists() or path.stat().st_size == 0:
        return Result("BLOCKED", "scorecard-check", "fresh scorecard is missing", 2, {"path": str(path)})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return Result("FAILED", "scorecard-check", "scorecard JSON is invalid", 1, {"path": str(path)})
    generated_at = (payload.get("metadata") or {}).get("generated_at")
    return Result("PASS", "scorecard-check", "scorecard is readable", 0, {"path": str(path), "generated_at": generated_at, "live_ready": False})


COMMANDS: dict[str, Callable[[argparse.Namespace], Result]] = {
    "setup": setup,
    "doctor": doctor,
    "up": up,
    "down": down,
    "restart": restart,
    "status": status,
    "logs": logs,
    "open": open_app,
    "test": test_default,
    "test-paid-beta": test_paid_beta,
    "test-full": test_full,
    "preflight": preflight,
    "rehearsal": rehearsal,
    "stripe-listen": stripe_listen,
    "stripe-trigger": stripe_trigger,
    "backup": backup,
    "restore-check": restore_check,
    "economics-validate": economics_validate,
    "economics-import": economics_import,
    "paper-start": paper_start,
    "paper-status": paper_status,
    "scorecard-build": scorecard_build,
    "scorecard-check": scorecard_check,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zol0ctl", description="Unified ZoL0 control plane")
    parser.add_argument("--evidence", default="", help="optional redacted JSON evidence path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup")
    for name in ("doctor", "up", "down", "restart", "status", "logs", "open"):
        command_parser = subparsers.add_parser(name)
        command_parser.add_argument("environment", choices=sorted(ALLOWED_ENVIRONMENTS), nargs="?", default="local")
        if name == "logs":
            command_parser.add_argument("--tail", type=int, default=200)
            command_parser.add_argument("--follow", action="store_true")
        if name == "open":
            command_parser.add_argument("--url", default="")

    for name in ("test", "test-paid-beta", "test-full", "rehearsal", "backup", "restore-check", "paper-status", "scorecard-build", "scorecard-check"):
        subparsers.add_parser(name)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--network", action="store_true")
    preflight_parser.add_argument("--output", default="")

    stripe_listen_parser = subparsers.add_parser("stripe-listen")
    stripe_listen_parser.add_argument("--forward-to", default="")
    stripe_trigger_parser = subparsers.add_parser("stripe-trigger")
    stripe_trigger_parser.add_argument("event")

    for name in ("economics-validate", "economics-import"):
        economics_parser = subparsers.add_parser(name)
        economics_parser.add_argument("payload")
        if name == "economics-import":
            economics_parser.add_argument("--base-url", default="")

    paper_parser = subparsers.add_parser("paper-start")
    paper_parser.add_argument("--minutes", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    lowered = args.command.lower()
    if any(fragment in lowered for fragment in FORBIDDEN_COMMAND_FRAGMENTS):
        result = Result("BLOCKED", args.command, "LIVE and real-money commands are forbidden", 2, {})
    else:
        result = COMMANDS[args.command](args)
    print(f"{result.status}: {result.command}: {result.detail}")
    _write_evidence(result, args.evidence or None)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
