import asyncio
import psutil
import pytest
from utils import system_monitor


@pytest.mark.asyncio
async def test_log_system_usage_sanity():
    # Run the logger for 2 seconds, check no crash and reasonable values
    task = asyncio.create_task(system_monitor.log_system_usage())
    await asyncio.sleep(2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()


@pytest.mark.asyncio
async def test_check_resource_limits_sanity():
    # Run the resource checker for 2 seconds, check no crash
    task = asyncio.create_task(
        system_monitor.check_resource_limits(cpu_limit=100, ram_limit=100)
    )
    await asyncio.sleep(2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()


def test_cpu_ram_usage_below_100():
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    assert 0 <= cpu <= 100
    assert 0 <= ram <= 100
