from collections.abc import Awaitable

import bluesky.plan_stubs as bps

from ophyd_async.core import DEFAULT_TIMEOUT, Device, LazyMock, wait_for_connection


def ensure_connected(
    *devices: Device,
    mock: bool | LazyMock = False,
    timeout: float = DEFAULT_TIMEOUT,
    force_reconnect=False,
):
    device_names = [device.name for device in devices]
    non_unique = {
        device: device.name for device in devices if device_names.count(device.name) > 1
    }
    if non_unique:
        raise ValueError(f"Devices do not have unique names {non_unique}")

    def connect_devices() -> Awaitable[None]:
        coros = {
            device.name: device.connect(
                mock=mock, timeout=timeout, force_reconnect=force_reconnect
            )
            for device in devices
        }
        return wait_for_connection(**coros)

    (connect_task,) = yield from bps.wait_for([connect_devices])

    if connect_task and connect_task.exception() is not None:
        raise connect_task.exception()
