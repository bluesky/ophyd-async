import bluesky.plan_stubs as bps

from ophyd_async.core.device import Device
from ophyd_async.core.utils import DEFAULT_TIMEOUT, wait_for_connection


def ensure_connected(
    *devices: Device,
    sim: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    force_reconnect=False,
):
    yield from bps.wait_for(
        [
            lambda: wait_for_connection(
                **{
                    device.name: device.connect(sim, timeout, force_reconnect)
                    for device in devices
                }
            )
        ]
    )
