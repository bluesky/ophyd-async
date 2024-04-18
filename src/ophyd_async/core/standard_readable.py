from contextlib import contextmanager
from typing import Dict, Generator, List, Optional, Sequence, Type, Union

from bluesky.protocols import Descriptor, HasHints, Hints, Reading, Stageable

from ophyd_async.protocols import AsyncConfigurable, AsyncReadable, AsyncStageable

from .async_status import AsyncStatus
from .device import Device
from .signal import SignalR
from .utils import merge_gathered_dicts


class StandardReadable(
    Device, AsyncReadable, AsyncConfigurable, AsyncStageable, HasHints
):
    """Device that owns its children and provides useful default behavior.

    - When its name is set it renames child Devices
    - Signals can be registered for read() and read_configuration()
    - These signals will be subscribed for read() between stage() and unstage()
    """

    _readables: List[AsyncReadable] = []
    _configurables: List[AsyncConfigurable] = []
    _stageables: List[AsyncStageable] = []

    _hints: Hints = {}

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
        return self._hints

    @contextmanager
    def add_children_as_readables(
        self,
        wrapper: Optional[Type[Union["ConfigSignal", "HintedSignal"]]] = None,
    ) -> Generator[None, None, None]:
        dict_copy = self.__dict__.copy()

        yield

        # Set symmetric difference operator gives all newly added items
        new_attributes = dict_copy.items() ^ self.__dict__.items()
        new_signals: List[SignalR] = [x[1] for x in new_attributes]

        self._wrap_signals(wrapper, new_signals)

    def add_readables(
        self,
        wrapper: Type[Union["ConfigSignal", "HintedSignal"]],
        *signals: SignalR,
    ) -> None:

        self._wrap_signals(wrapper, signals)

    def _wrap_signals(
        self,
        wrapper: Optional[Type[Union["ConfigSignal", "HintedSignal"]]],
        signals: Sequence[SignalR],
    ):

        for signal in signals:
            obj: Union[SignalR, "ConfigSignal", "HintedSignal"] = signal
            if wrapper:
                obj = wrapper(signal)

            if isinstance(obj, AsyncReadable):
                self._readables.append(obj)

            if isinstance(obj, AsyncConfigurable):
                self._configurables.append(obj)

            if isinstance(obj, AsyncStageable):
                self._stageables.append(obj)

            if isinstance(obj, HasHints):
                new_hint = obj.hints

                # Merge the existing and new hints, based on the type of the value.
                # This avoids default dict merge behaviour that overrided the values;
                # we want to combine them when they are Sequences, and ensure they are
                # identical when string values.
                for key, value in new_hint.items():
                    if isinstance(value, Sequence):
                        if key in self._hints:
                            self._hints[key] = (  # type: ignore[literal-required]
                                self._hints[key]  # type: ignore[literal-required]
                                + value
                            )
                        else:
                            self._hints[key] = value  # type: ignore[literal-required]
                    elif isinstance(value, str):
                        if key in self._hints:
                            assert (
                                self._hints[key]  # type: ignore[literal-required]
                                == value
                            ), "Hints value may not be overridden"
                        else:
                            self._hints[key] = value  # type: ignore[literal-required]
                    else:
                        raise AssertionError("Unknown type in Hints dictionary")


class ConfigSignal(AsyncConfigurable):

    def __init__(self, signal: SignalR) -> None:
        self.signal = signal

    async def read_configuration(self) -> Dict[str, Reading]:
        return await self.signal.read()

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await self.signal.describe()


class HintedSignal(HasHints, AsyncReadable):

    def __init__(self, signal: SignalR, cached: Optional[bool] = None) -> None:
        self.signal = signal
        self.cached = cached
        if cached:
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
    def uncached(cls, signal: SignalR):
        return cls(signal, cached=False)
