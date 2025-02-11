from bluesky.utils import plan

from ophyd_async.core import DEFAULT_TIMEOUT, Device, LazyMock, wait_for_connection

from ._wait_for_awaitable import wait_for_awaitable


@plan
def ensure_connected(
    *devices: Device,
    mock: bool | LazyMock = False,
    timeout: float = DEFAULT_TIMEOUT,
    force_reconnect=False,
):
    """Plan stub to ensure devices are connected with a given timeout."""
    device_names = [device.name for device in devices]
    non_unique = {
        device: device.name for device in devices if device_names.count(device.name) > 1
    }
    if non_unique:
        raise ValueError(f"Devices do not have unique names {non_unique}")
    coros = {
        device.name: device.connect(
            mock=mock, timeout=timeout, force_reconnect=force_reconnect
        )
        for device in devices
    }
    yield from wait_for_awaitable(wait_for_connection(**coros))
