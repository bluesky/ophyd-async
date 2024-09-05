from dataclasses import dataclass
from typing import Optional

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    ConfigSignal,
    HintedSignal,
    Signal,
    SignalX,
)
from ophyd_async.tango import TangoReadable, tango_polling


@dataclass
class TangoCounterConfig:
    sample_time: Optional[float] = None


# Enable device level polling, useful for servers that do not support events
# Polling for individual signal can be enabled with a dict
@tango_polling((0.1, 0.1, 0.1), {"counts": (1.0, 0.1, 0.1)})
class TangoCounter(TangoReadable):
    # Enter the name and type of the signals you want to use
    # If type is None or Signal, the type will be inferred from the Tango device
    counts: Signal
    sample_time: Signal
    state: Signal
    reset: Signal
    start: SignalX

    def __init__(self, trl: str, name=""):
        super().__init__(trl, name=name)
        self.add_readables([self.counts], HintedSignal.uncached)
        self.add_readables([self.sample_time], ConfigSignal)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        sample_time = await self.sample_time.get_value()
        timeout = sample_time + DEFAULT_TIMEOUT
        await self.start.trigger(wait=True, timeout=timeout)

    @AsyncStatus.wrap
    async def prepare(self, value: TangoCounterConfig) -> None:
        config = value.__dataclass_fields__
        for key in config:
            v = getattr(value, key)
            if v is not None:
                if hasattr(self, key):
                    await getattr(self, key).set(v)

    def get_dataclass(self) -> TangoCounterConfig:
        return TangoCounterConfig()
