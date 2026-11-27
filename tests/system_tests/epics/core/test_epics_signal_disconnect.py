import asyncio
import time

import pytest
from aioca import purge_channel_caches

from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.epics.testing import IOC, generate_random_pv_prefix, start_ioc


@pytest.mark.parametrize("protocol", ["ca", "pva"])
async def test_subscription_reports_ioc_disconnect_and_reconnect(protocol):
    prefix = generate_random_pv_prefix()
    process = start_ioc(IOC, prefix)
    signal = epics_signal_rw(
        float, f"{protocol}://{prefix}{protocol}:float", name="value"
    )
    readings = asyncio.Queue()
    subscribed = False
    try:
        await signal.connect()
        await signal.set(12.5)
        signal.subscribe_reading(readings.put_nowait)
        subscribed = True
        first = (await asyncio.wait_for(readings.get(), 10))["value"]
        assert first["value"] == 12.5
        assert first["alarm_severity"] == 0

        stopped = time.time()
        process.stop()
        disconnected = (await asyncio.wait_for(readings.get(), 10))["value"]
        assert disconnected["value"] == first["value"]
        assert disconnected["alarm_severity"] == -1
        assert stopped <= disconnected["timestamp"] <= time.time()
        assert await signal.read(cached=True) == {"value": disconnected}

        restarted = time.time()
        process = start_ioc(IOC, prefix)
        reconnected = (await asyncio.wait_for(readings.get(), 10))["value"]
        assert reconnected["alarm_severity"] == 0
        assert restarted <= reconnected["timestamp"] <= time.time()
        assert await signal.read(cached=True) == {"value": reconnected}
        assert reconnected == (await signal.read(cached=False))["value"]
        await signal.set(23.5)
        changed = (await asyncio.wait_for(readings.get(), 10))["value"]
        assert changed["value"] == 23.5
        assert changed["alarm_severity"] == 0
    finally:
        if subscribed:
            signal.clear_sub(readings.put_nowait)
        purge_channel_caches()
        process.stop()
