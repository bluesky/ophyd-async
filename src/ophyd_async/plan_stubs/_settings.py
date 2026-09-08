from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import bluesky.plan_stubs as bps
import numpy as np
from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import (
    READABLE_FORMATS_KEY,
    Device,
    ReadableFormats,
    Settings,
    SettingsProvider,
    SignalRW,
    StandardReadableFormat,
    Table,
    apply_readable_formats,
    walk_config_signals,
    walk_readable_formats,
    walk_rw_signals,
)

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
def get_current_settings(
    device: Device, only_config: bool = False
) -> MsgGenerator[Settings]:
    """Get current settings on `Device`.

    If `only_config` is True, get current configuration settings on `Configurable`.
    """
    if only_config:
        signals = yield from wait_for_awaitable(walk_config_signals(device))
    else:
        signals = walk_rw_signals(device)
    named_values = yield from _get_values_of_signals(signals)
    signal_values = {signals[name]: value for name, value in named_values.items()}
    return Settings(device, signal_values)


@plan
def store_settings(
    provider: SettingsProvider, name: str, device: Device, only_config: bool = False
) -> MsgGenerator[None]:
    """Walk a Device for SignalRWs and store their values and readable formats.

    If `only_config` is True, store only configuration settings on `Configurable`.
    Readable formats are stored in both cases, since they are what *determines*
    which signals are configuration.

    Values are stored flat, keyed by dotted attribute path. Readable formats go
    under the reserved [](#READABLE_FORMATS_KEY), which is not a valid Python
    identifier and so cannot collide with a path.

    :param provider: The provider to store the settings with.
    :param name: The name to store the settings under.
    :param device: The Device to walk for SignalRWs.
    :param only_config: If True, store only configuration signal values.
    """
    if only_config:
        signals = yield from wait_for_awaitable(walk_config_signals(device))
    else:
        signals = walk_rw_signals(device)
    data: dict[str, Any] = yield from _get_values_of_signals(signals)
    formats = walk_readable_formats(device)
    if formats:
        # Omitted entirely when there is nothing to say, so that a settings only
        # file stays exactly as it was before formats were storable
        data[READABLE_FORMATS_KEY] = {
            owner: {
                child: None if format is None else format.value
                for child, format in entries.items()
            }
            for owner, entries in formats.items()
        }
    yield from wait_for_awaitable(provider.store(name, data))


@plan
def retrieve_settings(
    provider: SettingsProvider, name: str, device: Device, only_config: bool = False
) -> MsgGenerator[Settings]:
    """Retrieve named Settings for a Device from a provider.

    If `only_config` is True, retrieve only configuration settings on `Configurable`.

    A file stored before readable formats existed simply has no
    [](#READABLE_FORMATS_KEY), which reads correctly as "do not change any
    formats" -- so no migration or version marker is needed.

    :param provider: The provider to retrieve the settings from.
    :param name: The name of the settings to retrieve.
    :param device: The Device to retrieve the settings for.
    :param only_config: If True, retrieve only configuration settings.
    """
    # Copy, as the provider may hand back a dict it holds on to and the reserved
    # keys are popped out of it below
    data = dict((yield from wait_for_awaitable(provider.retrieve(name))))
    # Reserved keys first, so what is left is signal paths and the unknown name
    # check below still catches genuine typos. Any <RESERVED> key is dropped,
    # not just the one understood here: a path can never look like that, so a
    # key written by a newer version is ignored rather than reported as a typo.
    stored_formats = data.pop(READABLE_FORMATS_KEY, {})
    for key in [k for k in data if k.startswith("<") and k.endswith(">")]:
        del data[key]
    readable_formats: ReadableFormats = {
        owner: {
            # A null means "stop this child contributing", so it is not coerced
            child: None if format is None else StandardReadableFormat(format)
            for child, format in entries.items()
        }
        for owner, entries in stored_formats.items()
    }
    if only_config:
        signals = yield from wait_for_awaitable(walk_config_signals(device))
    else:
        signals = walk_rw_signals(device)
    unknown_names = set(data) - set(signals)
    if unknown_names:
        raise NameError(f"Unknown signal names {sorted(unknown_names)}")
    signal_values = {signals[name]: value for name, value in data.items()}
    return Settings(device, signal_values, readable_formats)


@plan
def apply_settings(settings: Settings) -> MsgGenerator[None]:
    """Set every SignalRW to the given value in Settings. If value is None ignore it.

    Then apply any readable formats the Settings carries. Formats go last
    because they touch no hardware and cannot fail, so a failed value write
    leaves the Device's readable registry untouched.
    """
    signal_values = {
        signal: value for signal, value in settings.items() if value is not None
    }
    if signal_values:
        for signal, value in signal_values.items():
            yield from bps.abs_set(signal, value, group="apply_settings")
        yield from bps.wait("apply_settings")
    if settings.readable_formats:
        apply_readable_formats(settings.device, settings.readable_formats)


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
    :param current_settings:
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
