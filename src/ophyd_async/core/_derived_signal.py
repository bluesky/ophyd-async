from collections.abc import Callable
from typing import Any, get_type_hints

from bluesky.protocols import Reading
from event_model import DataKey

from ._signal import SignalR, SignalRW, SignalW
from ._signal_backend import SignalBackend, SignalDatatypeT, make_datakey, make_metadata
from ._status import AsyncStatus
from ._utils import Callback, gather_dict, merge_gathered_dicts


class DerivedSignalBackend(SignalBackend[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT],
        raw_signals: dict[str, SignalRW] | None = None,
        raw_to_derived: Callable[..., SignalDatatypeT] | None = None,
        set_derived: Callable[[SignalDatatypeT, bool], AsyncStatus] | None = None,
        units: str | None = None,
        precision: int | None = None,
    ):
        self.raw_signals = raw_signals or {}
        self._raw_to_derived = raw_to_derived
        self._set_derived = set_derived
        # Add the extra static metadata to the dictionary
        self.metadata = make_metadata(datatype, units, precision)
        self.callbacks: dict[SignalRW, Callback[dict[str, Reading]]] = {}
        self.subscribed_readings: dict[str, Reading] = {}
        super().__init__(datatype)

    @property
    def set_derived(self) -> Callable[[SignalDatatypeT, bool], AsyncStatus]:
        if self._set_derived is None:
            msg = "Cannot put as no set_derived method given"
            raise RuntimeError(msg)
        return self._set_derived

    @property
    def raw_to_derived(self) -> Callable[..., SignalDatatypeT]:
        if self._raw_to_derived is None:
            msg = "Cannot get as no raw_to_derived method given"
            raise RuntimeError(msg)
        return self._raw_to_derived

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
            readings[sig.name]["timestamp"] for sig in self.raw_signals.values()
        )
        alarm_severity = max(
            readings[sig.name].get("alarm_severity", 0)
            for sig in self.raw_signals.values()
        )
        # Calculate a dict of name -> value as needed by raw_derived and call it
        values = {k: readings[sig.name]["value"] for k, sig in self.raw_signals.items()}
        derived = self.raw_to_derived(**values)
        return Reading(
            value=derived, timestamp=timestamp, alarm_severity=alarm_severity
        )

    async def get_reading(self) -> Reading[SignalDatatypeT]:
        # Read all the raw signals
        readings = await merge_gathered_dicts(
            sig.read() for sig in self.raw_signals.values()
        )
        return self._make_reading(readings)

    async def get_value(self) -> SignalDatatypeT:
        coros = {k: sig.get_value() for k, sig in self.raw_signals.items()}
        values = await gather_dict(coros)
        return self.raw_to_derived(**values)

    async def get_setpoint(self) -> SignalDatatypeT:
        coros = {k: sig.get_setpoint() for k, sig in self.raw_signals.items()}
        setpoints = await gather_dict(coros)
        return self.raw_to_derived(**setpoints)

    def _make_raw_callback(
        self,
        signal_key: str,
        signal: SignalRW,
        callback: Callback[Reading[SignalDatatypeT]],
    ) -> Callback[dict[str, Reading]]:
        def raw_callback(value: dict[str, Reading]):
            self.subscribed_readings[signal_key] = value[signal.name]
            if set(self.subscribed_readings) == set(self.raw_signals):
                # We've got a complete set of values, callback on them
                reading = self._make_reading(self.subscribed_readings)
                callback(reading)

        return raw_callback

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        if callback and self.callbacks:
            raise RuntimeError("Cannot set a callback when one is already set")
        # Remove old callbacks
        while self.callbacks:
            sig, raw_callback_ = self.callbacks.popitem()
            sig.clear_sub(raw_callback_)
        # Make new subscription
        if callback:
            for k, sig in self.raw_signals.items():
                raw_callback = self._make_raw_callback(k, sig, callback)
                sig.subscribe(raw_callback)
                self.callbacks[sig] = raw_callback


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


def derived_signal_r(
    raw_to_derived: Callable[..., SignalDatatypeT],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_signals: SignalR,
) -> SignalR[SignalDatatypeT]:
    backend = DerivedSignalBackend(
        datatype=_get_return_datatype(raw_to_derived),
        raw_signals=raw_signals,
        raw_to_derived=raw_to_derived,
        units=derived_units,
        precision=derived_precision,
    )
    return SignalR(backend)


def derived_signal_rw(
    raw_to_derived: Callable[..., SignalDatatypeT],
    set_derived: Callable[[SignalDatatypeT, bool], AsyncStatus],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_signals: SignalRW,
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
        raw_signals=raw_signals,
        raw_to_derived=raw_to_derived,
        set_derived=set_derived,
        units=derived_units,
        precision=derived_precision,
    )
    return SignalRW(backend)


def derived_signal_w(
    set_derived: Callable[[SignalDatatypeT, bool], AsyncStatus],
) -> SignalW[SignalDatatypeT]:
    backend = DerivedSignalBackend(
        datatype=_get_first_arg_datatype(set_derived),
        set_derived=set_derived,
    )
    return SignalW(backend)
