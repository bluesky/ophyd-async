import asyncio
from typing import Annotated as A

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    AsyncStatus,
    CalculatableTimeout,
    SignalR,
    SignalRW,
    SignalX,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
    wait_for_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango.core import TangoPolling, TangoReadable
from tango import DevState


class TangoMover(TangoReadable, Movable, Stoppable):
    # Enter the name and type of the signals you want to use
    # If the server doesn't support events, the TangoPolling annotation gives
    # the parameters for ophyd to poll instead
    position: A[SignalRW[float], TangoPolling(0.1, 0.1, 0.1)]
    velocity: A[SignalRW[float], TangoPolling(0.1, 0.1, 0.1)]
    state: A[SignalR[DevState], TangoPolling(0.1)]
    # If a tango name clashes with a bluesky verb, add a trailing underscore
    stop_: SignalX

    def __init__(self, trl: str | None = "", name=""):
        super().__init__(trl, name=name)
        self.add_readables([self.position], Format.HINTED_SIGNAL)
        self.add_readables([self.velocity], Format.CONFIG_SIGNAL)
        self._set_success = True

    @WatchableAsyncStatus.wrap
    async def set(self, value: float, timeout: CalculatableTimeout = CALCULATE_TIMEOUT):
        self._set_success = True
        (old_position, velocity) = await asyncio.gather(
            self.position.get_value(), self.velocity.get_value()
        )
        if timeout is CALCULATE_TIMEOUT:
            assert velocity > 0, "Motor has zero velocity"
            timeout = abs(value - old_position) / velocity + DEFAULT_TIMEOUT

        if not (isinstance(timeout, float) or timeout is None):
            raise ValueError("Timeout must be a float or None")
        # For this server, set returns immediately so this status should not be awaited
        await self.position.set(value, wait=False, timeout=timeout)

        move_status = AsyncStatus(
            wait_for_value(self.state, DevState.ON, timeout=timeout)
        )

        try:
            async for current_position in observe_value(
                self.position, done_status=move_status
            ):
                yield WatcherUpdate(
                    current=current_position,
                    initial=old_position,
                    target=value,
                    name=self.name,
                )
        except RuntimeError as exc:
            self._set_success = False
            raise RuntimeError("Motor was stopped") from exc
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    def stop(self, success: bool = True) -> AsyncStatus:
        self._set_success = success
        return self.stop_.trigger()
