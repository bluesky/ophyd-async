import asyncio
import dataclasses
from collections.abc import Iterator
from typing import Generic, TypeVar, get_type_hints

import numpy as np

from ._device import Device
from ._protocol import AsyncMovable
from ._signal import SignalR, SignalRW, soft_signal_rw
from ._signal_backend import Array1D, SignalBackend
from ._status import AsyncStatus
from ._utils import T, get_origin_class

RawSignalsT = TypeVar("RawSignalsT")
ParametersSignalsT = TypeVar("ParametersSignalsT")
RawT = TypeVar("RawT")
DerivedT = TypeVar("DerivedT")
ParametersT = TypeVar("ParametersT")


class Transform(Generic[RawT, DerivedT, ParametersT]):
    def forward(self, raw: RawT, parameters: ParametersT) -> DerivedT: ...
    def inverse(self, derived: DerivedT, parameters: ParametersT) -> RawT: ...


F_contra = TypeVar("F_contra", bound=float | Array1D[np.float64], contravariant=True)


# TODO: should this be a TypedDict?
@dataclasses.dataclass
class SlitsRaw(Generic[F_contra]):
    top: F_contra
    bottom: F_contra


@dataclasses.dataclass
class SlitsDerived(Generic[F_contra]):
    gap: F_contra
    centre: F_contra


@dataclasses.dataclass
class SlitsParameters:
    gap_offset: float


class SlitsTransform(Transform[SlitsRaw, SlitsDerived, SlitsParameters]):
    def forward(
        self, raw: SlitsRaw[F_contra], parameters: SlitsParameters
    ) -> SlitsDerived[F_contra]:
        return SlitsDerived(
            gap=raw.top - raw.bottom + parameters.gap_offset,
            centre=(raw.top + raw.bottom) / 2,
        )

    def inverse(
        self, derived: SlitsDerived[F_contra], parameters: SlitsParameters
    ) -> SlitsRaw[F_contra]:
        half_gap = (derived.gap - parameters.gap_offset) / 2
        return SlitsRaw(
            top=derived.centre + half_gap,
            bottom=derived.centre - half_gap,
        )


def _get_dataclass_args(method) -> Iterator[type]:
    for k, v in get_type_hints(method):
        cls = get_origin_class(v)
        if k != "return" and dataclasses.is_dataclass(cls):
            yield cls


async def _get_dataclass_from_signals(cls: type[T], device: Device) -> T:
    coros = {}
    for field in dataclasses.fields(cls):
        sig = getattr(device, field.name)
        assert isinstance(
            sig, SignalR
        ), f"{device.name}.{field.name} is {sig}, not a Signal"
        coros[field.name] = sig.get_value()
    results = await asyncio.gather(*coros.values())
    kwargs = dict(zip(coros, results, strict=True))
    return cls(**kwargs)


class DerivedBackend(Generic[RawT, DerivedT, ParametersT]):
    def __init__(
        self,
        device: Device,
        transform: Transform[RawT, DerivedT, ParametersT],
    ):
        self._device = device
        self._transform = transform
        self._raw_cls, self._param_cls = _get_dataclass_args(self._transform.forward)

    async def get_parameters(self) -> ParametersT:
        return await _get_dataclass_from_signals(self._param_cls, self._device)

    async def get_raw_values(self) -> RawT:
        return await _get_dataclass_from_signals(self._raw_cls, self._device)

    async def get_derived_values(self) -> DerivedT:
        raw, parameters = await asyncio.gather(
            self.get_raw_values(), self.get_parameters()
        )
        return self._transform.forward(raw, parameters)

    async def set_derived_values(self, derived: DerivedT):
        assert isinstance(self._device, AsyncMovable)
        await self._device.set(derived)

    async def calculate_raw_values(self, derived: DerivedT) -> RawT:
        return self._transform.inverse(derived, await self.get_parameters())

    def derived_signal(self, variable: str) -> SignalRW[float]:
        return SignalRW(DerivedSignalBackend(self, variable))


class DerivedSignalBackend(SignalBackend[float]):
    def __init__(self, backend: DerivedBackend, variable: str):
        self._backend = backend
        self._variable = variable
        super().__init__(float)

    async def get_value(self) -> float:
        derived = await self._backend.get_derived_values()
        return getattr(derived, self._variable)

    async def put(self, value: float | None, wait: bool):
        derived = await self._backend.get_derived_values()
        # TODO: we should be calling locate on these as we want to move relative to the
        # setpoint, not readback
        setattr(derived, self._variable, value)
        await self._backend.set_derived_values(derived)


class Slits(Device):
    def __init__(self, name=""):
        self._backend = DerivedBackend(self, SlitsTransform())
        # Raw signals
        self.top = soft_signal_rw(float)
        self.bottom = soft_signal_rw(float)
        # Parameter
        self.gap_offset = soft_signal_rw(float)
        # Derived signals
        self.gap = self._backend.derived_signal("gap")
        self.centre = self._backend.derived_signal("centre")
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def set(self, derived: SlitsDerived[float]) -> None:
        raw: SlitsRaw[float] = await self._backend.calculate_raw_values(derived)
        await asyncio.gather(self.top.set(raw.top), self.bottom.set(raw.bottom))
