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


class VerticalMirror(Device, Movable[TwoJackDerived]):
    def __init__(self, name=""):
        # Raw signals
        self.y1 = SimMotor()
        self.y2 = SimMotor()
        # Parameter
        # This could also be set as '1.0', if constant.
        self.y1_y2_distance = soft_signal_rw(float, initial_value=1)
        # Derived signals
        self._factory = DerivedSignalFactory(
            TwoJackTransform,
            self.set,
            jack1=self.y1,
            jack2=self.y2,
            distance=self.y1_y2_distance,
        )
        self.height = self._factory.derived_signal_rw(float, "height")
        self.angle = self._factory.derived_signal_rw(float, "angle")
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def set(self, derived: TwoJackDerived) -> None:  # type: ignore until bluesky 1.13.2
        transform = await self._factory.transform()
        raw = transform.derived_to_raw(**derived)
        await asyncio.gather(
            self.y1.set(raw["jack1"]),
            self.y2.set(raw["jack2"]),
        )
