from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from functools import cached_property
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from bluesky.protocols import Location, Reading, Subscribable
from event_model import DataKey

from ._protocol import AsyncLocatable, AsyncReadable
from ._signal_backend import SignalBackend, SignalDatatypeT, make_datakey, make_metadata
from ._utils import (
    Callback,
    ConfinedModel,
    T,
    error_if_none,
    gather_dict,
    merge_gathered_dicts,
)

RawT = TypeVar("RawT")
DerivedT = TypeVar("DerivedT")


class Transform(ConfinedModel, Generic[RawT, DerivedT]):
    """Baseclass for bidirectional transforms for Derived Signals.

    Subclass and add:
    - type hinted parameters that should be fetched from Signals
    - a raw_to_derived method that takes the elements of RawT and returns a DerivedT
    - a derived_to_raw method that takes the elements of DerivedT and returns a RawT

    :example:
    ```python
    class MyRaw(TypedDict):
        raw1: float
        raw2: float

    class MyDerived(TypedDict):
        derived1: float
        derived2: float

    class MyTransform(Transform):
        param1: float

        def raw_to_derived(self, *, raw1: float, raw2: float) -> MyDerived:
            derived1, derived2 = some_maths(self.param1, raw1, raw2)
            return MyDerived(derived1=derived1, derived2=derived2)

        def derived_to_raw(self, *, derived1: float, derived2: float) -> MyRaw:
            raw1, raw2 = some_inverse_maths(self.param1, derived1, derived2)
            return MyRaw(raw1=raw1, raw2=raw2)
    ```
    """

    if TYPE_CHECKING:
        # Guard with if type checking so they don't appear in pydantic argument list
        # Ideally they would be:
        #     def raw_to_derived(self, **kwargs: Unpack[RawT]) -> DerivedT: ...
        # but TypedDicts are not valid as generics
        # https://github.com/microsoft/pyright/discussions/7317
        raw_to_derived: Callable[..., DerivedT]
        derived_to_raw: Callable[..., RawT]


TransformT = TypeVar("TransformT", bound=Transform)


def validate_by_type(raw_devices: Mapping[str, Any], type_: type[T]) -> dict[str, T]:
    filtered_devices: dict[str, T] = {}
    for name, device in raw_devices.items():
        if not isinstance(device, type_):
            msg = f"{device} is not an instance of {type_}"
            raise TypeError(msg)
        filtered_devices[name] = device
    return filtered_devices


class SignalTransformer(Generic[TransformT]):
    def __init__(
        self,
        transform_cls: type[TransformT],
        set_derived: Callable[..., Awaitable[None]] | None,
        set_derived_takes_dict: bool,
        raw_devices,
        raw_constants,
        transform_devices,
        transform_constants,
    ):
        self._transform_cls = transform_cls
        self._set_derived = set_derived
        self._set_derived_takes_dict = set_derived_takes_dict

        self._transform_devices = transform_devices
        self._transform_constants = transform_constants
        self._raw_devices = raw_devices
        self._raw_constants = raw_constants

        self._derived_callbacks: dict[str, Callback[Reading]] = {}
        self._cached_readings: dict[str, Reading] | None = None

    @cached_property
    def raw_locatables(self) -> dict[str, AsyncLocatable]:
        return validate_by_type(self._raw_devices, AsyncLocatable)

    @cached_property
    def transform_readables(self) -> dict[str, AsyncReadable]:
        return validate_by_type(self._transform_devices, AsyncReadable)

    @cached_property
    def raw_and_transform_readables(self) -> dict[str, AsyncReadable]:
        return validate_by_type(
            self._raw_devices | self._transform_devices, AsyncReadable
        )

    @cached_property
    def raw_and_transform_subscribables(self) -> dict[str, Subscribable]:
        return validate_by_type(
            self._raw_devices | self._transform_devices, Subscribable
        )

    def _complete_cached_reading(self) -> dict[str, Reading] | None:
        if self._cached_readings and len(self._cached_readings) == len(
            self.raw_and_transform_subscribables
        ):
            return self._cached_readings
        return None

    def _make_transform_from_readings(
        self, transform_readings: dict[str, Reading]
    ) -> TransformT:
        # Make the transform using the values from the readings for those args
        transform_args = {
            k: transform_readings[sig.name]["value"]
            for k, sig in self.transform_readables.items()
        }
        return self._transform_cls(**(transform_args | self._transform_constants))

    def _make_derived_readings(
        self, raw_and_transform_readings: dict[str, Reading]
    ) -> dict[str, Reading]:
        # Calculate the latest timestamp and max severity from them
        timestamp = max(
            raw_and_transform_readings[device.name]["timestamp"]
            for device in self.raw_and_transform_subscribables.values()
        )
        alarm_severity = max(
            raw_and_transform_readings[device.name].get("alarm_severity", 0)
            for device in self.raw_and_transform_subscribables.values()
        )
        # Make the transform using the values from the readings for those args
        transform = self._make_transform_from_readings(raw_and_transform_readings)
        # Create the raw values from the rest then calculate the derived readings
        # using the transform
        # Extend dictionary with values of any Constants passed as arguments
        raw_values = {
            **{
                k: raw_and_transform_readings[sig.name]["value"]
                for k, sig in self._raw_devices.items()
            },
            **self._raw_constants,
        }

        derived_readings = {
            name: Reading(
                value=derived, timestamp=timestamp, alarm_severity=alarm_severity
            )
            for name, derived in transform.raw_to_derived(**raw_values).items()
        }
        return derived_readings

    async def get_transform(self) -> TransformT:
        if raw_and_transform_readings := self._complete_cached_reading():
            transform_readings = raw_and_transform_readings
        else:
            transform_readings = await merge_gathered_dicts(
                device.read() for device in self.transform_readables.values()
            )
        return self._make_transform_from_readings(transform_readings)

    async def get_derived_readings(self) -> dict[str, Reading]:
        if not (raw_and_transform_readings := self._complete_cached_reading()):
            raw_and_transform_readings = await merge_gathered_dicts(
                device.read() for device in self.raw_and_transform_readables.values()
            )
        return self._make_derived_readings(raw_and_transform_readings)

    async def get_derived_values(self) -> dict[str, Any]:
        derived_readings = await self.get_derived_readings()
        return {k: v["value"] for k, v in derived_readings.items()}

    def _update_cached_reading(self, value: dict[str, Reading]):
        _cached_readings = error_if_none(
            self._cached_readings,
            "Cannot update cached reading as it has not been initialised",
        )

        _cached_readings.update(value)
        if self._complete_cached_reading():
            # We've got a complete set of values, callback on them
            derived_readings = self._make_derived_readings(_cached_readings)
            for name, callback in self._derived_callbacks.items():
                callback(derived_readings[name])

    def set_callback(self, name: str, callback: Callback[Reading] | None) -> None:
        if callback is None:
            self._derived_callbacks.pop(name, None)
            if not self._derived_callbacks:
                # Remove the callbacks to all the raw devices
                for raw in self.raw_and_transform_subscribables.values():
                    raw.clear_sub(self._update_cached_reading)
                # and clear the cached readings that will now be stale
                self._cached_readings = None
        else:
            if name in self._derived_callbacks:
                msg = f"Callback already set for {name}"
                raise RuntimeError(msg)
            self._derived_callbacks[name] = callback
            if self._cached_readings is None:
                # Add the callbacks to all the raw devices, this will run the first
                # callback
                self._cached_readings = {}
                for raw in self.raw_and_transform_subscribables.values():
                    raw.subscribe(self._update_cached_reading)
            elif self._complete_cached_reading():
                # Callback on the last complete set of readings
                derived_readings = self._make_derived_readings(self._cached_readings)
                callback(derived_readings[name])

    async def get_locations(self) -> dict[str, Location]:
        locations, transform = await asyncio.gather(
            gather_dict({k: sig.locate() for k, sig in self.raw_locatables.items()}),
            self.get_transform(),
        )
        raw_setpoints = {k: v["setpoint"] for k, v in locations.items()}
        raw_readbacks = {k: v["readback"] for k, v in locations.items()}
        derived_setpoints = transform.raw_to_derived(**raw_setpoints)
        derived_readbacks = transform.raw_to_derived(**raw_readbacks)
        return {
            name: Location(
                setpoint=derived_setpoints[name],
                readback=derived_readbacks[name],
            )
            for name in derived_setpoints
        }

    async def set_derived(self, name: str, value: Any):
        _set_derived = error_if_none(
            self._set_derived,
            "Cannot put as no set_derived method given",
        )
        if self._set_derived_takes_dict:
            # Need to get the other derived values and update the one that's changing
            derived = await self.get_locations()
            setpoints = {k: v["setpoint"] for k, v in derived.items()}
            setpoints[name] = value
            await _set_derived(setpoints)
        else:
            # Only one derived signal, so pass it directly
            await _set_derived(value)


class DerivedSignalBackend(SignalBackend[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        transformer: SignalTransformer,
        units: str | None = None,
        precision: int | None = None,
    ):
        self.name = name
        self.transformer = transformer
        # Add the extra static metadata to the dictionary
        self.metadata = make_metadata(datatype, units, precision)
        super().__init__(datatype)

    def source(self, name: str, read: bool) -> str:
        return f"derived://{name}"

    async def connect(self, timeout: float):
        # Assume that the underlying signals are already connected
        pass

    def set_value(self, value: SignalDatatypeT):
        msg = (
            "Cannot set the value of a derived signal, "
            "set the underlying raw signals instead"
        )
        raise RuntimeError(msg)

    async def put(self, value: SignalDatatypeT | None, wait: bool) -> None:
        if wait is False:
            msg = "Cannot put with wait=False"
            raise RuntimeError(msg)

        value = error_if_none(
            value,
            "Must be given a value to put",
        )

        await self.transformer.set_derived(self.name, value)

    async def get_datakey(self, source: str) -> DataKey:
        return make_datakey(
            self.datatype or float, await self.get_value(), source, self.metadata
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        readings = await self.transformer.get_derived_readings()
        return readings[self.name]

    async def get_value(self) -> SignalDatatypeT:
        derived = await self.transformer.get_derived_values()
        return derived[self.name]

    async def get_setpoint(self) -> SignalDatatypeT:
        # TODO: should be get_location
        locations = await self.transformer.get_locations()
        return locations[self.name]["setpoint"]

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        self.transformer.set_callback(self.name, callback)
