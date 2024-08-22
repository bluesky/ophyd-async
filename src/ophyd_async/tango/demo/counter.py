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
from ophyd_async.tango import (
    TangoReadableDevice,
)


@dataclass
class TangoCounterConfig:
    sample_time: Optional[float] = None


class TangoCounter(TangoReadableDevice):
    # Enter the name and type of the signals you want to use
    # If type is None or Signal, the type will be inferred from the Tango device
    counts: None
    sample_time: Signal
    state: Signal
    reset: Signal
    start: SignalX

    def __init__(self, trl: str, name=""):
        super().__init__(trl, name=name)
        self.add_readables([self.counts], HintedSignal.uncached)
        self.add_readables([self.sample_time], ConfigSignal)

    def trigger(self):
        return AsyncStatus(self._trigger())

    async def _trigger(self):
        sample_time = await self.sample_time.get_value()
        timeout = sample_time + DEFAULT_TIMEOUT
        await self.start.trigger(wait=True, timeout=timeout)

    def prepare(self, value: TangoCounterConfig) -> AsyncStatus:
        return AsyncStatus(self._prepare(value))

    async def _prepare(self, value: TangoCounterConfig) -> None:
        config = value.__dataclass_fields__
        for key, v in config.items():
            if v is not None:
                if hasattr(self, key):
                    await getattr(self, key).set(v)
