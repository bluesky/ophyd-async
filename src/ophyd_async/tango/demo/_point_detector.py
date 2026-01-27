from typing import Annotated as A

from bluesky.protocols import Triggerable

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.core import StandardReadable
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
            device_vector = {}
            i = 1
            for channel_trl in channel_trls:
                device_vector[i] = DemoPointDetectorChannel(channel_trl)
                i+=1
            self.channel = DeviceVector(device_vector)
        super().__init__(trl, name=name)

    @AsyncStatus.wrap
    async def trigger(self):
        await self.reset.trigger()
        timeout = await self.acquire_time.get_value() + DEFAULT_TIMEOUT
        await self.start.trigger(timeout=timeout)
