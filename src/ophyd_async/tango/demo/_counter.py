from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    ConfigSignal,
    HintedSignal,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.tango import TangoReadable, tango_polling


# Enable device level polling, useful for servers that do not support events
# Polling for individual signal can be enabled with a dict
@tango_polling({"counts": (1.0, 0.1, 0.1), "sample_time": (0.1, 0.1, 0.1)})
class TangoCounter(TangoReadable):
    # Enter the name and type of the signals you want to use
    # If type is None or Signal, the type will be inferred from the Tango device
    counts: SignalR[int]
    sample_time: SignalRW[float]
    start: SignalX
    _reset: SignalX

    def __init__(self, trl: str | None = "", name=""):
        super().__init__(trl, name=name)
        self.add_readables([self.counts], HintedSignal)
        self.add_readables([self.sample_time], ConfigSignal)

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        sample_time = await self.sample_time.get_value()
        timeout = sample_time + DEFAULT_TIMEOUT
        await self.start.trigger(wait=True, timeout=timeout)

    @AsyncStatus.wrap
    async def reset(self) -> None:
        await self._reset.trigger(wait=True, timeout=DEFAULT_TIMEOUT)
