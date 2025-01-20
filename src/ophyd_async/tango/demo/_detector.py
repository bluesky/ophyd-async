import asyncio

from ophyd_async.core import (
    AsyncStatus,
    DeviceVector,
    StandardReadable,
)

from ._counter import TangoCounter
from ._mover import TangoMover


class TangoDetector(StandardReadable):
    def __init__(self, mover_trl: str, counter_trls: list[str], name=""):
        # A detector device may be composed of tango sub-devices
        self.mover = TangoMover(mover_trl)
        self.counters = DeviceVector(
            {i + 1: TangoCounter(c_trl) for i, c_trl in enumerate(counter_trls)}
        )

        # Define the readables for TangoDetector
        # DeviceVectors are incompatible with AsyncReadable. Ignore until fixed.
        self.add_readables([self.counters, self.mover])  # type: ignore

        super().__init__(name=name)

    def set(self, value):
        return self.mover.set(value)

    def stop(self, success: bool = True) -> AsyncStatus:
        return self.mover.stop(success)

    @AsyncStatus.wrap
    async def trigger(self):
        statuses = []
        for counter in self.counters.values():
            statuses.append(counter.reset())
        await asyncio.gather(*statuses)
        statuses.clear()
        for counter in self.counters.values():
            statuses.append(counter.trigger())
        await asyncio.gather(*statuses)
