import asyncio
from collections.abc import Callable, Mapping
from functools import cached_property
from typing import TYPE_CHECKING, Any, Generic, TypeVar, get_type_hints

from bluesky.protocols import Location, Reading, Subscribable
from event_model import DataKey
from pydantic import BaseModel

from ._device import Device
from ._protocol import AsyncLocatable, AsyncReadable
from ._signal import SignalR, SignalRW, SignalT, SignalW
from ._signal_backend import SignalBackend, SignalDatatypeT, make_datakey, make_metadata
from ._status import AsyncStatus
from ._utils import Callback, T, gather_dict, merge_gathered_dicts

RawT = TypeVar("RawT")
DerivedT = TypeVar("DerivedT")


class Transform(BaseModel, Generic[RawT, DerivedT]):
    if TYPE_CHECKING:
        # Guard with if type checking so they don't appear in pydantic argument list
        # Ideally they would be:
        #     def raw_to_derived(self, **kwargs: Unpack[RawT]) -> DerivedT: ...
        # but TypedDicts are not valid as generics
        # https://github.com/microsoft/pyright/discussions/7317
        raw_to_derived: Callable[..., DerivedT]
        derived_to_raw: Callable[..., RawT]


TransformT = TypeVar("TransformT", bound=Transform)


def filter_by_type(raw_devices: Mapping[str, Device], type_: type[T]) -> dict[str, T]:
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
        set_derived: Callable[..., AsyncStatus] | None = None,
        **raw_devices: Device,
    ):
        self._transform_cls = transform_cls
        self._set_derived = set_derived
        transform_devices = {
            k: raw_devices.pop(k) for k in self._transform_cls.model_fields
        }
        self._transform_signal_r_s = filter_by_type(transform_devices, SignalR)
        self._raw_devices = raw_devices
        self._derived_callbacks: dict[str, Callback[Reading]] = {}
        self._cached_readings: dict[str, Reading] | None = None
        self._set_names: dict[str, str] = {}

    @cached_property
    def _raw_and_transform_readables(self) -> dict[str, AsyncReadable]:
        return filter_by_type(
            self._raw_devices | self._transform_signal_r_s, AsyncReadable
        )

    @cached_property
    def _raw_and_transform_subscribables(self) -> dict[str, Subscribable]:
        return filter_by_type(
            self._raw_devices | self._transform_signal_r_s, Subscribable
        )

    @cached_property
    def _raw_signal_r_locatables(
        self,
    ) -> tuple[dict[str, SignalR], dict[str, AsyncLocatable]]:
        locatables: dict[str, AsyncLocatable] = {}
        signals: dict[str, SignalR] = {}
        for name, device in self._raw_devices.items():
            if isinstance(device, SignalR):
                signals[name] = device
            elif isinstance(device, AsyncLocatable):
                locatables[name] = device
            else:
                msg = f"{device} is not an instance of SignalR or AsyncLocatable"
                raise TypeError(msg)
        return signals, locatables

    @cached_property
    def _raw_locatables(self) -> dict[str, AsyncLocatable]:
        return filter_by_type(self._raw_devices, AsyncLocatable)

    def _complete_cached_reading(self) -> dict[str, Reading] | None:
        if self._cached_readings and len(self._cached_readings) == len(
            self._raw_and_transform_subscribables
        ):
            return self._cached_readings

    async def get_transform(self) -> TransformT:
        # Get the data from the raw signal rs, this will be cached by the underlying
        # signal if we are subscribing to it
        transform_args = await gather_dict(
            {k: sig.get_value() for k, sig in self._transform_signal_r_s.items()}
        )
        return self._transform_cls(**transform_args)

    async def _get_locations(
        self, locatables: dict[str, AsyncLocatable]
    ) -> dict[str, Location]:
        coros = {k: sig.locate() for k, sig in locatables.items()}
        return await gather_dict(coros)

    async def _get_values(self, signals: dict[str, SignalR]) -> dict[str, Any]:
        coros = {k: sig.get_value() for k, sig in signals.items()}
        return await gather_dict(coros)

    async def get_derived(self) -> dict[str, Any]:
        if raw_and_transform_readings := self._complete_cached_reading():
            # Get the values from the cached readings
            derived_readings = self._make_derived_readings(raw_and_transform_readings)
            return {k: v["value"] for k, v in derived_readings.items()}
        else:
            # Get values from signals, and locations from locatables
            signals, locatables = self._raw_signal_r_locatables
            raw_values, locations, transform = await asyncio.gather(
                self._get_values(signals),
                self._get_locations(locatables),
                self.get_transform(),
            )
            # Merge the readbacks from the locations into a single set of values
            # and convert them to the derived datatype
            raw_values.update({k: v["readback"] for k, v in locations.items()})
            return transform.raw_to_derived(**raw_values)

    async def get_locations(self) -> dict[str, Location]:
        locations, transform = await asyncio.gather(
            self._get_locations(self._raw_locatables), self.get_transform()
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

    def _make_derived_readings(
        self, raw_and_transform_readings: dict[str, Reading]
    ) -> dict[str, Reading]:
        # Calculate the latest timestamp and max severity from them
        timestamp = max(
            raw_and_transform_readings[device.name]["timestamp"]
            for device in self._raw_devices.values()
        )
        alarm_severity = max(
            raw_and_transform_readings[device.name].get("alarm_severity", 0)
            for device in self._raw_devices.values()
        )
        # Make the transform using the values from the readings for those args
        transform_args = {
            k: raw_and_transform_readings[sig.name]["value"]
            for k, sig in self._transform_signal_r_s.items()
        }
        transform = self._transform_cls(**transform_args)
        # Create the raw values from the rest then calculate the derived readings
        # using the transform
        raw_values = {
            k: raw_and_transform_readings[sig.name]["value"]
            for k, sig in self._raw_devices.items()
        }
        derived_readings = {
            name: Reading(
                value=derived, timestamp=timestamp, alarm_severity=alarm_severity
            )
            for name, derived in transform.raw_to_derived(**raw_values).items()
        }
        return derived_readings

    async def get_readings(self) -> dict[str, Reading]:
        if not (raw_and_transform_readings := self._complete_cached_reading()):
            # Read all the raw signals
            raw_and_transform_readings = await merge_gathered_dicts(
                device.read() for device in self._raw_and_transform_readables.values()
            )
        derived_readings = self._make_derived_readings(raw_and_transform_readings)
        return derived_readings

    def _update_cached_reading(self, value: dict[str, Reading]):
        if self._cached_readings is None:
            msg = "Cannot update cached reading as it has not been initialised"
            raise RuntimeError(msg)
        self._cached_readings.update(value)
        if self._complete_cached_reading():
            # We've got a complete set of values, callback on them
            derived_readings = self._make_derived_readings(self._cached_readings)
            for name, callback in self._derived_callbacks.items():
                callback(derived_readings[name])

    def set_callback(self, name: str, callback: Callback[Reading] | None) -> None:
        if callback is None:
            self._derived_callbacks.pop(name, None)
            if not self._derived_callbacks:
                # Remove the callbacks to all the raw devices
                for raw in self._raw_and_transform_subscribables.values():
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
                for raw in self._raw_and_transform_subscribables.values():
                    raw.subscribe(self._update_cached_reading)
            elif self._complete_cached_reading():
                # Callback on the last complete set of readings
                derived_readings = self._make_derived_readings(self._cached_readings)
                callback(derived_readings[name])

    async def set_derived(self, name: str, value: Any):
        if self._set_derived is None:
            msg = "Cannot put as no set_derived method given"
            raise RuntimeError(msg)
        if len(self._set_names) == 1:
            # Only one derived signal, so pass it directly
            await self._set_derived(value)
        else:
            # Need to get the other derived values and update the one that's changing
            derived = await self.get_derived()
            derived[name] = value
            await self._set_derived({self._set_names[k]: v for k, v in derived.items()})

    def _make_signal(
        self,
        signal_cls: type[SignalT],
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalT:
        # Check up front the raw_devices are of the right type for what the signal_cls
        # supports
        if issubclass(signal_cls, SignalR):
            self._raw_and_transform_readables  # noqa: B018
            self._raw_and_transform_subscribables  # noqa: B018
            self._raw_signal_r_locatables  # noqa: B018
        if issubclass(signal_cls, SignalW) and not self._set_derived:
            msg = (
                f"Must define a set_derived method to support derived "
                f"{signal_cls.__name__}s"
            )
            raise ValueError(msg)
        if issubclass(signal_cls, SignalRW):
            self._raw_locatables  # noqa: B018
        self._set_names[name] = set_name or name
        backend = DerivedSignalBackend(datatype, name, self, units, precision)
        return signal_cls(backend)

    def derived_signal_r(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalR[SignalDatatypeT]:
        return self._make_signal(SignalR, datatype, name, set_name, units, precision)

    def derived_signal_w(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalW[SignalDatatypeT]:
        return self._make_signal(SignalW, datatype, name, set_name, units, precision)

    def derived_signal_rw(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalRW[SignalDatatypeT]:
        return self._make_signal(SignalRW, datatype, name, set_name, units, precision)


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

    async def put(self, value: SignalDatatypeT | None, wait: bool):
        if wait is False:
            msg = "Cannot put with wait=False"
            raise RuntimeError(msg)
        if value is None:
            msg = "Must be given a value to put"
            raise RuntimeError(msg)
        await self.transformer.set_derived(self.name, value)

    async def get_datakey(self, source: str) -> DataKey:
        return make_datakey(
            self.datatype or float, await self.get_value(), source, self.metadata
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        readings = await self.transformer.get_readings()
        return readings[self.name]

    async def get_value(self) -> SignalDatatypeT:
        derived = await self.transformer.get_derived()
        return derived[self.name]

    async def get_setpoint(self) -> SignalDatatypeT:
        # TODO: should be get_location
        locations = await self.transformer.get_locations()
        return locations[self.name]["setpoint"]

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        self.transformer.set_callback(self.name, callback)


def _get_return_datatype(func: Callable[..., SignalDatatypeT]) -> type[SignalDatatypeT]:
    args = get_type_hints(func)
    if "return" not in args:
        msg = f"{func} does not have a type hint for it's return value"
        raise TypeError(msg)
    return args["return"]


def _get_first_arg_datatype(
    func: Callable[[SignalDatatypeT], Any],
) -> type[SignalDatatypeT]:
    args = get_type_hints(func)
    args.pop("return", None)
    if not args:
        msg = f"{func} does not have a type hinted argument"
        raise TypeError(msg)
    return list(args.values())[0]


def _make_transformer(
    raw_to_derived: Callable[..., SignalDatatypeT] | None = None,
    set_derived: Callable[[SignalDatatypeT], AsyncStatus] | None = None,
    raw_devices: dict[str, Device] | None = None,
) -> SignalTransformer:
    class DerivedTransform(Transform):
        def raw_to_derived(self, **kwargs) -> dict[str, SignalDatatypeT]:
            if raw_to_derived is None:
                msg = "raw_to_derived not defined"
                raise RuntimeError(msg)
            return {"value": raw_to_derived(**kwargs)}

        def derived_to_raw(self, value: SignalDatatypeT):
            msg = "derived_to_raw not implemented for a single derived_signal"
            raise RuntimeError(msg)

    raw_devices = raw_devices or {}
    return SignalTransformer(DerivedTransform, set_derived=set_derived, **raw_devices)


def derived_signal_r(
    raw_to_derived: Callable[..., SignalDatatypeT],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalR[SignalDatatypeT]:
    transformer = _make_transformer(
        raw_to_derived=raw_to_derived, raw_devices=raw_devices
    )
    return transformer.derived_signal_r(
        datatype=_get_return_datatype(raw_to_derived),
        name="value",
        units=derived_units,
        precision=derived_precision,
    )


def derived_signal_rw(
    raw_to_derived: Callable[..., SignalDatatypeT],
    set_derived: Callable[[SignalDatatypeT], AsyncStatus],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalRW[SignalDatatypeT]:
    raw_to_derived_datatype = _get_return_datatype(raw_to_derived)
    set_derived_datatype = _get_first_arg_datatype(set_derived)
    if raw_to_derived_datatype != set_derived_datatype:
        msg = (
            f"{raw_to_derived} has datatype {raw_to_derived_datatype} "
            f"!= {set_derived_datatype} dataype {set_derived_datatype}"
        )
        raise TypeError(msg)

    transformer = _make_transformer(
        raw_to_derived=raw_to_derived, set_derived=set_derived, raw_devices=raw_devices
    )
    return transformer.derived_signal_rw(
        datatype=raw_to_derived_datatype,
        name="value",
        units=derived_units,
        precision=derived_precision,
    )


def derived_signal_w(
    set_derived: Callable[[SignalDatatypeT], AsyncStatus],
    derived_units: str | None = None,
    derived_precision: int | None = None,
) -> SignalW[SignalDatatypeT]:
    transformer = _make_transformer(set_derived=set_derived)
    return transformer.derived_signal_w(
        datatype=_get_first_arg_datatype(set_derived),
        name="value",
        units=derived_units,
        precision=derived_precision,
    )
