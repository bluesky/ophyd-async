import asyncio

from ophyd_async.core import (
    AsyncStatus,
    DeviceVector,
)
from ophyd_async.tango import TangoReadable

from ._counter import TangoCounter
from ._mover import TangoMover


class TangoDetector(TangoReadable):
    counters: DeviceVector
    mover: TangoMover

    def __init__(self, trl: str, mover_trl: str, counter_trls: list[str], name=""):
        super().__init__(trl, name=name)

        # If devices are inferred from type hints, they will be created automatically
        # during init. If they are created automatically, their trl must be set before
        # they are connected.
        self.mover.set_trl(mover_trl)
        for i, c_trl in enumerate(counter_trls):
            self.counters[i + 1] = TangoCounter(c_trl)

        # Define the readables for TangoDetector
        # DeviceVectors are incompatible with AsyncReadable. Ignore until fixed.
        self.add_readables([self.counters, self.mover])  # type: ignore

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
