from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import bluesky.plan_stubs as bps
from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import (
    Device,
    Settings,
    SettingsProvider,
    SignalRW,
    walk_rw_signals,
)

from ._wait_for_one import wait_for_one


@plan
def _get_values_of_signals(
    signals: dict[str, SignalRW],
) -> MsgGenerator[dict[str, Any]]:
    coros = [sig.get_value() for sig in signals.values()]
    values = yield from wait_for_one(asyncio.gather(*coros))
    named_values = dict(zip(signals, values, strict=True))
    return named_values


@plan
def store_settings(
    provider: SettingsProvider, name: str, device: Device
) -> MsgGenerator[None]:
    """Plan to recursively walk a Device to find SignalRWs and write a YAML of their
    values.
    """
    signals = walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    yield from wait_for_one(provider.store(name, named_values))


@plan
def retrieve_settings(
    provider: SettingsProvider, name: str, device: Device
) -> MsgGenerator[Settings]:
    named_values = yield from wait_for_one(provider.retrieve(name))
    signals = walk_rw_signals(device)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(signal_values)


@plan
def apply_settings(settings: Settings) -> MsgGenerator[None]:
    if settings:
        for signal, value in settings.items():
            yield from bps.abs_set(signal, value, "apply_settings")
        yield from bps.wait("apply_settings")


Reverter = Callable[[], MsgGenerator[None]]


def _settings_to_change(
    device: Device, settings: Settings
) -> MsgGenerator[tuple[Settings, Settings]]:
    # Get the current settings of the Device
    signals = walk_rw_signals(device)
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
