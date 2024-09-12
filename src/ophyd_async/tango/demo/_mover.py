import asyncio

from bluesky.protocols import Movable, Reading, Stoppable

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    CalculatableTimeout,
    CalculateTimeout,
    ConfigSignal,
    HintedSignal,
    SignalRW,
    SignalX,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
)
from ophyd_async.tango import TangoReadable, tango_polling
from tango import DevState


# Enable device level polling, useful for servers that do not support events
@tango_polling((0.1, 0.1, 0.1))
class TangoMover(TangoReadable, Movable, Stoppable):
    # Enter the name and type of the signals you want to use
    # If type is None or Signal, the type will be inferred from the Tango device
    position: SignalRW[float]
    velocity: SignalRW[float]
    _stop: SignalX

    def __init__(self, trl: str, name=""):
        super().__init__(trl, name=name)
        self.add_readables([self.position], HintedSignal)
        self.add_readables([self.velocity], ConfigSignal)
        self._set_success = True

    @WatchableAsyncStatus.wrap
    async def set(self, value: float, timeout: CalculatableTimeout = CalculateTimeout):
        self._set_success = True
        (old_position, velocity) = await asyncio.gather(
            self.position.get_value(), self.velocity.get_value()
        )
        if timeout is CalculateTimeout:
            assert velocity > 0, "Motor has zero velocity"
            timeout = abs(value - old_position) / velocity + DEFAULT_TIMEOUT

        # For this server, set returns immediately so this status should not be awaited
        await self.position.set(value, wait=False, timeout=timeout)

        # Wait for the motor to stop
        move_status = self.wait_for_idle()

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

    @AsyncStatus.wrap
    async def wait_for_idle(self):
        event = asyncio.Event()

        def _wait(value: dict[str, Reading]):
            if value[self.state.name]["value"] == DevState.ON:
                event.set()

        self.state.subscribe(_wait)
        await event.wait()
        self.state.clear_sub(_wait)

    def stop(self, success: bool = True) -> AsyncStatus:
        self._set_success = success
        return self._stop.trigger()
