import warnings
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from enum import Enum
from typing import Any, cast

from bluesky.protocols import HasHints, Hints, Reading
from event_model import DataKey

from ._device import Device, DeviceVector
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable
from ._signal import SignalR
from ._status import AsyncStatus
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


class StandardReadable(
    Device, AsyncReadable, AsyncConfigurable, AsyncStageable, HasHints
):
    """Device that provides selected child Device values in `read()`.

    Provides the ability for children to be registered to:
    - Participate in `stage()` and `unstage()`
    - Provide their value in `read()` and `describe()
    - Provide their value in `read_configuration()` and `describe_configuration()
    - Select a value to appear in `hints`

    The behavior is customized with a [](#StandardReadableFormat)
    """

    # These must be immutable types to avoid accidental sharing between
    # different instances of the class
    _describe_config_funcs: tuple[Callable[[], Awaitable[dict[str, DataKey]]], ...] = ()
    _read_config_funcs: tuple[Callable[[], Awaitable[dict[str, Reading]]], ...] = ()
    _describe_funcs: tuple[Callable[[], Awaitable[dict[str, DataKey]]], ...] = ()
    _read_funcs: tuple[Callable[[], Awaitable[dict[str, Reading]]], ...] = ()
    _stageables: tuple[AsyncStageable, ...] = ()
    _has_hints: tuple[HasHints, ...] = ()

    @AsyncStatus.wrap
    async def stage(self) -> None:
        for sig in self._stageables:
            await sig.stage().task

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        for sig in self._stageables:
            await sig.unstage().task

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(
            [func() for func in self._describe_config_funcs]
        )

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts([func() for func in self._read_config_funcs])

    async def describe(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts([func() for func in self._describe_funcs])

    async def read(self) -> dict[str, Reading]:
        return await merge_gathered_dicts([func() for func in self._read_funcs])

    @property
    def hints(self) -> Hints:
        hints: Hints = {}
        for new_hint in self._has_hints:
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
            if isinstance(value, DeviceVector):
                flattened_values.extend(value.values())
            else:
                flattened_values.append(value)

        new_devices = list(filter(lambda x: isinstance(x, Device), flattened_values))
        self.add_readables(new_devices, format)

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

        def assert_device_is_signalr(device: Device) -> SignalR:
            if not isinstance(device, SignalR):
                raise TypeError(f"{device} is not a SignalR")
            return device

        for device in devices:
            match format:
                case StandardReadableFormat.CHILD:
                    if isinstance(device, AsyncConfigurable):
                        self._describe_config_funcs += (device.describe_configuration,)
                        self._read_config_funcs += (device.read_configuration,)
                    if isinstance(device, AsyncReadable):
                        self._describe_funcs += (device.describe,)
                        self._read_funcs += (device.read,)
                    if isinstance(device, AsyncStageable):
                        self._stageables += (device,)
                    if isinstance(device, HasHints):
                        self._has_hints += (device,)
                case StandardReadableFormat.CONFIG_SIGNAL:
                    signalr_device = assert_device_is_signalr(device=device)
                    self._describe_config_funcs += (signalr_device.describe,)
                    self._read_config_funcs += (signalr_device.read,)
                case StandardReadableFormat.HINTED_SIGNAL:
                    signalr_device = assert_device_is_signalr(device=device)
                    self._describe_funcs += (signalr_device.describe,)
                    self._read_funcs += (signalr_device.read,)
                    self._stageables += (signalr_device,)
                    self._has_hints += (_HintsFromName(signalr_device),)
                case StandardReadableFormat.UNCACHED_SIGNAL:
                    signalr_device = assert_device_is_signalr(device=device)
                    self._describe_funcs += (signalr_device.describe,)
                    self._read_funcs += (_UncachedRead(signalr_device),)
                case StandardReadableFormat.HINTED_UNCACHED_SIGNAL:
                    signalr_device = assert_device_is_signalr(device=device)
                    self._describe_funcs += (signalr_device.describe,)
                    self._read_funcs += (_UncachedRead(signalr_device),)
                    self._has_hints += (_HintsFromName(signalr_device),)


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
