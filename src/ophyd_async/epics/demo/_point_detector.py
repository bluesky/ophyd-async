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
from ophyd_async.epics.core import EpicsDevice, PvSuffix

from ._point_detector_channel import DemoPointDetectorChannel


class DemoPointDetector(StandardReadable, EpicsDevice, Triggerable):
    """A demo detector that produces a point values based on X and Y motors."""

    acquire_time: A[SignalRW[float], PvSuffix("AcquireTime"), Format.CONFIG_SIGNAL]
    start: A[SignalX, PvSuffix("Start.PROC")]
    acquiring: A[SignalR[bool], PvSuffix("Acquiring")]
    reset: A[SignalX, PvSuffix("Reset.PROC")]

    def __init__(self, prefix: str, num_channels: int = 3, name: str = "") -> None:
        with self.add_children_as_readables():
            self.channel = DeviceVector(
                {
                    i: DemoPointDetectorChannel(f"{prefix}{i}:")
                    for i in range(1, num_channels + 1)
                }
            )
        super().__init__(prefix=prefix, name=name)

    @AsyncStatus.wrap
    async def trigger(self):
        await self.reset.trigger()
        timeout = await self.acquire_time.get_value() + DEFAULT_TIMEOUT
        await self.start.trigger(timeout=timeout)
