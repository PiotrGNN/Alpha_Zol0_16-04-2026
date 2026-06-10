from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get_json(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Paid-beta post-deploy smoke test")
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

    if not args.base_url.startswith("https://"):
        print(json.dumps({"status": "BLOCKED", "detail": "HTTPS base URL required"}))
        return 2

    checks: list[dict] = []
    try:
        status, health = _get_json(args.base_url.rstrip("/") + "/health")
        checks.append(
            {
                "name": "health",
                "passed": status == 200
                and health.get("public_live_trading") is False,
            }
        )
        status, openapi = _get_json(args.base_url.rstrip("/") + "/openapi.json")
        paths = openapi.get("paths", {})
        checks.append(
            {
                "name": "openapi",
                "passed": status == 200
                and "/auth/login" in paths
                and "/billing/webhook" in paths
                and not any("live" in path.lower() for path in paths),
            }
        )
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "detail": f"{type(exc).__name__}: smoke request failed",
                    "checks": checks,
                },
                sort_keys=True,
            )
        )
        return 1

    result = "PASS" if all(check["passed"] for check in checks) else "FAILED"
    print(json.dumps({"status": result, "checks": checks}, sort_keys=True))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
