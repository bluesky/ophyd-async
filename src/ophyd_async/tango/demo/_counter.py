from typing import Annotated as A

from ophyd_async.core import DEFAULT_TIMEOUT, AsyncStatus, SignalR, SignalRW, SignalX
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango.core import TangoPolling, TangoReadable


class TangoCounter(TangoReadable):
    """Tango counting device."""

    # Enter the name and type of the signals you want to use
    # If the server doesn't support events, the TangoPolling annotation gives
    # the parameters for ophyd to poll instead
    counts: A[SignalR[int], Format.HINTED_SIGNAL, TangoPolling(1.0, 0.1, 0.1)]
    sample_time: A[SignalRW[float], Format.CONFIG_SIGNAL, TangoPolling(0.1, 0.1, 0.1)]
    start: SignalX
    # If a tango name clashes with a bluesky verb, add a trailing underscore
    reset_: SignalX

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        sample_time = await self.sample_time.get_value()
        timeout = sample_time + DEFAULT_TIMEOUT
        await self.start.trigger(wait=True, timeout=timeout)

    @AsyncStatus.wrap
    async def reset(self) -> None:
        await self.reset_.trigger(wait=True, timeout=DEFAULT_TIMEOUT)
