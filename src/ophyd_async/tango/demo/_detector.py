import asyncio

from ophyd_async.core import (
    AsyncStatus,
    DeviceVector,
)
from ophyd_async.tango import TangoReadable

from . import TangoCounter, TangoMover


class TangoDetector(TangoReadable):
    counters: DeviceVector[TangoCounter]
    mover: TangoMover

    def __init__(self, *args, **kwargs):
        if "counters_kwargs" in kwargs:
            self._counters_kwargs = kwargs.pop("counters_kwargs")
        if "mover_kwargs" in kwargs:
            self._mover_kwargs = kwargs.pop("mover_kwargs")
        super().__init__(*args, **kwargs)
        self.add_readables([self.counters, self.mover])

    def set(self, value):
        return self.mover.set(value)

    def stop(self):
        return self.mover.stop()

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
