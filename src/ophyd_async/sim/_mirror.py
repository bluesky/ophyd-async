import asyncio
import math
from typing import TypedDict

from bluesky.protocols import Movable

from ophyd_async.core import (
    AsyncStatus,
    DerivedSignalFactory,
    Device,
    Transform,
    soft_signal_rw,
)

from ._motor import SimMotor


class TwoJackRaw(TypedDict):
    jack1: float
    jack2: float


class TwoJackDerived(TypedDict):
    height: float
    angle: float


class TwoJackTransform(Transform):
    distance: float

    def raw_to_derived(self, *, jack1: float, jack2: float) -> TwoJackDerived:
        diff = jack2 - jack1
        return TwoJackDerived(
            height=jack1 + diff / 2,
            # need the cast as returns numpy float rather than float64, but this
            # is ok at runtime
            angle=math.atan(diff / self.distance),
        )

    def derived_to_raw(self, *, height: float, angle: float) -> TwoJackRaw:
        diff = math.tan(angle) * self.distance
        return TwoJackRaw(
            jack1=height - diff / 2,
            jack2=height + diff / 2,
        )


class MirrorDerived(TypedDict):
    x: float
    roll: float


class Mirror(Device, Movable):
    def __init__(self, name=""):
        # Raw signals
        self.x1 = SimMotor()
        self.x2 = SimMotor()
        # Parameter
        self.x1_x2_distance = soft_signal_rw(float, initial_value=1)
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
    async def set(self, value: MirrorDerived) -> None:
        await self._set_mirror(TwoJackDerived(height=value["x"], angle=value["roll"]))
