import asyncio
from collections.abc import Callable, Mapping
from functools import cached_property
from typing import Any, get_type_hints

from bluesky.protocols import Location, Reading, Subscribable
from event_model import DataKey

from ._device import Device
from ._protocol import AsyncLocatable, AsyncReadable
from ._signal import SignalR, SignalRW, SignalT, SignalW
from ._signal_backend import SignalBackend, SignalDatatypeT, make_datakey, make_metadata
from ._status import AsyncStatus
from ._utils import Callback, T, gather_dict, merge_gathered_dicts


def filter_by_type(raw_devices: Mapping[str, Device], type_: type[T]) -> dict[str, T]:
    filtered_devices: dict[str, T] = {}
    for name, device in raw_devices.items():
        if not isinstance(device, type_):
            msg = f"{device} is not an instance of {type_}"
            raise TypeError(msg)
        filtered_devices[name] = device
    return filtered_devices


class DerivedSignalBackend(SignalBackend[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT],
        raw_devices: Mapping[str, Device] | None = None,
        raw_to_derived: Callable[..., SignalDatatypeT] | None = None,
        set_derived: Callable[[SignalDatatypeT, bool], AsyncStatus] | None = None,
        units: str | None = None,
        precision: int | None = None,
    ):
        self._raw_devices = raw_devices or {}
        self._raw_to_derived = raw_to_derived
        self._set_derived = set_derived
        # Add the extra static metadata to the dictionary
        self.metadata = make_metadata(datatype, units, precision)
        self.callback: Callback[dict[str, Reading]] | None = None
        self.subscribed_readings: dict[str, Reading] = {}
        super().__init__(datatype)

    @cached_property
    def set_derived(self) -> Callable[[SignalDatatypeT, bool], AsyncStatus]:
        if self._set_derived is None:
            msg = "Cannot put as no set_derived method given"
            raise RuntimeError(msg)
        return self._set_derived

    @cached_property
    def raw_to_derived(self) -> Callable[..., SignalDatatypeT]:
        if self._raw_to_derived is None:
            msg = "Cannot get as no raw_to_derived method given"
            raise RuntimeError(msg)
        return self._raw_to_derived

    @cached_property
    def raw_readables(self) -> dict[str, AsyncReadable]:
        return filter_by_type(self._raw_devices, AsyncReadable)

    @cached_property
    def raw_signal_r_locatables(
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
    def raw_locatables(self) -> dict[str, AsyncLocatable]:
        return filter_by_type(self._raw_devices, AsyncLocatable)

    @cached_property
    def raw_subscribables(self) -> dict[str, Subscribable]:
        return filter_by_type(self._raw_devices, Subscribable)

    def source(self, name: str, read: bool) -> str:
        return f"derived://{name}"

    async def connect(self, timeout: float):
        # Assume that the underlying signals are already connected
        pass

    async def put(self, value: SignalDatatypeT | None, wait: bool):
        if value is None:
            msg = "Must be given a value to put"
            raise RuntimeError(msg)
        await self.set_derived(value, wait)

    async def get_datakey(self, source: str) -> DataKey:
        return make_datakey(
            self.datatype or float, await self.get_value(), source, self.metadata
        )

    def _make_reading(self, readings: dict[str, Reading]) -> Reading[SignalDatatypeT]:
        # Calculate the latest timestamp and max severity from them
        timestamp = max(
            readings[device.name]["timestamp"] for device in self._raw_devices.values()
        )
        alarm_severity = max(
            readings[device.name].get("alarm_severity", 0)
            for device in self._raw_devices.values()
        )
        # Calculate a dict of name -> value as needed by raw_derived and call it
        values = {
            k: readings[sig.name]["value"] for k, sig in self._raw_devices.items()
        }
        derived = self.raw_to_derived(**values)
        return Reading(
            value=derived, timestamp=timestamp, alarm_severity=alarm_severity
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        # Read all the raw signals
        readings = await merge_gathered_dicts(
            device.read() for device in self.raw_readables.values()
        )
        return self._make_reading(readings)

    async def _get_locations(
        self, locatables: dict[str, AsyncLocatable]
    ) -> dict[str, Location]:
        coros = {k: sig.locate() for k, sig in locatables.items()}
        return await gather_dict(coros)

    async def _get_values(self, signals: dict[str, SignalR]) -> dict[str, Any]:
        coros = {k: sig.get_value() for k, sig in signals.items()}
        return await gather_dict(coros)

    async def get_value(self) -> SignalDatatypeT:
        # Get values from signals, and locations from locatables
        signals, locatables = self.raw_signal_r_locatables
        values, locations = await asyncio.gather(
            self._get_values(signals), self._get_locations(locatables)
        )
        # Merge the readbacks from the locations into a single set of values
        # and convert them to the derived datatype
        values.update({k: v["readback"] for k, v in locations.items()})
        return self.raw_to_derived(**values)

    async def get_setpoint(self) -> SignalDatatypeT:
        # TODO: should be get_location
        locations = await self._get_locations(self.raw_locatables)
        setpoints = {k: v["setpoint"] for k, v in locations.items()}
        return self.raw_to_derived(**setpoints)

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback and self.callback:
            raise RuntimeError("Cannot set a callback when one is already set")
        # Remove old subscriptions
        if self.callback:
            for sig in self.raw_subscribables.values():
                sig.clear_sub(self.callback)
        # Make new subscription
        if callback:
            for sig in self.raw_subscribables.values():

                def raw_callback(value: dict[str, Reading]):
                    self.subscribed_readings.update(value)
                    if len(self.subscribed_readings) == len(self.raw_subscribables):
                        # We've got a complete set of values, callback on them
                        reading = self._make_reading(self.subscribed_readings)
                        callback(reading)

                sig.subscribe(raw_callback)
                self.callback = raw_callback


def _get_return_datatype(func: Callable[..., SignalDatatypeT]) -> type[SignalDatatypeT]:
    args = get_type_hints(func)
    if "return" not in args:
        msg = f"{func} does not have a type hint for it's return value"
        raise TypeError(msg)
    return args["return"]


def _get_first_arg_datatype(
    func: Callable[[SignalDatatypeT, bool], Any],
) -> type[SignalDatatypeT]:
    args = get_type_hints(func)
    args.pop("return", None)
    if not args:
        msg = f"{func} does not have a type hinted argument"
        raise TypeError(msg)
    return list(args.values())[0]


def _make_signal(signal_cls: type[SignalT], backend: DerivedSignalBackend) -> SignalT:
    if issubclass(signal_cls, SignalR):
        backend.raw_readables  # noqa: B018
        backend.raw_subscribables  # noqa: B018
        backend.raw_signal_r_locatables  # noqa: B018
    if issubclass(signal_cls, SignalRW):
        backend.raw_locatables  # noqa: B018
    return signal_cls(backend)


def derived_signal_r(
    raw_to_derived: Callable[..., SignalDatatypeT],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalR[SignalDatatypeT]:
    backend = DerivedSignalBackend(
        datatype=_get_return_datatype(raw_to_derived),
        raw_devices=raw_devices,
        raw_to_derived=raw_to_derived,
        units=derived_units,
        precision=derived_precision,
    )
    return _make_signal(SignalR, backend)


def derived_signal_rw(
    raw_to_derived: Callable[..., SignalDatatypeT],
    set_derived: Callable[[SignalDatatypeT, bool], AsyncStatus],
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
    backend = DerivedSignalBackend(
        datatype=raw_to_derived_datatype,
        raw_devices=raw_devices,
        raw_to_derived=raw_to_derived,
        set_derived=set_derived,
        units=derived_units,
        precision=derived_precision,
    )
    return _make_signal(SignalRW, backend)


def derived_signal_w(
    set_derived: Callable[[SignalDatatypeT, bool], AsyncStatus],
) -> SignalW[SignalDatatypeT]:
    backend = DerivedSignalBackend(
        datatype=_get_first_arg_datatype(set_derived),
        set_derived=set_derived,
    )
    return _make_signal(SignalW, backend)
