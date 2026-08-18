import asyncio
import warnings
from collections.abc import Awaitable, Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from typing import Any, cast

from bluesky.protocols import HasHints, Hints, Reading
from event_model import DataKey

from ._device import Device, DeviceMap, DeviceVector
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable
from ._signal import SignalR, walk_devices
from ._standard_base import _StandardBase
from ._status import AsyncStatus
from ._utils import merge_gathered_dicts


class _Verb(Enum):
    """The four bluesky verbs a registered child can contribute to."""

    DESCRIBE_CONFIG = "DESCRIBE_CONFIG"
    READ_CONFIG = "READ_CONFIG"
    DESCRIBE = "DESCRIBE"
    READ = "READ"


_CONFIG_VERBS = frozenset({_Verb.DESCRIBE_CONFIG, _Verb.READ_CONFIG})
_READ_VERBS = frozenset({_Verb.DESCRIBE, _Verb.READ})


def _as_signal_r(device: Device) -> SignalR:
    if not isinstance(device, SignalR):
        raise TypeError(f"{device} is not a SignalR")
    return device


def _normalise_format(format: "StandardReadableFormat") -> "StandardReadableFormat":
    """Resolve a deprecated `ConfigSignal`/`HintedSignal` marker to a real member.

    The registry stores real enum members so that the format can be compared,
    serialised and reported later. The deprecated markers only announce
    themselves when compared, so the comparison has to happen here, at
    registration, rather than each time a verb is called.
    """
    if isinstance(format, StandardReadableFormat):
        return format
    for member in StandardReadableFormat:
        if format == member:  # _WarningMatcher.__eq__ raises the DeprecationWarning
            return member
    raise TypeError(f"{format} is not a StandardReadableFormat")


class StandardReadableFormat(Enum):
    """Declare how a `Device` should contribute to the `StandardReadable` verbs."""

    CHILD = "CHILD"
    """Detect which verbs the child supports and contribute to:

    - `read()`, `describe()` if it is [](#bluesky.protocols.Readable)
    - `read_configuration()`, `describe_configuration()` if it is
      [](#bluesky.protocols.Configurable)
    - `stage()`, `unstage()` if it is [](#bluesky.protocols.Stageable)
    - `hints` if it [](#bluesky.protocols.HasHints)
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
        parent.add_readables([child], self)


# Back compat
class _WarningMatcher:
    def __init__(self, name: str, target: StandardReadableFormat):
        self._name = name
        self._target = target

    def __eq__(self, value: object) -> bool:
        warnings.warn(
            DeprecationWarning(
                f"Use `StandardReadableFormat.{self._target.name}` "
                f"instead of `{self._name}`"
            ),
            stacklevel=2,
        )
        return value == self._target


def _compat_format(name: str, target: StandardReadableFormat) -> StandardReadableFormat:
    return cast(StandardReadableFormat, _WarningMatcher(name, target))


ConfigSignal = _compat_format("ConfigSignal", StandardReadableFormat.CONFIG_SIGNAL)
HintedSignal: Any = _compat_format("HintedSignal", StandardReadableFormat.HINTED_SIGNAL)
HintedSignal.uncached = _compat_format(
    "HintedSignal.uncached", StandardReadableFormat.HINTED_UNCACHED_SIGNAL
)


class StandardReadable(_StandardBase, AsyncReadable, AsyncConfigurable, HasHints):
    """Device that provides selected child Device values in `read()`.

    Provides the ability for children to be registered to:
    - Participate in `stage()` and `unstage()`
    - Provide their value in `read()` and `describe()
    - Provide their value in `read_configuration()` and `describe_configuration()
    - Select a value to appear in `hints`

    The behavior is customized with a [](#StandardReadableFormat), which can be
    changed at runtime with [](#StandardReadable.set_readable_format).
    """

    # The registered children, in registration order. Immutable so that it cannot
    # be accidentally shared between instances of the class, and so that a runtime
    # format change swaps the whole tuple rather than mutating shared state.
    _readables: tuple[tuple[Device, StandardReadableFormat], ...] = ()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Staging is derived from _readables on each call rather than registered
        # up-front, so a format changed between runs is picked up on next stage().
        self._stage_funcs += (self._stage_readables,)
        self._unstage_funcs += (self._unstage_readables,)

    @AsyncStatus.wrap
    async def _stage_readables(self) -> None:
        await asyncio.gather(*(sig.stage().task for sig in self._signals_to_stage()))

    @AsyncStatus.wrap
    async def _unstage_readables(self) -> None:
        await asyncio.gather(*(sig.unstage().task for sig in self._signals_to_stage()))

    def _signals_to_stage(self) -> Iterator[AsyncStageable]:
        for device, format in self._readables:
            if format is StandardReadableFormat.HINTED_SIGNAL and isinstance(
                device, AsyncStageable
            ):
                # Caching is set up on stage so that read() is fast
                yield device
            elif format is StandardReadableFormat.CHILD and isinstance(
                device, AsyncStageable
            ):
                yield device

    def _funcs_for(self, verb: _Verb) -> Iterator[Callable[[], Awaitable[dict]]]:
        """Derive the callables contributing to one verb from the registry."""
        for device, format in self._readables:
            match format:
                case StandardReadableFormat.CHILD:
                    if verb in _CONFIG_VERBS and isinstance(device, AsyncConfigurable):
                        yield (
                            device.describe_configuration
                            if verb is _Verb.DESCRIBE_CONFIG
                            else device.read_configuration
                        )
                    elif verb in _READ_VERBS and isinstance(device, AsyncReadable):
                        yield device.describe if verb is _Verb.DESCRIBE else device.read
                case StandardReadableFormat.CONFIG_SIGNAL:
                    signal = _as_signal_r(device)
                    if verb is _Verb.DESCRIBE_CONFIG:
                        yield signal.describe
                    elif verb is _Verb.READ_CONFIG:
                        yield signal.read
                case StandardReadableFormat.HINTED_SIGNAL:
                    signal = _as_signal_r(device)
                    if verb is _Verb.DESCRIBE:
                        yield signal.describe
                    elif verb is _Verb.READ:
                        yield signal.read
                case (
                    StandardReadableFormat.UNCACHED_SIGNAL
                    | StandardReadableFormat.HINTED_UNCACHED_SIGNAL
                ):
                    signal = _as_signal_r(device)
                    if verb is _Verb.DESCRIBE:
                        yield signal.describe
                    elif verb is _Verb.READ:
                        yield _UncachedRead(signal)

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(
            [func() for func in self._funcs_for(_Verb.DESCRIBE_CONFIG)]
        )

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(
            [func() for func in self._funcs_for(_Verb.READ_CONFIG)]
        )

    async def describe(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(
            [func() for func in self._funcs_for(_Verb.DESCRIBE)]
        )

    async def read(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(
            [func() for func in self._funcs_for(_Verb.READ)]
        )

    def _hint_sources(self) -> Iterator[HasHints]:
        for device, format in self._readables:
            match format:
                case StandardReadableFormat.CHILD if isinstance(device, HasHints):
                    yield device
                case (
                    StandardReadableFormat.HINTED_SIGNAL
                    | StandardReadableFormat.HINTED_UNCACHED_SIGNAL
                ):
                    yield _HintsFromName(device)

    @property
    def hints(self) -> Hints:
        hints: Hints = {}
        for new_hint in self._hint_sources():
            # Merge the existing and new hints, based on the type of the value.
            # This avoids default dict merge behavior that overrides the values;
            # we want to combine them when they are Sequences, and ensure they are
            # identical when string values.
            for key, value in new_hint.hints.items():
                # fail early for unkwon types
                if isinstance(value, str):
                    if key in hints:
                        if hints[key] != value:
                            msg = f"Hints key {key} value may not be overridden"
                            raise RuntimeError(msg)
                    else:
                        hints[key] = value  # type: ignore[literal-required]
                elif isinstance(value, Sequence):
                    if key in hints:
                        for new_val in value:
                            if new_val in hints[key]:
                                msg = f"Hint {key} {new_val} overrides existing hint"
                                raise RuntimeError(msg)
                        hints[key] = (  # type: ignore[literal-required]
                            hints[key] + value  # type: ignore[literal-required]
                        )
                    else:
                        hints[key] = value  # type: ignore[literal-required]
                else:
                    msg = (
                        f"{new_hint.name}: Unknown type for value '{value}'"
                        f" for key '{key}'"
                    )
                    raise TypeError(msg)

        return hints

    @contextmanager
    def add_children_as_readables(
        self,
        format: StandardReadableFormat = StandardReadableFormat.CHILD,
    ) -> Generator[None, None, None]:
        """Context manager that calls [](#add_readables) on child Devices added within.

        Scans `self.children()` on entry and exit to context manager, and calls
        `add_readables()` on any that are added with the provided
        `StandardReadableFormat`.
        """
        dict_copy = dict(self.children())

        yield

        # Set symmetric difference operator gives all newly added keys.
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

        new_keys = dict_copy.keys() ^ new_dict.keys()
        new_values = [new_dict[key] for key in new_keys]

        flattened_values = []
        for value in new_values:
            # DeviceVector and DeviceMap case.
            if isinstance(value, (DeviceVector, DeviceMap)):
                flattened_values.extend(value.values())
            else:
                flattened_values.append(value)

        new_devices = list(filter(lambda x: isinstance(x, Device), flattened_values))
        self.add_readables(new_devices, format)

    def set_readable_format(
        self, device: Device, format: StandardReadableFormat | None
    ) -> None:
        """Set how a child Device contributes to this Device's bluesky verbs.

        This is the runtime equivalent of the `Kind` attribute in ophyd v1: it
        can be called after construction to move a child between configuration,
        hinted and uncached reads, or to drop it from the verbs entirely.

        Call it **between runs**. The descriptor for a run is emitted at its
        start, and [](#StandardReadableFormat.HINTED_SIGNAL) sets up caching in
        `stage()`, so changing a format part way through a run would make
        `describe()` and `read()` disagree.

        :param device: The Device to set the format of, normally a child of this one
        :param format:
            The format to give it, or `None` to stop it contributing at all.
            Replaces any format the device already has, rather than adding a
            second contribution.
        :raises TypeError: If a signal-only format is given a non-`SignalR`
        """
        if format is not None:
            format = _normalise_format(format)
            if format is not StandardReadableFormat.CHILD:
                _as_signal_r(device)
        kept = tuple((d, f) for d, f in self._readables if d is not device)
        self._readables = kept if format is None else (*kept, (device, format))

    def get_readable_format(self, device: Device) -> StandardReadableFormat | None:
        """Return the format of a child Device, or `None` if it does not contribute."""
        for registered, format in self._readables:
            if registered is device:
                return format
        return None

    def readable_children(self) -> Iterator[tuple[Device, StandardReadableFormat]]:
        """Iterate over the registered children and their formats, in order."""
        yield from self._readables

    def clear_readables(self) -> None:
        """Drop every registered child, so this Device contributes nothing."""
        self._readables = ()

    def add_readables(
        self,
        devices: Sequence[Device],
        format: StandardReadableFormat = StandardReadableFormat.CHILD,
    ) -> None:
        """Add devices to contribute to various bluesky verbs.

        Use output from the given devices to contribute to the verbs of the following
        interfaces:

        - [](#bluesky.protocols.Readable)
        - [](#bluesky.protocols.Configurable)
        - [](#bluesky.protocols.Stageable)
        - [](#bluesky.protocols.HasHints)

        :param devices: The devices to be added
        :param format:
            Determines which of the devices functions are added to which verb as
            per the [](#StandardReadableFormat) documentation
        """
        for device in devices:
            self.set_readable_format(device, format)


class _UncachedRead:
    def __init__(self, signal: SignalR) -> None:
        self.signal = signal

    async def __call__(self) -> dict[str, Reading]:
        return await self.signal.read(cached=False)


class _HintsFromName(HasHints):
    def __init__(self, device: Device) -> None:
        self.device = device

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def hints(self) -> Hints:
        fields = [self.name] if self.name else []
        return {"fields": fields}


#: Reserved key under which [](#store_settings) writes readable formats. Chosen
#: so that it cannot be a dotted attribute path: `<` cannot start a Python
#: identifier, so no attribute assignment can produce a colliding key, and
#: unlike `*FORMATS*` it needs no quoting in yaml.
READABLE_FORMATS_KEY = "<READABLE_FORMATS>"

#: Reserved key for storing Device names. Reserved now so that adding it later
#: needs no migration; nothing writes it yet.
DEVICE_NAMES_KEY = "<DEVICE_NAMES>"

#: The path standing in for the root Device itself in a [](#ReadableFormats).
#: Not a valid Python identifier, so no attribute assignment can produce a
#: colliding path, and unlike `""` it does not make yaml fall back to its
#: hard-to-read explicit key syntax.
ROOT_DEVICE_KEY = "<ROOT_DEVICE>"

#: The readable formats of a Device tree in a form that can be stored and
#: retrieved: `{path of the StandardReadable: {path of the child: format}}`.
#: Paths are dotted attribute paths from the root Device, as produced by
#: [](#walk_devices), with [](#ROOT_DEVICE_KEY) meaning the root Device itself.
#:
#: The outer key is needed because a format is a fact about an (owner, child)
#: *pair*, not about a single Device: the same child can be registered on more
#: than one `StandardReadable` with a different format each time.
ReadableFormats = dict[str, dict[str, StandardReadableFormat]]


def _paths_to_devices(device: Device) -> dict[str, Device]:
    return {ROOT_DEVICE_KEY: device, **walk_devices(device)}


def walk_readable_formats(device: Device) -> ReadableFormats:
    """Retrieve the readable format of every registered child in a Device tree.

    Used as part of saving a Device, so that which signals are hinted, config
    or omitted can be restored later. Every `StandardReadable` in the tree gets
    an entry, including those with nothing registered, so that applying the
    result is a complete description rather than a partial overlay.

    :param device: The root Device to walk.
    :return: A [](#ReadableFormats) suitable for storing.
    """
    device_to_path = {dev: path for path, dev in _paths_to_devices(device).items()}
    formats: ReadableFormats = {}
    for path, dev in _paths_to_devices(device).items():
        if not isinstance(dev, StandardReadable):
            continue
        entries: dict[str, StandardReadableFormat] = {}
        for child, format in dev.readable_children():
            child_path = device_to_path.get(child)
            if child_path is None:
                # Registered something that is not in this tree, so it has no
                # stable path to store it against. Its value is not stored
                # either, as store_settings only walks the tree, so it will not
                # survive a store/apply round trip at all. See
                # https://github.com/bluesky/ophyd-async/issues/1402
                warnings.warn(
                    f"{dev.name or dev}: {child.name or child} is not within "
                    f"{device.name or device}, so neither its readable format "
                    "nor its value will be stored, and applying stored settings "
                    "will not restore it",
                    stacklevel=2,
                )
            else:
                entries[child_path] = format
        formats[path] = entries
    return formats


def apply_readable_formats(device: Device, formats: ReadableFormats) -> None:
    """Set the readable format of children in a Device tree.

    This **replaces** the registered children of each `StandardReadable` named
    in `formats`, rather than adding to them, so that applying a stored set
    switches a Device between techniques rather than accumulating the union of
    both. `StandardReadable`s not named in `formats` are left alone.

    :param device: The root Device the paths in `formats` are relative to.
    :param formats: A [](#ReadableFormats), e.g. from [](#walk_readable_formats).
    :raises KeyError: If a path does not name a Device in the tree.
    :raises TypeError: If a path does not name a `StandardReadable`.
    """
    devices = _paths_to_devices(device)
    resolved: list[tuple[StandardReadable, list[tuple[Device, StandardReadableFormat]]]]
    resolved = []
    # Resolve everything before changing anything, so a bad path cannot leave
    # the tree half applied
    for owner_path, entries in formats.items():
        owner = devices.get(owner_path)
        if owner is None:
            raise KeyError(f"No Device at {owner_path!r} in {device.name or device}")
        if not isinstance(owner, StandardReadable):
            raise TypeError(f"{owner_path!r} is not a StandardReadable, got {owner}")
        readables = []
        for child_path, format in entries.items():
            child = devices.get(child_path)
            if child is None:
                raise KeyError(
                    f"No Device at {child_path!r} in {device.name or device}"
                )
            readables.append((child, StandardReadableFormat(format)))
        resolved.append((owner, readables))
    for owner, readables in resolved:
        owner.clear_readables()
        for child, format in readables:
            owner.set_readable_format(child, format)
