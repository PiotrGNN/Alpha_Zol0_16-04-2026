from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SECRET_VARIABLES = (
    "PAID_BETA_DATABASE_URL",
    "PAID_BETA_TOKEN_SECRET",
    "PAID_BETA_ADMIN_BOOTSTRAP_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "PAID_BETA_SMTP_PASSWORD",
)


def load_secret_files() -> None:
    for name in SECRET_VARIABLES:
        file_name = (os.getenv(f"{name}_FILE") or "").strip()
        if not file_name:
            continue
        path = Path(file_name)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"unable to read configured secret file for {name}") from exc
        if not value:
            raise RuntimeError(f"configured secret file for {name} is empty")
        os.environ[name] = value


def main(argv: list[str] | None = None) -> int:
    command = list(argv if argv is not None else sys.argv[1:])
    if not command:
        print("BLOCKED: child command is required", file=sys.stderr)
        return 2
    load_secret_files()
    completed = subprocess.run(command, env=os.environ.copy(), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
