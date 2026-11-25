from __future__ import annotations

import asyncio
import warnings
from collections.abc import Callable, Mapping
from typing import Any

import bluesky.plan_stubs as bps
import numpy as np
from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import (
    Device,
    DeviceSnapshot,
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

#: The reserved key under which readable formats are stored. It cannot collide
#: with a dotted attribute path.
_READABLE_FORMATS_KEY = "<READABLE_FORMATS>"

#: Separates the path of the owning `StandardReadable` from the path of the
#: child in a stored readable format key.
_OWNER_SEPARATOR = ":"


def _is_section(key: str) -> bool:
    return key.startswith("<") and key.endswith(">")


def _format_key(owner_path: str, child_path: str) -> str:
    return f"{owner_path}{_OWNER_SEPARATOR}{child_path}" if owner_path else child_path


def _parse_format_key(key: str) -> tuple[str, str]:
    owner_path, _, child_path = key.rpartition(_OWNER_SEPARATOR)
    return owner_path, child_path


def _stored_readable_formats(device: Device) -> dict[str, str | None] | None:
    """Describe how the readable formats in a Device tree differ from construction.

    `None` if there is no `StandardReadable` in the tree. A change to a child that
    is not within its owner is warned about and skipped.
    """
    paths: dict[Device, str] = {device: ""}
    paths.update({dev: path for path, dev in walk_devices(device).items()})
    readables = [dev for dev in paths if isinstance(dev, StandardReadable)]
    stored: dict[str, str | None] | None = None
    if readables:
        stored = {}
        for owner in readables:
            child_paths = {child: path for path, child in walk_devices(owner).items()}
            for child, format in owner.get_readable_format_changes():
                child_path = child_paths.get(child)
                if child_path is None:
                    # Not below its owner, so it has no stable path to store it
                    # against. See https://github.com/bluesky/ophyd-async/issues/1402
                    warnings.warn(
                        f"{owner.name or owner}: {child.name or child} is not within "
                        f"{owner.name or owner}, so the change to its readable "
                        "format will not be stored",
                        stacklevel=2,
                    )
                else:
                    key = _format_key(paths[owner], child_path)
                    stored[key] = None if format is None else format.value
    return stored


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
def store_snapshot(
    provider: SettingsProvider, name: str, device: Device, only_config: bool = False
) -> MsgGenerator[None]:
    """Walk a Device for SignalRWs and store their values and readable formats.

    If the tree contains a `StandardReadable`, its readable format changes since
    construction go under `<READABLE_FORMATS>`, even if there are none.

    :param provider: The provider to store the snapshot with.
    :param name: The name to store the snapshot under.
    :param device: The Device to walk for SignalRWs.
    :param only_config:
        If True, store only the values of configuration signals. Readable formats
        are always stored.
    """
    if only_config:
        signals = yield from wait_for_awaitable(walk_config_signals(device))
    else:
        signals = walk_rw_signals(device)
    data: dict[str, Any] = yield from _get_values_of_signals(signals)
    formats = _stored_readable_formats(device)
    if formats is not None:
        data[_READABLE_FORMATS_KEY] = formats
    yield from wait_for_awaitable(provider.store(name, data))


@plan
def retrieve_snapshot(
    provider: SettingsProvider, name: str, device: Device
) -> MsgGenerator[DeviceSnapshot]:
    """Retrieve the named snapshot from a provider, bound to a Device.

    :param provider: The provider to retrieve the snapshot from.
    :param name: The name of the snapshot to retrieve.
    :param device: The Device the snapshot is for.
    :raises ValueError: If a stored readable format is not a `StandardReadableFormat`.
    :raises NameError: If a stored path does not name anything in the Device.
    """
    data = yield from wait_for_awaitable(provider.retrieve(name))
    values = {k: v for k, v in data.items() if not _is_section(k)}
    formats = None
    if _READABLE_FORMATS_KEY in data:
        # A hand written "<READABLE_FORMATS>:" is null, which still means reset
        stored = data[_READABLE_FORMATS_KEY] or {}
        # A null means "stop this child contributing", so is not coerced
        formats = {
            _parse_format_key(key): None
            if value is None
            else StandardReadableFormat(value)
            for key, value in stored.items()
        }
    return DeviceSnapshot(device, values, formats)


@plan
def apply_readable_formats(
    device: Device, formats: ReadableFormats | None
) -> MsgGenerator[None]:
    """Reset the readable formats in a Device tree, then apply the given changes.

    Every `StandardReadable` in the tree is first put back to what it registered
    during construction, so an empty `formats` restores the class defaults.

    :param device: The root of the tree to reset.
    :param formats:
        The changes to apply, as `{StandardReadable: {child: format}}`. `None`
        leaves the formats alone.
    """
    if formats is not None:
        for dev in (device, *walk_devices(device).values()):
            if isinstance(dev, StandardReadable):
                dev.reset_readable_formats()
        for owner, changes in formats.items():
            for child, format in changes.items():
                owner.set_readable_format(child, format)
    yield from bps.null()


@plan
def store_settings(
    provider: SettingsProvider, name: str, device: Device, only_config: bool = False
) -> MsgGenerator[None]:
    """Walk a Device for SignalRWs and store their values.

    Deprecated: use [](#store_snapshot). This delegates to it, so it also stores
    readable formats.

    :param provider: The provider to store the settings with.
    :param name: The name to store the settings under.
    :param device: The Device to walk for SignalRWs.
    :param only_config: If True, store only the values of configuration signals.
    """
    warnings.warn(
        DeprecationWarning("store_settings is deprecated, use store_snapshot instead"),
        stacklevel=3,
    )
    yield from store_snapshot(provider, name, device, only_config)


@plan
def retrieve_settings(
    provider: SettingsProvider, name: str, device: Device, only_config: bool = False
) -> MsgGenerator[Settings]:
    """Retrieve named Settings for a Device from a provider.

    Deprecated: use `(yield from retrieve_snapshot(...)).settings`
    ([](#retrieve_snapshot)). Sections such as `<READABLE_FORMATS>` are skipped.

    :param provider: The provider to retrieve the settings from.
    :param name: The name of the settings to retrieve.
    :param device: The Device to retrieve the settings for.
    :param only_config: Has no effect, and is kept for compatibility.
    """
    warnings.warn(
        DeprecationWarning(
            "retrieve_settings is deprecated, use "
            "(yield from retrieve_snapshot(...)).settings instead"
        ),
        stacklevel=3,
    )
    return (yield from retrieve_snapshot(provider, name, device)).settings


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
