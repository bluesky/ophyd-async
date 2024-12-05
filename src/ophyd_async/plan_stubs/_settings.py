from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import bluesky.plan_stubs as bps
from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import (
    Device,
    Settings,
    SettingsProvider,
    SignalRW,
    T,
    walk_rw_signals,
)

from ._wait_for_one import wait_for_one


@plan
def _get_values_of_signals(
    signals: Mapping[T, SignalRW],
) -> MsgGenerator[dict[T, Any]]:
    coros = [sig.get_value() for sig in signals.values()]
    values = yield from wait_for_one(asyncio.gather(*coros))
    named_values = dict(zip(signals, values, strict=True))
    return named_values


@plan
def get_current_settings(device: Device) -> MsgGenerator[Settings]:
    signals = walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(device, signal_values)


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
    return Settings(device, signal_values)


@plan
def apply_settings(settings: Settings) -> MsgGenerator[None]:
    signal_values = {
        signal: value for signal, value in settings.items() if value is not None
    }
    if signal_values:
        for signal, value in signal_values.items():
            yield from bps.abs_set(signal, value, "apply_settings")
        yield from bps.wait("apply_settings")


@plan
def apply_settings_if_different(
    settings: Settings,
    apply_plan: Callable[[Settings], MsgGenerator[None]],
    current_settings: Settings | None = None,
) -> MsgGenerator[None]:
    if current_settings is None:
        signal_values = yield from _get_values_of_signals(
            {sig: sig for sig in settings}
        )
        current_settings = Settings(settings.device, signal_values)
    settings_to_change, _ = settings.partition(
        lambda sig: settings[sig] != current_settings[sig]
    )
    yield from apply_plan(settings_to_change)


# def my_custom_plan(panda: Device, settings: Settings) -> MsgGenerator[None]:
#     # Get the initial state of the device
#     initial_settings = yield from get_current_settings(panda)
#     yield from apply_settings_if_different(
#         settings, apply_settings_to_panda, initial_settings
#     )
#     yield from fly(panda)
#     # Setup for a different plan
#     yield from apply_settings_if_different(settings, apply_settings_to_panda)
#     yield from fly(panda)
#     # Restore to how it was
#     yield from apply_settings_if_different(initial_settings, apply_settings_to_panda)
