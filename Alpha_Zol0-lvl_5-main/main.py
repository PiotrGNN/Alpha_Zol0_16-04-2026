"""
# ✅ Audited by Copilot AI — 2025-07-29
# Changes: PEP8 line length fixes, audit header added, ensured logger and
# imports are correct.
"""

# main.py – Entry point for ZoL0 Bot with CLI, restart and simulation mode
import argparse
import logging
import sys
import asyncio
import threading
import time

import uvicorn
from core.BotCore import run_bot
from core.db_models import init_db
from utils.system_monitor import log_system_usage, check_resource_limits

logger = logging.getLogger("zol0-main")
logging.basicConfig(level=logging.INFO)


def start_api():
    """Start FastAPI dashboard backend."""
    try:
        uvicorn.run(
            "api_status:app",
            host="0.0.0.0",
            port=8000,
            log_level="info",
            reload=False,
        )
    except Exception as e:
        logger.error(f"[API] Failed to start FastAPI server: {e}")


# Start system monitoring in a separate event loop
# to avoid blocking the main thread
def start_system_monitor():
    """Launch system resource monitoring tasks asynchronously."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Create background tasks for resource logging and alerting
        loop.create_task(log_system_usage())
        loop.create_task(check_resource_limits())
        loop.run_forever()
    except Exception as e:
        logger.error(f"[MONITOR] Failed to start system monitor: {e}")


def main():
    parser = argparse.ArgumentParser(description="ZoL0 Bot entrypoint")
    parser.add_argument(
        "--mode",
        choices=["simulate", "live"],
        default="simulate",
        help="Run mode (simulate/live)",
    )
    parser.add_argument(
        "--no-api", action="store_true", help="Disable FastAPI dashboard"
    )
    parser.add_argument(
        "--autorestart",
        type=int,
        default=5,
        help="Restart delay (in seconds) on crash",
    )
    args = parser.parse_args()

    logger.info(
        f"ZoL0 Starting in {args.mode.upper()} mode. " f"API enabled: {not args.no_api}"
    )

    # Ensure DB schema exists before the bot starts writing logs/decisions/equity.
    try:
        init_db()
        logger.info("[DB] Schema initialized")
    except Exception as e:
        logger.error(f"[DB] Failed to initialize schema: {e}", exc_info=True)
        sys.exit(1)

    # Start API in background
    if not args.no_api:
        api_thread = threading.Thread(target=start_api, daemon=True)
        # Also start the system monitoring thread (runs its own asyncio loop)
        monitor_thread = threading.Thread(target=start_system_monitor, daemon=True)
        # [TASK-ID: system_monitoring_init]
        # Monitoring zasobów – uruchamiany pasywnie, nie wpływa na pętlę handlu
        # (Podpięcie tylko tutaj, nie w pętli decyzyjnej)
        api_thread.start()
        monitor_thread.start()
        logger.info("[API] FastAPI server thread started")
        logger.info("[MONITOR] System monitoring thread started")

    # Main bot loop with autorestart
    while True:
        try:
            run_bot(simulate=(args.mode == "simulate"))
        except KeyboardInterrupt:
            logger.info("[MAIN] ZoL0 shutdown requested by user.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"[MAIN] Bot crashed: {e}", exc_info=True)
            logger.info(f"[MAIN] Restarting in {args.autorestart} seconds...")
            time.sleep(args.autorestart)


if __name__ == "__main__":
    main()

# Export FastAPI app for uvicorn/Dockerfile
