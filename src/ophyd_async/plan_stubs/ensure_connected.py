import asyncio
from typing import List

import bluesky.plan_stubs as bps

from ophyd_async.core.device import Device
from ophyd_async.core.utils import DEFAULT_TIMEOUT, wait_for_connection


def ensure_connected(
    *devices: Device,
    mock: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    force_reconnect=False,
):
    connect_task_singleton: List[asyncio.Task] = yield from bps.wait_for(
        [
            lambda: wait_for_connection(
                **{
                    device.name: device.connect(
                        mock=mock, timeout=timeout, force_reconnect=force_reconnect
                    )
                    for device in devices
                }
            )
        ]
    )

    if connect_task_singleton and connect_task_singleton[0].exception() is not None:
        raise connect_task_singleton[0].exception()
