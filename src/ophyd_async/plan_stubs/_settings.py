from __future__ import annotations

import asyncio
import warnings
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
    StandardReadable,
    StandardReadableFormat,
    Table,
    walk_config_signals,
    walk_devices,
    walk_rw_signals,
)

from ._utils import T
from ._wait_for_awaitable import wait_for_awaitable

#: The key standing in for the root Device itself in a ReadableFormats, where
#: every other key is a dotted attribute path.
_ROOT_DEVICE_KEY = "<ROOT_DEVICE>"


def _paths_to_devices(device: Device) -> dict[str, Device]:
    return {_ROOT_DEVICE_KEY: device, **walk_devices(device)}


def _walk_readable_formats(device: Device) -> ReadableFormats | None:
    """Retrieve how the readable formats in a Device tree differ from construction.

    A child dropped since construction has a format of `None`. A child outside
    its owner has no path to store, so a change to it is warned about and
    skipped. Returns `None` if there is no `StandardReadable` in the tree.
    """
    devices = _paths_to_devices(device)
    readables = {
        path: dev for path, dev in devices.items() if isinstance(dev, StandardReadable)
    }
    if not readables:
        return None
    formats: ReadableFormats = {}
    for path, dev in readables.items():
        # Child paths are stored relative to the owner, not the root, so walk
        # from the owner
        device_to_path = {child: p for p, child in walk_devices(dev).items()}
        entries: dict[str, StandardReadableFormat | None] = {}
        for child, format in dev.get_readable_format_changes():
            child_path = device_to_path.get(child)
            if child_path is None:
                # Not below its owner, so it has no stable path to store it
                # against. See https://github.com/bluesky/ophyd-async/issues/1402
                warnings.warn(
                    f"{dev.name or dev}: {child.name or child} is not within "
                    f"{dev.name or dev}, so the change to its readable format "
                    "will not be stored",
                    stacklevel=2,
                )
            else:
                entries[child_path] = format
        if entries:
            formats[path] = entries
    return formats


def _resolve_readable_formats(
    device: Device, formats: ReadableFormats
) -> list[tuple[StandardReadable, Device, StandardReadableFormat | None]]:
    """Turn every owner and child path in `formats` into the Devices they name.

    :raises NameError:
        If any owner or child path does not name a Device in the tree, or any
        owner is not a `StandardReadable`. All are listed in one error.
    """
    devices = _paths_to_devices(device)
    resolved: list[tuple[StandardReadable, Device, StandardReadableFormat | None]] = []
    unknown_paths: list[str] = []
    not_readable: list[str] = []
    for owner_path, entries in formats.items():
        owner = devices.get(owner_path)
        if owner is None:
            unknown_paths.append(owner_path)
        elif not isinstance(owner, StandardReadable):
            not_readable.append(owner_path)
        else:
            children = walk_devices(owner)
            for child_path, format in entries.items():
                if child_path in children:
                    resolved.append((owner, children[child_path], format))
                else:
                    unknown_paths.append(child_path)
    problems = []
    if unknown_paths:
        problems.append(f"Unknown readable format paths {sorted(unknown_paths)}")
    if not_readable:
        problems.append(
            f"Readable format owners that are not a StandardReadable "
            f"{sorted(not_readable)}"
        )
    if problems:
        raise NameError("; ".join(problems))
    return resolved


def _apply_readable_formats(device: Device, formats: ReadableFormats) -> None:
    """Reset the readable formats in a Device tree, then apply the given changes.

    Every `StandardReadable` in the tree is first put back to what it
    registered during construction, then the changes in `formats` are applied
    on top. So an empty `formats` restores the class defaults.
    """
    # Resolve everything before changing anything, so a bad path cannot leave
    # the tree half applied
    changes = _resolve_readable_formats(device, formats)
    for dev in _paths_to_devices(device).values():
        if isinstance(dev, StandardReadable):
            dev.reset_readable_formats()
    for owner, child, format in changes:
        owner.set_readable_format(child, format)


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

    Values are keyed by dotted attribute path. If the tree contains a
    `StandardReadable`, the changes to readable formats since construction go
    under [](#READABLE_FORMATS_KEY), even if there are none.

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
    formats = _walk_readable_formats(device)
    if formats is not None:
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

    A file with no [](#READABLE_FORMATS_KEY), such as one stored before
    readable formats existed, gives Settings that leave formats alone. Any other
    `<...>` key is warned about and dropped.

    :param provider: The provider to retrieve the settings from.
    :param name: The name of the settings to retrieve.
    :param device: The Device to retrieve the settings for.
    :param only_config: If True, retrieve only configuration settings.
    """
    # Copy, as the provider may hand back a dict it holds on to and the reserved
    # keys are popped out of it below
    data = dict((yield from wait_for_awaitable(provider.retrieve(name))))
    # Reserved keys first, so what is left is signal paths.
    # Present but null, as a hand written "<READABLE_FORMATS>:" would be, still
    # means reset to the class defaults
    stored_formats = (
        data.pop(READABLE_FORMATS_KEY) or {} if READABLE_FORMATS_KEY in data else None
    )
    readable_formats: ReadableFormats | None = (
        None
        if stored_formats is None
        else {
            owner: {
                # A null means "stop this child contributing", so is not coerced
                child: None if format is None else StandardReadableFormat(format)
                for child, format in entries.items()
            }
            for owner, entries in stored_formats.items()
        }
    )
    unknown_reserved = sorted(k for k in data if k.startswith("<") and k.endswith(">"))
    if unknown_reserved:
        warnings.warn(
            f"Ignoring unknown reserved keys {unknown_reserved} in settings {name!r}",
            stacklevel=2,
        )
        for key in unknown_reserved:
            del data[key]
    if only_config:
        signals = yield from wait_for_awaitable(walk_config_signals(device))
    else:
        signals = walk_rw_signals(device)
    unknown_names = set(data) - set(signals)
    if unknown_names:
        raise NameError(f"Unknown signal names {sorted(unknown_names)}")
    if readable_formats:
        # Resolve the paths now, so a stale one fails before any value is written
        _resolve_readable_formats(device, readable_formats)
    signal_values = {signals[name]: value for name, value in data.items()}
    return Settings(device, signal_values, readable_formats)


@plan
def apply_settings(settings: Settings) -> MsgGenerator[None]:
    """Set every SignalRW to the given value in Settings. If value is None ignore it.

    Then apply any readable formats the Settings carries. Every `StandardReadable`
    in the tree is first put back to what it registered during construction, so
    an empty `readable_formats` restores the class defaults, and a child added
    since the formats were stored keeps the format its class gives it. To stop
    a child contributing, give it a format of `None`, which in a stored file is
    a null:

    ```yaml
    <READABLE_FORMATS>:
      <ROOT_DEVICE>:
        energy: HINTED_SIGNAL
        temperature: null
    ```

    Formats go last, so a failed value write leaves them untouched.

    :raises NameError:
        If a readable format path does not name a Device in the tree, or its
        owner is not a `StandardReadable`.
    """
    signal_values = {
        signal: value for signal, value in settings.items() if value is not None
    }
    if signal_values:
        for signal, value in signal_values.items():
            yield from bps.abs_set(signal, value, group="apply_settings")
        yield from bps.wait("apply_settings")
    if settings.readable_formats is not None:
        _apply_readable_formats(settings.device, settings.readable_formats)


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
