from __future__ import annotations

from collections.abc import Iterator, MutableMapping, Sequence
from pathlib import Path
from typing import Any

import bluesky.plan_stubs as bps
from bluesky.protocols import Location
from bluesky.utils import Msg, MsgGenerator

from ._device import Device
from ._device_save_loader import load_from_yaml, save_to_yaml
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


# Add a plan settings_from_device(device: Device) -> MsgGenerator[Settings] to
# walk any device for SignalRWs and locate all SignalRWs from it
def settings_from_device(device: Device) -> MsgGenerator[Settings]:
    """Plan to recursively walk a Device to find SignalRWs and get their values."""
    signals = _walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(signal_values)


# Add a plan settings_to_yaml(device: Device, yaml_path: str) ->
# MsgGenerator[None] that uses the above to store those settings to a YAML file
def settings_to_yaml(device: Device, yaml_path: str | Path) -> MsgGenerator[None]:
    """Plan to recursively walk a Device to find SignalRWs and write a YAML of their
    values.
    """
    signals = _walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    save_to_yaml(named_values, yaml_path)


# Add a function settings_from_yaml(device: Device, yaml_path: str) -> Settings
# that loads a YAML file for values, walks a Device for SignalRWs, and creates a
# Settings object from them
def settings_from_yaml(device: Device, yaml_path: str | Path) -> Settings:
    """Load a YAML file of values, and create a Settings object from them."""
    data = load_from_yaml(yaml_path)
    signals = _walk_rw_signals(device)
    signal_values = {signals[name]: value for name, value in data.items()}
    return Settings(signal_values)


# Add a plan settings_to_change(device: Device, settings: Settings) ->
# MsgGenerator[Settings] that discards settings that are already at the right
# value, erroring if they aren't in the Device
def settings_to_change(device: Device, settings: Settings) -> MsgGenerator[Settings]:
    signals = _walk_rw_signals(device)
    # Check that the signals in settings are actually in the Device
    unknown_signals = set(signals.values()) - set(settings)
    assert not unknown_signals, f"Signal {unknown_signals} are not in {device}"
    # Get the current value of signals
    named_values = yield from _get_values_of_signals(signals)
    need_wait = False
    # Change any signals in settings that don't match current value
    for name, current_value in named_values.items():
        signal = signals[name]
        needed_value = settings.get(signal, None)
        if needed_value != current_value:
            need_wait = True
            yield from bps.abs_set(signal, needed_value, "change_settings")
    # Wait for them to complete
    if need_wait:
        yield from bps.wait("change_settings")


# Add per-device plans apply_settings_to_x(device: Device, settings: Settings)
# -> MsgGenerator[Settings] that calls settings_to_change and sets the signals
# that come back in the right phases, then returns the settings that would be
# required to restore it
#
# Add utility functions x_settings(...) -> Settings that make settings to do
# particular jobs
#
