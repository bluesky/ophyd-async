import asyncio
from dataclasses import dataclass

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    MovableLogic,
    SignalR,
    SignalRW,
    SignalX,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_x,
)


@dataclass
class DemoMotorMoveSiganls:
    readback: SignalR[float]
    setpoint: SignalRW[float]
    velocity: SignalRW[float]
    units: SignalR[str]
    precision: SignalR[int]
    stop: SignalX


class DemoMotorMoveLogic(MovableLogic[float]):
    def __init__(self, motor_signals: DemoMotorMoveSiganls):
        self.motor_signals = motor_signals
        self.readback = motor_signals.readback
        self.setpoint = motor_signals.setpoint

    async def stop(self):
        await self.motor_signals.stop.trigger()

    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        velocity = await self.motor_signals.velocity.get_value()
        return abs(new_position - old_position) / velocity + DEFAULT_TIMEOUT

    async def get_units_precision(self) -> tuple[str, int]:
        return await asyncio.gather(
            self.motor_signals.units.get_value(),
            self.motor_signals.precision.get_value(),
        )


class DemoMotor(StandardReadable, StandardMovable):
    """A demo movable that moves based on velocity."""

    def __init__(self, prefix: str, name: str = ""):
        with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
            self.readback = epics_signal_r(float, prefix + "Readback")
        self.setpoint = epics_signal_rw(float, prefix + "Setpoint")

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.velocity = epics_signal_rw(float, prefix + "Velocity")
            self.units = epics_signal_r(str, prefix + "Readback.EGU")

        self.precision = epics_signal_r(int, prefix + "Readback.PREC")
        # If a signal name clashes with a bluesky verb add _ to the attribute name
        self.stop_ = epics_signal_x(prefix + "Stop.PROC")

        motor_signals = DemoMotorMoveSiganls(
            readback=self.readback,
            setpoint=self.setpoint,
            velocity=self.velocity,
            units=self.units,
            precision=self.precision,
            stop=self.stop_,
        )
        self._movable_logic = DemoMotorMoveLogic(motor_signals)

        super().__init__(name)

    @property
    def movable_logic(self) -> DemoMotorMoveLogic:
        return self._movable_logic
