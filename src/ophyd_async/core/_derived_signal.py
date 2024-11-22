import asyncio
import dataclasses
from abc import abstractmethod
from typing import Generic, Self, TypeVar, get_args

from ._device import Device
from ._protocol import AsyncMovable
from ._signal import SignalR, SignalRW
from ._signal_backend import SignalBackend, SignalDatatypeT


@dataclasses.dataclass
class TransformArgument(Generic[SignalDatatypeT]):
    @classmethod
    async def get_dataclass_from_signals(cls, device: Device) -> Self:
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


RawT = TypeVar("RawT", bound=TransformArgument)
DerivedT = TypeVar("DerivedT", bound=TransformArgument)
ParametersT = TypeVar("ParametersT", bound=TransformArgument)


class TransformMeta(type):
    def __init__(cls, *_):
        if "__orig_bases__" not in cls.__dict__:
            raise TypeError(
                "Transform classes must be defined with Raw, "
                "Derived, and Parameter `TransformArgument`s."
            )
        orig_base = cls.__orig_bases__[0]  # type: ignore
        cls.raw_cls, cls.derived_cls, cls.parameters_cls = get_args(orig_base)


class Transform(Generic[RawT, DerivedT, ParametersT], metaclass=TransformMeta):
    raw_cls: type[RawT]
    derived_cls: type[DerivedT]
    parameters_cls: type[ParametersT]

    @classmethod
    @abstractmethod
    def forward(cls, raw: RawT, parameters: ParametersT) -> DerivedT:
        pass

    @classmethod
    @abstractmethod
    def inverse(cls, derived: DerivedT, parameters: ParametersT) -> RawT:
        pass


class DerivedBackend(Generic[RawT, DerivedT, ParametersT]):
    def __init__(
        self,
        device: Device,
        transform: Transform[RawT, DerivedT, ParametersT],
    ):
        self._device = device
        self._transform = transform

    async def get_parameters(self) -> ParametersT:
        return await self._transform.parameters_cls.get_dataclass_from_signals(
            self._device
        )

    async def get_raw_values(self) -> RawT:
        return await self._transform.raw_cls.get_dataclass_from_signals(self._device)

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

    def derived_signal(self, variable: str) -> SignalRW:
        return SignalRW(DerivedSignalBackend(self, variable))


class DerivedSignalBackend(SignalBackend[float]):
    def __init__(self, backend: DerivedBackend, transform_name: str):
        self._backend = backend
        self._transform_name = transform_name
        super().__init__(float)

    async def get_value(self) -> float:
        derived = await self._backend.get_derived_values()
        return getattr(derived, self._transform_name)

    async def put(self, value: float | None, wait: bool):
        derived = await self._backend.get_derived_values()
        # TODO: we should be calling locate on these as we want to move relative to the
        # setpoint, not readback
        setattr(derived, self._transform_name, value)
        await self._backend.set_derived_values(derived)
