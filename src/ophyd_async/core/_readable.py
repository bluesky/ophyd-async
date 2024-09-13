import warnings
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager

from bluesky.protocols import HasHints, Hints, Reading
from event_model import DataKey

from ._device import Device, DeviceVector
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable
from ._signal import SignalR
from ._status import AsyncStatus
from ._utils import merge_gathered_dicts

ReadableChild = AsyncReadable | AsyncConfigurable | AsyncStageable | HasHints
ReadableChildWrapper = (
    Callable[[ReadableChild], ReadableChild]
    | type["ConfigSignal"]
    | type["HintedSignal"]
)


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
    _readables: tuple[AsyncReadable, ...] = ()
    _configurables: tuple[AsyncConfigurable, ...] = ()
    _stageables: tuple[AsyncStageable, ...] = ()
    _has_hints: tuple[HasHints, ...] = ()

    def set_readable_signals(
        self,
        read: Sequence[SignalR] = (),
        config: Sequence[SignalR] = (),
        read_uncached: Sequence[SignalR] = (),
    ):
        """
        Parameters
        ----------
        read:
            Signals to make up :meth:`~StandardReadable.read`
        conf:
            Signals to make up :meth:`~StandardReadable.read_configuration`
        read_uncached:
            Signals to make up :meth:`~StandardReadable.read` that won't be cached
        """
        warnings.warn(
            DeprecationWarning(
                "Migrate to `add_children_as_readables` context manager or "
                "`add_readables` method"
            ),
            stacklevel=2,
        )
        self.add_readables(read, wrapper=HintedSignal)
        self.add_readables(config, wrapper=ConfigSignal)
        self.add_readables(read_uncached, wrapper=HintedSignal.uncached)

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
            [sig.describe_configuration() for sig in self._configurables]
        )

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(
            [sig.read_configuration() for sig in self._configurables]
        )

    async def describe(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts([sig.describe() for sig in self._readables])

    async def read(self) -> dict[str, Reading]:
        return await merge_gathered_dicts([sig.read() for sig in self._readables])

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
        wrapper: ReadableChildWrapper | None = None,
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

        dict_copy = self.__dict__.copy()

        yield

        # Set symmetric difference operator gives all newly added keys
        new_keys = dict_copy.keys() ^ self.__dict__.keys()
        new_values = [self.__dict__[key] for key in new_keys]

        flattened_values = []
        for value in new_values:
            if isinstance(value, DeviceVector):
                children = value.children()
                flattened_values.extend([x[1] for x in children])
            else:
                flattened_values.append(value)

        new_devices = list(filter(lambda x: isinstance(x, Device), flattened_values))
        self.add_readables(new_devices, wrapper)

    def add_readables(
        self,
        devices: Sequence[ReadableChild],
        wrapper: ReadableChildWrapper | None = None,
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

        for readable in devices:
            obj = readable
            if wrapper:
                obj = wrapper(readable)

            if isinstance(obj, AsyncReadable):
                self._readables += (obj,)

            if isinstance(obj, AsyncConfigurable):
                self._configurables += (obj,)

            if isinstance(obj, AsyncStageable):
                self._stageables += (obj,)

            if isinstance(obj, HasHints):
                self._has_hints += (obj,)


class ConfigSignal(AsyncConfigurable):
    def __init__(self, signal: ReadableChild) -> None:
        assert isinstance(signal, SignalR), f"Expected signal, got {signal}"
        self.signal = signal

    async def read_configuration(self) -> dict[str, Reading]:
        return await self.signal.read()

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await self.signal.describe()

    @property
    def name(self) -> str:
        return self.signal.name


class HintedSignal(HasHints, AsyncReadable):
    def __init__(self, signal: ReadableChild, allow_cache: bool = True) -> None:
        assert isinstance(signal, SignalR), f"Expected signal, got {signal}"
        self.signal = signal
        self.cached = None if allow_cache else allow_cache
        if allow_cache:
            self.stage = signal.stage
            self.unstage = signal.unstage

    async def read(self) -> dict[str, Reading]:
        return await self.signal.read(cached=self.cached)

    async def describe(self) -> dict[str, DataKey]:
        return await self.signal.describe()

    @property
    def name(self) -> str:
        return self.signal.name

    @property
    def hints(self) -> Hints:
        if self.signal.name == "":
            return {"fields": []}
        return {"fields": [self.signal.name]}

    @classmethod
    def uncached(cls, signal: ReadableChild) -> "HintedSignal":
        return cls(signal, allow_cache=False)
