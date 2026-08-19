import asyncio
import warnings
from collections.abc import Awaitable, Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from functools import cached_property

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


#: The formats whose devices take part in `stage()`/`unstage()`, if they are
#: `Stageable` at all.
_STAGED_FORMATS = frozenset(
    {StandardReadableFormat.HINTED_SIGNAL, StandardReadableFormat.CHILD}
)


class _SealDefaultFormatsMeta(type(_StandardBase)):  # type: ignore[misc]
    """Record the formats a `StandardReadable` was constructed with.

    `type.__call__` runs `__new__` and then the *whole* `__init__` chain before
    returning, which is the only point that is after every place a format can
    be declared:

    - annotations, applied by `create_children_from_annotations` inside
      `Device.__init__`
    - registration a subclass does *before* calling `super().__init__()`, which
      is what all 24 in-tree Devices do
    - registration a subclass does *after* it, which nothing in tree does but
      which is perfectly legal

    Snapshotting at the end of `StandardReadable.__init__` would silently miss
    the third, and the symptom would be
    [](#StandardReadable.reset_readable_formats) dropping a child the class had
    declared. Devices are already built on a metaclass (`_ProtocolMeta`, from
    the `HasName` Protocol), so this adds no new machinery to the hierarchy.
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
    - Provide their value in `read()` and `describe()
    - Provide their value in `read_configuration()` and `describe_configuration()
    - Select a value to appear in `hints`

    The behavior is customized with a [](#StandardReadableFormat), which can be
    changed at runtime with [](#StandardReadable.set_readable_format).
    """

    @cached_property
    def _readables(self) -> dict[Device, StandardReadableFormat]:
        """The registered children and their formats, in registration order.

        A `cached_property` rather than an attribute set in `__init__`, because
        `add_children_as_readables` and `set_readable_format` are routinely
        called *before* `super().__init__()` (e.g. `AreaDetector`), so anything
        `__init__` assigned would discard them. It also keeps each instance's
        registry its own, where a mutable class attribute would be shared.

        Keying by Device is identity keying, which is what a registry of
        children needs: `Device` does not override `__eq__`, and while
        `DeviceVector` and `DeviceMap` inherit a value based `__eq__` from
        `Mapping`, they hash by `id()`. That is injective over live objects, so
        two distinct devices never share a hash and `__eq__` is never reached.
        """
        return {}

    # The formats declared during construction, sealed by the metaclass once
    # __init__ has fully returned. Only ever replaced, never mutated in place,
    # so the shared class level default is safe.
    _default_readables: dict[Device, StandardReadableFormat] = {}

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
        # HINTED_SIGNAL stages so that caching is set up and read() is fast; a
        # CHILD stages because it may have staging of its own. The uncached and
        # config formats deliberately do not.
        for device, format in self._readables.items():
            if format in _STAGED_FORMATS and isinstance(device, AsyncStageable):
                yield device

    def _extra_funcs_for(self, verb: _Verb) -> Iterator[Callable[[], Awaitable[dict]]]:
        """Contribute to a verb from something other than the registry.

        Subclasses that produce data from somewhere other than a registered
        child override this rather than the verb methods themselves, so that
        registered children keep working without being reimplemented.
        `StandardDetector` uses it for the data its data logics produce.
        """
        return iter(())

    def _funcs_for(self, verb: _Verb) -> Iterator[Callable[[], Awaitable[dict]]]:
        """Derive the callables contributing to one verb from the registry."""
        yield from self._extra_funcs_for(verb)
        for device, format in self._readables.items():
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

    def _extra_hint_sources(self) -> Iterator[HasHints]:
        """Contribute hints from something other than the registry.

        The counterpart of [](#StandardReadable._extra_funcs_for) for `hints`.
        """
        return iter(())

    def _hint_sources(self) -> Iterator[HasHints]:
        yield from self._extra_hint_sources()
        for device, format in self._readables.items():
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
            if not isinstance(format, StandardReadableFormat):
                raise TypeError(f"{format} is not a StandardReadableFormat")
            if format is not StandardReadableFormat.CHILD:
                _as_signal_r(device)
        if format is None:
            self._readables.pop(device, None)
        else:
            # Re-formatting an already registered child keeps its position, so
            # changing a format does not reorder `hints`
            self._readables[device] = format

    def reset_readable_formats(self) -> None:
        """Undo every runtime format change, back to how the class declared them.

        The baseline is everything registered by the time construction
        finished: annotations, `add_children_as_readables`, and any
        [](#StandardReadable.set_readable_format) an `__init__` made. Anything
        done after that -- switching a child between config and hinted,
        dropping one with a format of `None`, registering a new one -- is
        undone.

        Intended for a Device that is retuned per technique, so a scan can put
        it back without knowing what it changed.

        This resets **this Device only**, not its children; it is the
        counterpart of `set_readable_format` rather than of
        [](#apply_readable_formats). To reset a whole tree:

        ```python
        for dev in walk_devices(detector).values():
            if isinstance(dev, StandardReadable):
                dev.reset_readable_formats()
        ```

        The baseline is the *class declaration*, not the last stored settings
        file, so this discards a technique loaded by [](#apply_settings) too.
        """
        # Mutated rather than replaced, so the cached_property stays the same
        # object and nothing holding a reference sees a stale registry
        self._readables.clear()
        self._readables.update(self._default_readables)

    def get_readable_formats(self) -> dict[Device, StandardReadableFormat]:
        """Return the registered children and their formats, in registration order.

        A Device that does not contribute is absent, so
        `get_readable_formats().get(child)` gives its format or `None`.
        """
        return dict(self._readables)

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


def _config_signals(device: Device) -> set[SignalR]:
    """Return every `Signal` contributing to a Device's `read_configuration()`.

    Recurses into children registered as [](#StandardReadableFormat.CHILD), so
    a Device that registers a sub-Device whole picks up whatever that
    sub-Device declares as configuration. A Device that is not a
    `StandardReadable` contributes nothing.

    Unlike `walk_config_signals` this reads the registry rather than calling
    `read_configuration()`, so it does no I/O and includes read-only `SignalR`s
    as well as `SignalRW`s -- `ADBaseIO.model` is a `SignalR`, and it is
    exactly the signal an areaDetector trigger logic needs for deadtime.

    Deliberately private and unexported: #1367 restructures detector logic, so
    what the public shape of this should be is not settled yet.
    """
    signals: set[SignalR] = set()
    if not isinstance(device, StandardReadable):
        return signals
    for child, format in device._readables.items():  # noqa: SLF001
        if format is StandardReadableFormat.CONFIG_SIGNAL:
            signals.add(_as_signal_r(child))
        elif format is StandardReadableFormat.CHILD:
            signals |= _config_signals(child)
    return signals


class _UncachedRead:
    def __init__(self, signal: SignalR) -> None:
        self.signal = signal

    async def __call__(self) -> dict[str, Reading]:
        return await self.signal.read(cached=False)


class _HintedFields(HasHints):
    """Present a fixed list of field names as `hints`."""

    def __init__(self, fields: Sequence[str]) -> None:
        self._fields = list(fields)

    @property
    def name(self) -> str:
        return ""

    @property
    def hints(self) -> Hints:
        return {"fields": self._fields}


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

#: The path standing in for the root Device itself in a [](#ReadableFormats).
#: Not a valid Python identifier, so no attribute assignment can produce a
#: colliding path, and unlike `""` it does not make yaml fall back to its
#: hard-to-read explicit key syntax.
ROOT_PATH = "<ROOT>"

#: The readable formats of a Device tree in a form that can be stored and
#: retrieved: `{path of the StandardReadable: {path of the child: format}}`,
#: where a format of `None` means "stop this child contributing".
#: Paths are dotted attribute paths from the root Device, as produced by
#: [](#walk_devices), with [](#ROOT_PATH) meaning the root Device itself.
#:
#: The outer key is needed because a format is a fact about an (owner, child)
#: *pair*, not about a single Device: the same child can be registered on more
#: than one `StandardReadable` with a different format each time.
ReadableFormats = dict[str, dict[str, StandardReadableFormat | None]]


def _paths_to_devices(device: Device) -> dict[str, Device]:
    return {ROOT_PATH: device, **walk_devices(device)}


def walk_readable_formats(device: Device) -> ReadableFormats:
    """Retrieve the readable format of every registered child in a Device tree.

    Used as part of saving a Device, so that which signals are hinted or
    config can be restored later. Only `StandardReadable`s that actually
    register something get an entry: applying merges rather than replaces, so
    an empty entry would do nothing.

    :param device: The root Device to walk.
    :return: A [](#ReadableFormats) suitable for storing.
    """
    paths_to_devices = _paths_to_devices(device)
    device_to_path = {dev: path for path, dev in paths_to_devices.items()}
    formats: ReadableFormats = {}
    for path, dev in paths_to_devices.items():
        if not isinstance(dev, StandardReadable):
            continue
        entries: dict[str, StandardReadableFormat | None] = {}
        for child, format in dev.get_readable_formats().items():
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
        if entries:
            formats[path] = entries
    return formats


def apply_readable_formats(device: Device, formats: ReadableFormats) -> None:
    """Set the readable format of children in a Device tree.

    This **merges** into what is already registered rather than replacing it: a
    child the formats do not mention keeps whatever format it has. That matches
    how signal values behave, where applying a stored file leaves signals it has
    never heard of alone -- so a file stored against an older version of a
    Device does not silently unregister signals added since.

    To stop a child contributing, give it a format of `None` explicitly, which
    in a stored file is a null:

    ```yaml
    <READABLE_FORMATS>:
      <ROOT>:
        energy: HINTED_SIGNAL
        temperature: null
    ```

    Nothing writes those nulls for you, because storing a Device records only
    what it currently registers and cannot know what some other profile
    registered. A profile that needs a child dropped has to say so.

    :param device: The root Device the paths in `formats` are relative to.
    :param formats: A [](#ReadableFormats), e.g. from [](#walk_readable_formats).
    :raises KeyError: If a path does not name a Device in the tree.
    :raises TypeError: If a path does not name a `StandardReadable`.
    """
    devices = _paths_to_devices(device)
    resolved: list[
        tuple[StandardReadable, list[tuple[Device, StandardReadableFormat | None]]]
    ] = []
    # Resolve everything before changing anything, so a bad path cannot leave
    # the tree half applied
    for owner_path, entries in formats.items():
        owner = devices.get(owner_path)
        if owner is None:
            raise KeyError(f"No Device at {owner_path!r} in {device.name or device}")
        if not isinstance(owner, StandardReadable):
            raise TypeError(f"{owner_path!r} is not a StandardReadable, got {owner}")
        readables: list[tuple[Device, StandardReadableFormat | None]] = []
        for child_path, format in entries.items():
            child = devices.get(child_path)
            if child is None:
                raise KeyError(
                    f"No Device at {child_path!r} in {device.name or device}"
                )
            readables.append(
                (child, None if format is None else StandardReadableFormat(format))
            )
        resolved.append((owner, readables))
    for owner, readables in resolved:
        for child, format in readables:
            owner.set_readable_format(child, format)
