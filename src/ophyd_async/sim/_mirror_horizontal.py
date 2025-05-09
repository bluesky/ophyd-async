import asyncio
from typing import TypedDict

from bluesky.protocols import Movable

from ophyd_async.core import AsyncStatus, DerivedSignalFactory, Device

from ._mirror_vertical import TwoJackDerived, TwoJackTransform
from ._motor import SimMotor


class HorizontalMirrorDerived(TypedDict):
    x: float
    roll: float


class HorizontalMirror(Device, Movable):
    def __init__(self, name=""):
        # Raw signals
        self.x1 = SimMotor()
        self.x2 = SimMotor()
        # Parameter
        # This could also be set as 'soft_signal_rw(float, initial_value=1)'
        self.x1_x2_distance = 1.0
        # Derived signals
        self._factory = DerivedSignalFactory(
            TwoJackTransform,
            self._set_mirror,
            jack1=self.x1,
            jack2=self.x2,
            distance=self.x1_x2_distance,
        )
        self.x = self._factory.derived_signal_rw(float, "height")
        self.roll = self._factory.derived_signal_rw(float, "angle")
        super().__init__(name=name)

    async def _set_mirror(self, derived: TwoJackDerived) -> None:
        transform = await self._factory.transform()
        raw = transform.derived_to_raw(**derived)
        await asyncio.gather(
            self.x1.set(raw["jack1"]),
            self.x2.set(raw["jack2"]),
        )

    @AsyncStatus.wrap
    async def set(self, value: HorizontalMirrorDerived) -> None:
        await self._set_mirror(TwoJackDerived(height=value["x"], angle=value["roll"]))
