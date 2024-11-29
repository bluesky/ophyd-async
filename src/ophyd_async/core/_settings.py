from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Callable, Iterator, MutableMapping, Sequence
from typing import Any

from bluesky.protocols import Location
from bluesky.utils import Msg, MsgGenerator

from ._device import Device
from ._signal import SignalRW
from ._signal_backend import SignalDatatypeT


class Settings(MutableMapping[SignalRW[Any], Any]):
    def __init__(self, settings: MutableMapping[SignalRW, Any] | None = None):
        self._settings = {}
        self.update(settings or {})

    def __getitem__(self, key: SignalRW[SignalDatatypeT]) -> SignalDatatypeT:
        return self._settings[key]

    def __setitem__(
        self, key: SignalRW[SignalDatatypeT], value: SignalDatatypeT
    ) -> None:
        # Check the types on entry to dict to make sure we can't accidentally
        # add a non-signal type
        if not isinstance(key, SignalRW):
            raise TypeError(f"Expected SignalRW, got {key}")
        if key.datatype and not isinstance(value, key.datatype):
            raise TypeError(f"Expected {key.datatype}, got {value}")
        self._settings[key] = value

    def __delitem__(self, key: SignalRW) -> None:
        del self._settings[key]

    def __iter__(self) -> Iterator[SignalRW]:
        yield from iter(self._settings)

    def __len__(self) -> int:
        return len(self._settings)

    def __or__(self, other: MutableMapping[SignalRW, Any]) -> Settings:
        return Settings(self._settings | dict(other))

    def partition(
        self, predicate: Callable[[SignalRW], bool]
    ) -> tuple[Settings, Settings]:
        where_true, where_false = Settings(), Settings()
        for signal, value in self.items():
            dest = where_true if predicate(signal) else where_false
            dest[signal] = value
        return where_true, where_false

    async def apply(self) -> Settings:
        # Get the current settings of the Device
        original_values = await asyncio.gather(*[sig.get_setpoint() for sig in self])
        original_settings = Settings(dict(zip(self, original_values, strict=True)))
        # Set the signals that need to change
        coros = [
            signal.set(value)
            for signal, value in self.items()
            if value != original_settings[signal]
        ]
        await asyncio.gather(*coros)
        # Return the original settings
        return original_settings


class SettingsProvider:
    @abstractmethod
    def store(self, name: str, data: dict[str, Any]): ...

    @abstractmethod
    def retrieve(self, name: str) -> dict[str, Any]: ...


def _walk_rw_signals(device: Device, path_prefix: str = "") -> dict[str, SignalRW[Any]]:
    """Retrieve all SignalRWs from a device.

    Stores retrieved signals with their dotted attribute paths in a dictionary. Used as
    part of saving and loading a device.

    Parameters
    ----------
    device : Device
        Ophyd device to retrieve read-write signals from.

    path_prefix : str
        For internal use, leave blank when calling the method.

    Returns
    -------
    SignalRWs : dict
        A dictionary matching the string attribute path of a SignalRW with the
        signal itself.

    """
    signals: dict[str, SignalRW[Any]] = {}

    for attr_name, attr in device.children():
        dot_path = f"{path_prefix}{attr_name}"
        if type(attr) is SignalRW:
            signals[dot_path] = attr
        attr_signals = _walk_rw_signals(attr, path_prefix=dot_path + ".")
        signals.update(attr_signals)
    return signals


def _get_values_of_signals(
    signals: dict[str, SignalRW],
) -> MsgGenerator[dict[str, Any]]:
    locations: Sequence[Location] = yield Msg(
        "locate", *signals.values(), squeeze=False
    )
    named_values = {
        name: location["setpoint"]
        for name, location in zip(signals, locations, strict=True)
    }
    return named_values


def store_settings(
    provider: SettingsProvider, name: str, device: Device
) -> MsgGenerator[None]:
    """Plan to recursively walk a Device to find SignalRWs and write a YAML of their
    values.
    """
    signals = _walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    provider.store(name, named_values)


def retrieve_settings(
    provider: SettingsProvider, name: str, device: Device
) -> Settings:
    named_values = provider.retrieve(name)
    signals = _walk_rw_signals(device)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(signal_values)


# Add utility functions x_settings(...) -> Settings that make settings to do
# particular jobs
#
