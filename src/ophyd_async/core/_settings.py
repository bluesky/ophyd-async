from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any

import bluesky.plan_stubs as bps
from bluesky.utils import MsgGenerator

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
    async def get_all_values() -> dict[str, Any]:
        values = await asyncio.gather(sig.get_value() for sig in signals.values())
        return dict(zip(signals, values, strict=True))

    (task,) = yield from bps.wait_for([get_all_values])
    return task.result()


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


def apply_settings(settings: Settings) -> MsgGenerator[None]:
    if settings:
        for signal, value in settings.items():
            yield from bps.abs_set(signal, value, "apply_settings")
        yield from bps.wait("apply_settings")


# Add a plan settings_to_change(device: Device, settings: Settings) ->
# MsgGenerator[Settings] that discards settings that are already at the right
# value, erroring if they aren't in the Device
def _settings_to_change(
    device: Device, settings: Settings
) -> MsgGenerator[tuple[Settings, Settings]]:
    # Get the current settings of the Device
    signals = _walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    original_settings = Settings(signal_values)
    # Check that the signals in settings are actually in the Device
    unknown_signals = set(settings) - set(original_settings)
    assert not unknown_signals, f"Signal {unknown_signals} are not in {device}"
    # Work out which signals need to change
    signals_to_change = {
        signal: value
        for signal, value in settings.items()
        if original_settings[signal] != value
    }
    # Return the settings that need to change and their original values
    return Settings(signals_to_change), original_settings


Reverter = Callable[[], MsgGenerator[None]]


def only_set_unequal_signals(
    apply_device_settings: Callable[[Settings], MsgGenerator[None]],
) -> Callable[[Device, Settings], MsgGenerator[Reverter]]:
    def apply_to_unequal(device: Device, settings: Settings) -> MsgGenerator[Reverter]:
        to_change, original = yield from _settings_to_change(device, settings)
        yield from apply_device_settings(to_change)

        def revert_settings() -> MsgGenerator[None]:
            to_change_back, _ = yield from _settings_to_change(device, original)
            yield from apply_device_settings(to_change_back)

        return revert_settings

    return apply_to_unequal


@only_set_unequal_signals
def apply_panda_settings(settings: Settings) -> MsgGenerator[None]:
    units, others = settings.partition(lambda signal: signal.name.endswith("_units"))
    yield from apply_settings(units)
    yield from apply_settings(others)


# Add utility functions x_settings(...) -> Settings that make settings to do
# particular jobs
#
