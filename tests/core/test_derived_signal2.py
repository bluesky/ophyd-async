import asyncio
from collections.abc import Callable
from typing import Any, Awaitable, Generic, TypedDict, TypeVar, cast

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel

from ophyd_async.core import (
    AsyncStatus,
    Device,
    SignalBackend,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    SignalW,
    StrictEnum,
    soft_signal_rw,
)
from ophyd_async.sim import SimMotor


class DerivedSignalBackend(SignalBackend[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT],
        setter: Callable[[SignalDatatypeT, bool], AsyncStatus] | None = None,
    ):
        self._setter = setter
        super().__init__(datatype)

    def source(self, name: str, read: bool) -> str:
        return f"derived://{name}"

    async def connect(self, timeout: float):
        pass

    async def put(self, value: SignalDatatypeT | None, wait: bool):
        if self._setter is None:
            msg = "No setter method defined"
            raise RuntimeError(msg)
        if value is None:
            msg = "Must be given a value to put"
            raise RuntimeError(msg)
        await self._setter(value, wait)

    @abstractmethod
    async def get_datakey(self, source: str) -> DataKey:
        """Metadata like source, dtype, shape, precision, units."""

    @abstractmethod
    async def get_reading(self) -> Reading[SignalDatatypeT]:
        """Return the current value, timestamp and severity."""

    @abstractmethod
    async def get_value(self) -> SignalDatatypeT:
        """Return the current value."""

    @abstractmethod
    async def get_setpoint(self) -> SignalDatatypeT:
        """Return the point that a signal was requested to move to."""

    @abstractmethod
    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        """Observe changes to the current value, timestamp and severity."""


def derived_signal_r(
    getter: Callable[..., SignalDatatypeT],
    **kwargs: SignalR,
) -> SignalR[SignalDatatypeT]: ...


def derived_signal_rw(
    getter: Callable[..., SignalDatatypeT],
    setter: Callable[[SignalDatatypeT], AsyncStatus],
    **kwargs: SignalRW,
) -> SignalRW[SignalDatatypeT]: ...


def derived_signal_w(
    setter: Callable[[SignalDatatypeT], AsyncStatus],
    **kwargs: SignalW,
) -> SignalW[SignalDatatypeT]: ...


RawT = TypeVar("RawT", bound=dict[str, Any])
DerivedT = TypeVar("DerivedT", bound=dict[str, Any])


class Transform(BaseModel, Generic[RawT, DerivedT]):
    raw_to_derived: Callable[..., DerivedT]
    derived_to_raw: Callable[..., RawT]


TransformT = TypeVar("TransformT", bound=Transform)


class SignalTransformer(Generic[TransformT]):
    def __init__(
        self,
        transform_cls: type[TransformT],
        setter: Callable[..., AsyncStatus],
        **kwargs: Device,
    ):
        pass

    def derived_signal_rw(
        self, datatype: type[SignalDatatypeT], name: str
    ) -> SignalRW[SignalDatatypeT]: ...

    def get_transform(self) -> TransformT: ...


F = TypeVar("F", float, npt.NDArray[np.float64])


class TwoJackRaw(TypedDict, Generic[F]):
    jack1: F
    jack2: F


class TwoJackDerived(TypedDict, Generic[F]):
    height: F
    angle: F


class TwoJackTransform(Transform):
    distance: float

    def raw_to_derived(self, jack1: F, jack2: F) -> TwoJackDerived[F]:
        diff = jack2 - jack1
        return TwoJackDerived(
            height=jack1 + diff / 2,
            # need the case as returns numpy float rather than float64, but this
            # is ok at runtime
            angle=cast(F, np.atan(diff / self.distance)),
        )

    def derived_to_raw(self, height: F, angle: F) -> TwoJackRaw[F]:
        diff = cast(F, np.tan(angle) * self.distance)
        return TwoJackRaw(
            jack1=height - diff / 2,
            jack2=height + diff / 2,
        )


class Mirror(Device):
    def __init__(self, name=""):
        # Raw signals
        self.x1 = SimMotor()
        self.x2 = SimMotor()
        # Parameter
        self.x1_x2_distance = soft_signal_rw(float)
        # Derived signals
        self._transformer = SignalTransformer(
            TwoJackTransform,
            self.set,
            jack1=self.x1,
            jack2=self.x2,
            distance=self.x1_x2_distance,
        )
        self.x = self._transformer.derived_signal_rw(float, "height")
        self.roll = self._transformer.derived_signal_rw(float, "angle")
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def set(self, derived: TwoJackDerived[float]) -> None:
        raw = self._transformer.get_transform().derived_to_raw(**derived)
        await asyncio.gather(
            self.x1.set(raw["jack1"]),
            self.x2.set(raw["jack2"]),
        )


class BeamstopPosition(StrictEnum):
    IN_POSITION = "In position"
    OUT_OF_POSITION = "Out of position"


class Beamstop(Device):
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


class Positioner(Device):
    def __init__(self, name=""):
        # Raw signals
        self.x = soft_signal_rw(float)
        self.y = soft_signal_rw(float)
        # Derived signals
        self.position = derived_signal_rw(
            self._get_position, self.set, x=self.x, y=self.y
        )
        super().__init__(name=name)

    def _get_position(self, x: float, y: float) -> BeamstopPosition:
        if abs(x) < 1 and abs(y) < 2:
            return BeamstopPosition.IN_POSITION
        else:
            return BeamstopPosition.OUT_OF_POSITION

    @AsyncStatus.wrap
    async def set(self, value: BeamstopPosition):
        match value:
            case BeamstopPosition.IN_POSITION:
                await asyncio.gather(self.x.set(0), self.y.set(1))
            case BeamstopPosition.OUT_OF_POSITION:
                await asyncio.gather(self.x.set(5), self.y.set(5))
