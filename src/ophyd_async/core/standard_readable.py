from contextlib import contextmanager
from typing import (
    Callable,
    Dict,
    Generator,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)

from bluesky.protocols import Descriptor, HasHints, Hints, Reading

from ophyd_async.protocols import AsyncConfigurable, AsyncReadable, AsyncStageable

from .async_status import AsyncStatus
from .device import Device, DeviceVector
from .signal import SignalR
from .utils import merge_gathered_dicts

ReadableChild = Union[AsyncReadable, AsyncConfigurable, AsyncStageable, HasHints]
ReadableChildWrapper = Union[
    Callable[[ReadableChild], ReadableChild], Type["ConfigSignal"], Type["HintedSignal"]
]


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
    _readables: Tuple[AsyncReadable, ...] = ()
    _configurables: Tuple[AsyncConfigurable, ...] = ()
    _stageables: Tuple[AsyncStageable, ...] = ()
    _has_hints: Tuple[HasHints, ...] = ()

    @AsyncStatus.wrap
    async def stage(self) -> None:
        for sig in self._stageables:
            await sig.stage().task

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        for sig in self._stageables:
            await sig.unstage().task

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(
            [sig.describe_configuration() for sig in self._configurables]
        )

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(
            [sig.read_configuration() for sig in self._configurables]
        )

    async def describe(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts([sig.describe() for sig in self._readables])

    async def read(self) -> Dict[str, Reading]:
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
        wrapper: Optional[ReadableChildWrapper] = None,
    ) -> Generator[None, None, None]:
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
        devices: Sequence[Device],
        wrapper: Optional[ReadableChildWrapper] = None,
    ) -> None:
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

    async def read_configuration(self) -> Dict[str, Reading]:
        return await self.signal.read()

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await self.signal.describe()


class HintedSignal(HasHints, AsyncReadable):
    def __init__(self, signal: ReadableChild, allow_cache: bool = True) -> None:
        assert isinstance(signal, SignalR), f"Expected signal, got {signal}"
        self.signal = signal
        self.cached = None if allow_cache else allow_cache
        if allow_cache:
            self.stage = signal.stage
            self.unstage = signal.unstage

    async def read(self) -> Dict[str, Reading]:
        return await self.signal.read(cached=self.cached)

    async def describe(self) -> Dict[str, Descriptor]:
        return await self.signal.describe()

    @property
    def name(self) -> str:
        return self.signal.name

    @property
    def hints(self) -> Hints:
        return {"fields": [self.signal.name]}

    @classmethod
    def uncached(cls, signal: ReadableChild) -> "HintedSignal":
        return cls(signal, allow_cache=False)
