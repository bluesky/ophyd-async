from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from enum import Enum

from bluesky.protocols import HasHints, Hints, Reading
from event_model import DataKey

from ._device import Device, DeviceVector
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable
from ._signal import SignalR
from ._status import AsyncStatus
from ._utils import merge_gathered_dicts


class StandardReadableFormat(Enum):
    CHILD = "CHILD"
    CONFIG_SIGNAL = "CONFIG_SIGNAL"
    HINTED_SIGNAL = "HINTED_SIGNAL"
    UNCACHED_SIGNAL = "UNCACHED_SIGNAL"
    HINTED_UNCACHED_SIGNAL = "HINTED_UNCACHED_SIGNAL"

    def __call__(self, parent: Device, child: Device):
        if not isinstance(parent, StandardReadable):
            raise TypeError(f"Expected parent to be StandardReadable, got {parent}")
        parent.add_readables([child], self)


# Back compat
ConfigSignal = StandardReadableFormat.CONFIG_SIGNAL
HintedSignal = StandardReadableFormat.HINTED_SIGNAL
HintedSignal.uncached = StandardReadableFormat.HINTED_UNCACHED_SIGNAL  # type: ignore


class StandardReadable(
    Device, AsyncReadable, AsyncConfigurable, AsyncStageable, HasHints
):
    """Device that owns its children and provides useful default behavior.

    - When its name is set it renames child Devices
    - Signals can be registered for read() and read_configuration()
    - These signals will be subscribed for read() between stage() and unstage()
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
            # This avoids default dict merge behaviour that overrides the values;
            # we want to combine them when they are Sequences, and ensure they are
            # identical when string values.
            for key, value in new_hint.hints.items():
                if isinstance(value, str):
                    if key in hints:
                        assert (
                            hints[key] == value  # type: ignore[literal-required]
                        ), f"Hints key {key} value may not be overridden"
                    else:
                        hints[key] = value  # type: ignore[literal-required]
                elif isinstance(value, Sequence):
                    if key in hints:
                        for new_val in value:
                            assert (
                                new_val not in hints[key]  # type: ignore[literal-required]
                            ), f"Hint {key} {new_val} overrides existing hint"
                        hints[key] = (  # type: ignore[literal-required]
                            hints[key] + value  # type: ignore[literal-required]
                        )
                    else:
                        hints[key] = value  # type: ignore[literal-required]
                else:
                    raise TypeError(
                        f"{new_hint.name}: Unknown type for value '{value}' "
                        f" for key '{key}'"
                    )

        return hints

    @contextmanager
    def add_children_as_readables(
        self,
        wrapper: StandardReadableFormat = StandardReadableFormat.CHILD,
    ) -> Generator[None, None, None]:
        """Context manager to wrap adding Devices

        Add Devices to this class instance inside the Context Manager to automatically
        add them to the correct fields, based on the Device's interfaces.

        The provided wrapper class will be applied to all Devices and can be used to
        specify their behaviour.

        Parameters
        ----------
        wrapper:
            Wrapper class to apply to all Devices created inside the context manager.

        See Also
        --------
        :func:`~StandardReadable.add_readables`
        :class:`ConfigSignal`
        :class:`HintedSignal`
        :meth:`HintedSignal.uncached`
        """

        dict_copy = dict(self.children())

        yield

        # Set symmetric difference operator gives all newly added keys
        new_dict = dict(self.children())
        new_keys = dict_copy.keys() ^ new_dict.keys()
        new_values = [new_dict[key] for key in new_keys]

        flattened_values = []
        for value in new_values:
            if isinstance(value, DeviceVector):
                flattened_values.extend(value.values())
            else:
                flattened_values.append(value)

        new_devices = list(filter(lambda x: isinstance(x, Device), flattened_values))
        self.add_readables(new_devices, wrapper)

    def add_readables(
        self,
        devices: Sequence[Device],
        wrapper: StandardReadableFormat = StandardReadableFormat.CHILD,
    ) -> None:
        """Add the given devices to the lists of known Devices

        Add the provided Devices to the relevant fields, based on the Signal's
        interfaces.

        The provided wrapper class will be applied to all Devices and can be used to
        specify their behaviour.

        Parameters
        ----------
        devices:
            The devices to be added
        wrapper:
            Wrapper class to apply to all Devices created inside the context manager.

        See Also
        --------
        :func:`~StandardReadable.add_children_as_readables`
        :class:`ConfigSignal`
        :class:`HintedSignal`
        :meth:`HintedSignal.uncached`
        """

        for device in devices:
            match wrapper:
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
                    assert isinstance(device, SignalR), f"{device} is not a SignalR"
                    self._describe_config_funcs += (device.describe,)
                    self._read_config_funcs += (device.read,)
                case StandardReadableFormat.HINTED_SIGNAL:
                    assert isinstance(device, SignalR), f"{device} is not a SignalR"
                    self._describe_funcs += (device.describe,)
                    self._read_funcs += (device.read,)
                    self._stageables += (device,)
                    self._has_hints += (_HintsFromName(device),)
                case StandardReadableFormat.UNCACHED_SIGNAL:
                    assert isinstance(device, SignalR), f"{device} is not a SignalR"
                    self._describe_funcs += (device.describe,)
                    self._read_funcs += (_UncachedRead(device),)
                case StandardReadableFormat.HINTED_UNCACHED_SIGNAL:
                    assert isinstance(device, SignalR), f"{device} is not a SignalR"
                    self._describe_funcs += (device.describe,)
                    self._read_funcs += (_UncachedRead(device),)
                    self._has_hints += (_HintsFromName(device),)


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
