from __future__ import annotations

import asyncio

from ophyd_async.core import (
    Device,
    DeviceVector,
    StandardReadable,
    StrictEnum,
    derived_signal_r,
    derived_signal_rw,
    derived_signal_w,
    soft_signal_rw,
)


class BeamstopPosition(StrictEnum):
    IN_POSITION = "In position"
    OUT_OF_POSITION = "Out of position"


class ReadOnlyBeamstop(Device):
    """Reads from 2 motors to work out if the beamstop is in position.

    E.g. bps.rd(beamstop.position)
    """

    def __init__(self, name=""):
        # Raw signals
        self.x = soft_signal_rw(float)
        self.y = soft_signal_rw(float)
        # Derived signals
        self.position = derived_signal_r(self._get_position, x=self.x, y=self.y)
        super().__init__(name=name)

    def _get_position(self, x: float, y: float) -> BeamstopPosition:
        if abs(x) < 1 and abs(y) < 2:
            return BeamstopPosition.IN_POSITION
        else:
            return BeamstopPosition.OUT_OF_POSITION


class MovableBeamstop(Device):
    """As well as reads, this one allows you to move it.

    E.g. bps.mv(beamstop.position, BeamstopPosition.IN_POSITION)
    """

    def __init__(self, name=""):
        # Raw signals
        self.x = soft_signal_rw(float)
        self.y = soft_signal_rw(float)
        # Derived signals
        self.position = derived_signal_rw(
            self._get_position, self._set_from_position, x=self.x, y=self.y
        )
        super().__init__(name=name)

    def _get_position(self, x: float, y: float) -> BeamstopPosition:
        if abs(x) < 1 and abs(y) < 2:
            return BeamstopPosition.IN_POSITION
        else:
            return BeamstopPosition.OUT_OF_POSITION

    async def _set_from_position(self, position: BeamstopPosition) -> None:
        if position == BeamstopPosition.IN_POSITION:
            await asyncio.gather(self.x.set(0), self.y.set(0))
        else:
            await asyncio.gather(self.x.set(3), self.y.set(5))


class Exploder(StandardReadable):
    """This one takes a value and sets all its signal to that value.

    This allows convenience "set all" functions, while the individual
    signals are still free to be set to different values.
    """

    def __init__(self, num_signals: int, name=""):
        with self.add_children_as_readables():
            self.signals = DeviceVector(
                {i: soft_signal_rw(int, units="cts") for i in range(1, num_signals + 1)}
            )
        self.set_all = derived_signal_w(self._set_all, derived_units="cts")
        super().__init__(name=name)

    async def _set_all(self, value: int) -> None:
        coros = [sig.set(value) for sig in self.signals.values()]
        await asyncio.gather(*coros)
