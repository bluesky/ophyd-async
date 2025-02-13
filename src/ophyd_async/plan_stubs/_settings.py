from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import bluesky.plan_stubs as bps
import numpy as np
from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import (
    Device,
    Settings,
    SettingsProvider,
    SignalRW,
    walk_rw_signals,
)
from ophyd_async.core._table import Table

from ._utils import T
from ._wait_for_awaitable import wait_for_awaitable


@plan
def _get_values_of_signals(
    signals: Mapping[T, SignalRW],
) -> MsgGenerator[dict[T, Any]]:
    coros = [sig.get_value() for sig in signals.values()]
    values = yield from wait_for_awaitable(asyncio.gather(*coros))
    named_values = dict(zip(signals, values, strict=True))
    return named_values


@plan
def get_current_settings(device: Device) -> MsgGenerator[Settings]:
    """Get current settings on `Device`."""
    signals = walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(device, signal_values)


@plan
def store_settings(
    provider: SettingsProvider, name: str, device: Device
) -> MsgGenerator[None]:
    """Walk a Device for SignalRWs and store their values.

    :param provider: The provider to store the settings with.
    :param name: The name to store the settings under.
    :param device: The Device to walk for SignalRWs.
    """
    signals = walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    yield from wait_for_awaitable(provider.store(name, named_values))


@plan
def retrieve_settings(
    provider: SettingsProvider, name: str, device: Device
) -> MsgGenerator[Settings]:
    """Retrieve named Settings for a Device from a provider."""
    named_values = yield from wait_for_awaitable(provider.retrieve(name))
    signals = walk_rw_signals(device)
    unknown_names = set(named_values) - set(signals)
    if unknown_names:
        raise NameError(f"Unknown signal names {sorted(unknown_names)}")
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(device, signal_values)


@plan
def apply_settings(settings: Settings) -> MsgGenerator[None]:
    """Set every SignalRW to the given value in Settings. If value is None ignore it."""
    signal_values = {
        signal: value for signal, value in settings.items() if value is not None
    }
    if signal_values:
        for signal, value in signal_values.items():
            yield from bps.abs_set(signal, value, group="apply_settings")
        yield from bps.wait("apply_settings")


@plan
def apply_settings_if_different(
    settings: Settings,
    apply_plan: Callable[[Settings], MsgGenerator[None]],
    current_settings: Settings | None = None,
) -> MsgGenerator[None]:
    """Set every SignalRW in settings, only if it is different to the current value.

    :param apply_plan:
        A device specific plan which takes the Settings to apply and applies them to
        the Device. Used to add device specific ordering to setting the signals.
    :current_settings:
        If given, should be a superset of settings containing the current value of
        the Settings in the Device. If not given it will be created by reading just
        the signals given in settings.
    """
    if current_settings is None:
        # If we aren't give the current settings, then get the
        # values of just the signals we were asked to change.
        # This allows us to use this plan with Settings for a subset
        # of signals in the Device without retrieving them all
        signal_values = yield from _get_values_of_signals(
            {sig: sig for sig in settings}
        )
        current_settings = Settings(settings.device, signal_values)

    def _is_different(current, required) -> bool:
        if isinstance(current, Table):
            current = current.model_dump()
            if isinstance(required, Table):
                required = required.model_dump()
            return current.keys() != required.keys() or any(
                _is_different(current[k], required[k]) for k in current
            )
        elif isinstance(current, np.ndarray):
            return not np.array_equal(current, required)
        else:
            return current != required

    settings_to_change, _ = settings.partition(
        lambda sig: _is_different(current_settings[sig], settings[sig])
    )
    yield from apply_plan(settings_to_change)
