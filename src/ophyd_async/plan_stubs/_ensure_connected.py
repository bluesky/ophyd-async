import bluesky.plan_stubs as bps

from ophyd_async.core import DEFAULT_TIMEOUT, Device, wait_for_connection


def ensure_connected(
    *devices: Device,
    mock: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    force_reconnect=False,
):
    (connect_task,) = yield from bps.wait_for(
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

    if connect_task and connect_task.exception() is not None:
        raise connect_task.exception()
