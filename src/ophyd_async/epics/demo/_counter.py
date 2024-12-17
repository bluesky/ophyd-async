from typing import Annotated as A

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalX,
    StandardReadable,
    StrictEnum,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix


class EnergyMode(StrictEnum):
    """Energy mode for `Sensor`"""

    #: Low energy mode
    LOW = "Low Energy"
    #: High energy mode
    HIGH = "High Energy"


class Counter(StandardReadable, EpicsDevice):
    """A demo sensor that produces a scalar value based on X and Y Movers"""

    value: A[SignalR[int], PvSuffix("Value"), Format.HINTED_SIGNAL]
    mode: A[SignalRW[EnergyMode], PvSuffix("Mode"), Format.CONFIG_SIGNAL]


class MultiChannelCounter(StandardReadable, EpicsDevice):
    start: A[SignalX, PvSuffix("Start")]
    acquire_time: A[SignalRW[float], PvSuffix("AcquireTime")]

    def __init__(self, prefix: str, name: str = "", num_counters: int = 3) -> None:
        with self.add_children_as_readables():
            self.counters = DeviceVector(
                {i: Counter(f"{prefix}{i}:") for i in range(1, num_counters + 1)}
            )
        super().__init__(prefix=prefix, name=name)

    @AsyncStatus.wrap
    async def trigger(self):
        timeout = await self.acquire_time.get_value() + DEFAULT_TIMEOUT
        await self.start.trigger(timeout=timeout)
