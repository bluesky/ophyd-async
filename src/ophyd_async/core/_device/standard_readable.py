from typing import Dict, Sequence, Tuple

from bluesky.protocols import Configurable, Descriptor, Readable, Reading, Stageable

from ..async_status import AsyncStatus
from ..utils import merge_gathered_dicts
from ._signal.signal import SignalR
from .device import Device


class StandardReadable(Device, Readable, Configurable, Stageable):
    """Device that owns its children and provides useful default behavior.

    - When its name is set it renames child Devices
    - Signals can be registered for read() and read_configuration()
    - These signals will be subscribed for read() between stage() and unstage()
    """

    _read_signals: Tuple[SignalR, ...] = ()
    _configuration_signals: Tuple[SignalR, ...] = ()
    _read_uncached_signals: Tuple[SignalR, ...] = ()

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
            Signals to make up `read()`
        conf:
            Signals to make up `read_configuration()`
        read_uncached:
            Signals to make up `read()` that won't be cached
        """
        self._read_signals = tuple(read)
        self._configuration_signals = tuple(config)
        self._read_uncached_signals = tuple(read_uncached)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        for sig in self._read_signals + self._configuration_signals:
            await sig.stage().task

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        for sig in self._read_signals + self._configuration_signals:
            await sig.unstage().task

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(
            [sig.describe() for sig in self._configuration_signals]
        )

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(
            [sig.read() for sig in self._configuration_signals]
        )

    async def describe(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(
            [sig.describe() for sig in self._read_signals + self._read_uncached_signals]
        )

    async def read(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(
            [sig.read() for sig in self._read_signals]
            + [sig.read(cached=False) for sig in self._read_uncached_signals]
        )
