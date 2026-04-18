import asyncio
import logging

logger = logging.getLogger("system_monitor")

# psutil is optional in runtime; if not installed, provide lightweight fallbacks
try:
    import psutil

    _PSUTIL_AVAILABLE = True
except Exception:
    psutil = None
    _PSUTIL_AVAILABLE = False
    logger.debug("psutil not available; system monitoring disabled or limited")

# [TASK-ID: system_monitoring_init]


async def log_system_usage():
    while True:
        if not _PSUTIL_AVAILABLE:
            logger.debug("psutil not available; skipping system usage log")
        else:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            logger.info(f"[MONITOR] CPU: {cpu}%, RAM: {ram}%")
        await asyncio.sleep(60)


# [TASK-ID: resource_alerting]
async def check_resource_limits(cpu_limit=90, ram_limit=90):
    while True:
        if not _PSUTIL_AVAILABLE:
            logger.debug("psutil not available; skipping resource limit checks")
        else:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            if cpu > cpu_limit or ram > ram_limit:
                logger.warning(
                    f"[ALERT] Resource limit exceeded: CPU={cpu}%, RAM={ram}%"
                )
        await asyncio.sleep(60)
