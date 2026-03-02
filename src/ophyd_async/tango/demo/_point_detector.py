from typing import Annotated as A

from bluesky.protocols import Triggerable

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalX,
    StandardReadable,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango.core import TangoDevice

from ._point_detector_channel import DemoPointDetectorChannel


class DemoPointDetector(TangoDevice, StandardReadable, Triggerable):
    """A demo detector that produces a point values based on X and Y motors."""

    acquire_time: A[SignalRW[float], Format.CONFIG_SIGNAL]
    start: SignalX
    acquiring: SignalR[bool]
    reset: SignalX

    def __init__(self, trl: str, channel_trls: list[str], name: str = "") -> None:
        with self.add_children_as_readables():
            self.channel = DeviceVector(
                {
                    i + 1: DemoPointDetectorChannel(channel_trl)
                    for i, channel_trl in enumerate(channel_trls)
                }
            )
        super().__init__(trl, name=name)

    @AsyncStatus.wrap
    async def trigger(self):
        await self.reset.trigger()
        timeout = await self.acquire_time.get_value() + DEFAULT_TIMEOUT
        await self.start.trigger(timeout=timeout)
