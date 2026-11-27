import asyncio
import itertools
import warnings
from collections.abc import (
    Awaitable,
    Callable,
    Generator,
    Iterator,
    Sequence,
)
from contextlib import contextmanager
from enum import Enum
from functools import cached_property
from typing import Literal

from bluesky.protocols import HasHints, Hints, Reading
from event_model import DataKey

from ._device import Device, DeviceMap, DeviceVector
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable
from ._signal import SignalR
from ._standard_base import _StandardBase
from ._utils import merge_gathered_dicts


class StandardReadableFormat(Enum):
    """Declare how a `Device` should contribute to the `StandardReadable` verbs."""

    CHILD = "CHILD"
    """Detect which verbs the child supports and contribute to:

    - `read()`, `describe()` if it is [](#bluesky.protocols.Readable)
    - `read_configuration()`, `describe_configuration()` if it is
      [](#bluesky.protocols.Configurable)
    - `stage()`, `unstage()` if it is [](#bluesky.protocols.Stageable)
    - `hints` if it [](#bluesky.protocols.HasHints)

    For a bare `SignalR` this means a cached `read()`, `describe()`, `stage()` and
    `unstage()`, but no `hints`: the non-hinted equivalent of `HINTED_SIGNAL`.
    """

    CONFIG_SIGNAL = "CONFIG_SIGNAL"
    """Contribute the `Signal` value to `read_configuration()` and
    `describe_configuration()`
    """

    HINTED_SIGNAL = "HINTED_SIGNAL"
    """Contribute the monitored `Signal` value to `read()` and `describe()` and
    put the signal name in `hints`
    """

    UNCACHED_SIGNAL = "UNCACHED_SIGNAL"
    """Contribute the uncached `Signal` value to `read()` and `describe()`
    """

    HINTED_UNCACHED_SIGNAL = "HINTED_UNCACHED_SIGNAL"
    """Contribute the uncached `Signal` value to `read()` and `describe()` and
    put the signal name in `hints`
    """

    def __call__(self, parent: Device, child: Device):
        if not isinstance(parent, StandardReadable):
            raise TypeError(f"Expected parent to be StandardReadable, got {parent}")
        parent.set_readable_format(child, self)


# Short alias for the case statements below
Format = StandardReadableFormat

SignalFormat = Literal[
    Format.CONFIG_SIGNAL,
    Format.HINTED_SIGNAL,
    Format.UNCACHED_SIGNAL,
    Format.HINTED_UNCACHED_SIGNAL,
]

#: A registered child and its format. Only a `SignalR` has a signal format.
ReadableEntry = tuple[Device, Literal[Format.CHILD]] | tuple[SignalR, SignalFormat]


class _SealDefaultFormatsMeta(type(_StandardBase)):
    """Record the formats a `StandardReadable` was constructed with.

    The snapshot is taken after the whole `__init__` chain has returned, so it
    holds the formats from annotations and from registration before or after
    `super().__init__()`.
    """

    def __call__(cls, *args, **kwargs):
        self = super().__call__(*args, **kwargs)
        self._default_readables = dict(self._readables)
        return self


class StandardReadable(
    _StandardBase,
    AsyncReadable,
    AsyncConfigurable,
    HasHints,
    metaclass=_SealDefaultFormatsMeta,
):
    """Device that provides selected child Device values in `read()`.

    Provides the ability for children to be registered to:
    - Participate in `stage()` and `unstage()`
    - Provide their value in `read()` and `describe()`
    - Provide their value in `read_configuration()` and `describe_configuration()`
    - Select a value to appear in `hints`

    The behavior is customized with a [](#StandardReadableFormat), which can be
    changed at runtime with [](#StandardReadable.set_readable_format).
    """

    @cached_property
    def _readables(self) -> dict[Device, ReadableEntry]:
        """The registered children and their formats, in registration order.

        A `cached_property`, so `add_children_as_readables` and
        `set_readable_format` can be called before `super().__init__()`.
        """
        return {}

    # The formats declared during construction, sealed by the metaclass once
    # __init__ has fully returned. Only ever replaced, never mutated in place,
    # so the shared class level default is safe.
    _default_readables: dict[Device, ReadableEntry] = {}

    # What contributes to each verb, gathered in parallel by the verb methods.
    # Immutable defaults to avoid accidental sharing between instances. A
    # subclass producing data from somewhere other than a registered child adds
    # to these rather than overriding the verbs. Each registry is named after
    # the method that gathers it, and each hook added to it is `__on_<method>`,
    # name-mangled so mix-ins in one MRO never collide.
    _read_funcs: tuple[Callable[[], Awaitable[dict[str, Reading]]], ...] = ()
    _describe_funcs: tuple[Callable[[], Awaitable[dict[str, DataKey]]], ...] = ()
    _read_configuration_funcs: tuple[
        Callable[[], Awaitable[dict[str, Reading]]], ...
    ] = ()
    _describe_configuration_funcs: tuple[
        Callable[[], Awaitable[dict[str, DataKey]]], ...
    ] = ()
    _hints_funcs: tuple[Callable[[], Iterator[Hints]], ...] = ()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Each of these derives from _readables on every call rather than being
        # registered up-front, so a format changed between runs is picked up on
        # the next stage() or the next descriptor.
        self._stage_funcs += (self.__on_stage,)
        self._unstage_funcs += (self.__on_unstage,)
        self._read_funcs += (self.__on_read,)
        self._describe_funcs += (self.__on_describe,)
        self._read_configuration_funcs += (self.__on_read_configuration,)
        self._describe_configuration_funcs += (self.__on_describe_configuration,)
        self._hints_funcs += (self.__on_hints,)

    def _signals_to_stage(self) -> Iterator[AsyncStageable]:
        # HINTED_SIGNAL stages so that caching is set up and read() is fast; a
        # CHILD stages because it may have staging of its own. The uncached and
        # config formats deliberately do not.
        for entry in self._readables.values():
            match entry:
                case (device, Format.CHILD):
                    if isinstance(device, AsyncStageable):
                        yield device
                case (signal, Format.HINTED_SIGNAL):
                    yield signal
                case (
                    _,
                    Format.CONFIG_SIGNAL
                    | Format.UNCACHED_SIGNAL
                    | Format.HINTED_UNCACHED_SIGNAL,
                ):
                    pass

    async def __on_stage(self) -> None:
        await asyncio.gather(*(sig.stage().task for sig in self._signals_to_stage()))

    async def __on_unstage(self) -> None:
        await asyncio.gather(*(sig.unstage().task for sig in self._signals_to_stage()))

    async def __on_describe_configuration(self) -> dict[str, DataKey]:
        """What the registered children contribute to `describe_configuration()`."""
        coros = []
        for entry in self._readables.values():
            match entry:
                case (device, Format.CHILD):
                    if isinstance(device, AsyncConfigurable):
                        coros.append(device.describe_configuration())
                case (signal, Format.CONFIG_SIGNAL):
                    coros.append(signal.describe())
                case (
                    _,
                    Format.HINTED_SIGNAL
                    | Format.UNCACHED_SIGNAL
                    | Format.HINTED_UNCACHED_SIGNAL,
                ):
                    pass
        return await merge_gathered_dicts(coros)

    async def __on_read_configuration(self) -> dict[str, Reading]:
        """What the registered children contribute to `read_configuration()`."""
        coros = []
        for entry in self._readables.values():
            match entry:
                case (device, Format.CHILD):
                    if isinstance(device, AsyncConfigurable):
                        coros.append(device.read_configuration())
                case (signal, Format.CONFIG_SIGNAL):
                    coros.append(signal.read())
                case (
                    _,
                    Format.HINTED_SIGNAL
                    | Format.UNCACHED_SIGNAL
                    | Format.HINTED_UNCACHED_SIGNAL,
                ):
                    pass
        return await merge_gathered_dicts(coros)

    async def __on_describe(self) -> dict[str, DataKey]:
        """What the registered children contribute to `describe()`."""
        coros = []
        for entry in self._readables.values():
            match entry:
                case (device, Format.CHILD):
                    if isinstance(device, AsyncReadable):
                        coros.append(device.describe())
                case (
                    signal,
                    Format.HINTED_SIGNAL
                    | Format.UNCACHED_SIGNAL
                    | Format.HINTED_UNCACHED_SIGNAL,
                ):
                    coros.append(signal.describe())
                case (_, Format.CONFIG_SIGNAL):
                    pass
        return await merge_gathered_dicts(coros)

    async def __on_read(self) -> dict[str, Reading]:
        """What the registered children contribute to `read()`."""
        coros = []
        for entry in self._readables.values():
            match entry:
                case (device, Format.CHILD):
                    if isinstance(device, AsyncReadable):
                        coros.append(device.read())
                case (signal, Format.HINTED_SIGNAL):
                    coros.append(signal.read())
                case (
                    signal,
                    Format.UNCACHED_SIGNAL | Format.HINTED_UNCACHED_SIGNAL,
                ):
                    coros.append(signal.read(cached=False))
                case (_, Format.CONFIG_SIGNAL):
                    pass
        return await merge_gathered_dicts(coros)

    def __on_hints(self) -> Iterator[Hints]:
        """What the registered children contribute to `hints`."""
        for entry in self._readables.values():
            match entry:
                case (device, Format.CHILD):
                    if isinstance(device, HasHints):
                        yield device.hints
                case (
                    signal,
                    Format.HINTED_SIGNAL | Format.HINTED_UNCACHED_SIGNAL,
                ):
                    # An unnamed signal has nothing to put in `fields`, but is
                    # still hinted, so it contributes the key and no name
                    yield {"fields": [signal.name] if signal.name else []}
                case (
                    _,
                    Format.CONFIG_SIGNAL | Format.UNCACHED_SIGNAL,
                ):
                    pass

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(
            [func() for func in self._describe_configuration_funcs]
        )

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(
            [func() for func in self._read_configuration_funcs]
        )

    async def describe(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts([func() for func in self._describe_funcs])

    async def read(self) -> dict[str, Reading]:
        return await merge_gathered_dicts([func() for func in self._read_funcs])

    @property
    def hints(self) -> Hints:
        # fields and dimensions keys from sub devices are flattened
        # into the hints.
        flattened_fields = []
        flattened_dimensions = []

        hints: Hints = {}
        for new_hint in itertools.chain.from_iterable(
            func() for func in self._hints_funcs
        ):
            # If a hints key in a subdevice isn't given in bluesky protocols, then it
            # doesn't carry over to the device holding it.
            for key, value in new_hint.items():
                if key in ("fields", "dimensions"):
                    if isinstance(value, str) or not isinstance(value, Sequence):
                        raise RuntimeError(
                            f"{self.name}: '{key}' key must be a Sequence, "
                            f"received {type(value)}"
                        )
                    already_parsed = (
                        flattened_fields if key == "fields" else flattened_dimensions
                    )
                    if common := [v for v in value if v in already_parsed]:
                        raise RuntimeError(
                            f"Hint '{key}' {list(common)} override existing hint."
                        )

                    already_parsed += list(value)
                elif key == "gridding":
                    if (already_set := hints.get(key, None)) and already_set != value:
                        raise RuntimeError("Hint key 'gridding' may not be overridden.")
                    hints["gridding"] = value  # type: ignore

        if flattened_fields:
            hints["fields"] = flattened_fields
        if flattened_dimensions:
            hints["dimensions"] = flattened_dimensions

        return hints

    @contextmanager
    def add_children_as_readables(
        self,
        format: StandardReadableFormat = StandardReadableFormat.CHILD,
    ) -> Generator[None, None, None]:
        """Register child Devices added within with the given format.

        Scans `self.children()` on entry and exit to context manager, and calls
        [](#StandardReadable.set_readable_format) on any that are added with the
        provided `StandardReadableFormat`.
        """
        dict_copy = dict(self.children())

        yield

        new_dict = dict(self.children())
        for key, value in new_dict.items():
            # Check if key already exists in dict_copy and if the value has changed.
            if key in dict_copy and value != dict_copy[key]:
                error_msg = (
                    f"Duplicate readable device found: '{key}' in {value.parent}. "
                    "Derived class must not redefine a readable. "
                    "See: https://github.com/bluesky/ophyd-async/issues/848. "
                    "If this functionality is required, please raise an issue: "
                    "https://github.com/bluesky/ophyd-async"
                )
                raise KeyError(error_msg)

        # Newly added children, in the order they were declared
        new_values = [value for key, value in new_dict.items() if key not in dict_copy]

        flattened_values = []
        for value in new_values:
            # DeviceVector and DeviceMap case.
            if isinstance(value, (DeviceVector, DeviceMap)):
                flattened_values.extend(value.values())
            else:
                flattened_values.append(value)

        for device in flattened_values:
            if isinstance(device, Device):
                self.set_readable_format(device, format)

    def set_readable_format(
        self, device: Device, format: StandardReadableFormat | None
    ) -> None:
        """Set how a child Device contributes to this Device's bluesky verbs.

        Call it between runs, as a run's descriptor is emitted at its start.

        :param device: The Device to set the format of, normally a child of this one
        :param format:
            The format to give it, replacing any it already has, or `None` to
            stop it contributing.
        :raises TypeError: If a signal-only format is given a non-`SignalR`
        """
        # Re-formatting an already registered child keeps its position, so
        # changing a format does not reorder `hints`
        match format:
            case None:
                self._readables.pop(device, None)
            case Format.CHILD:
                self._readables[device] = (device, format)
            case (
                Format.CONFIG_SIGNAL
                | Format.HINTED_SIGNAL
                | Format.UNCACHED_SIGNAL
                | Format.HINTED_UNCACHED_SIGNAL
            ):
                if not isinstance(device, SignalR):
                    raise TypeError(f"{device} is not a SignalR")
                self._readables[device] = (device, format)

    def reset_readable_formats(self) -> None:
        """Put the formats back to those registered by the end of construction.

        Undoes every later [](#StandardReadable.set_readable_format), including
        formats loaded by [](#apply_readable_formats). Resets this Device only; use
        [](#apply_readable_formats) with `{}` for a whole tree.
        """
        # Mutated rather than replaced, so the cached_property stays the same
        # object and nothing holding a reference sees a stale registry
        self._readables.clear()
        self._readables.update(self._default_readables)

    def get_readable_formats(self) -> Iterator[ReadableEntry]:
        """Yield each registered child and its format, in registration order.

        A Device that does not contribute is not yielded. It is safe to call
        [](#StandardReadable.set_readable_format) while iterating.
        """
        # Iterate over a copy, as the dict would raise if changed while iterating
        return iter(list(self._readables.values()))

    def get_readable_format_changes(
        self,
    ) -> Iterator[tuple[Device, StandardReadableFormat | None]]:
        """Yield the formats that differ from those declared at construction.

        A child registered at construction but since dropped has a format of `None`.
        It is safe to call [](#StandardReadable.set_readable_format) while iterating.
        """
        changes: list[tuple[Device, StandardReadableFormat | None]] = [
            (child, entry[1])
            for child, entry in self._readables.items()
            if self._default_readables.get(child) != entry
        ]
        changes.extend(
            (child, None)
            for child in self._default_readables
            if child not in self._readables
        )
        return iter(changes)

    # Back compat - delete before 1.0
    def add_readables(
        self,
        devices: Sequence[Device],
        format: StandardReadableFormat = StandardReadableFormat.CHILD,
    ) -> None:
        """Deprecated: use [](#StandardReadable.set_readable_format) instead.

        :param devices: The devices to be added
        :param format:
            Determines which of the devices functions are added to which verb as
            per the [](#StandardReadableFormat) documentation
        """
        warnings.warn(
            DeprecationWarning(
                "Use `set_readable_format(device, format)` on each device "
                "instead of `add_readables(devices, format)`"
            ),
            stacklevel=2,
        )
        for device in devices:
            self.set_readable_format(device, format)


#: The changes to the readable formats of a Device tree since construction:
#: `{StandardReadable: {child Device: format}}`, where a format of `None` means
#: "stop this child contributing".
ReadableFormats = dict[StandardReadable, dict[Device, StandardReadableFormat | None]]
