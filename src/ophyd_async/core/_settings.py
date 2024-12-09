from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any

from ._device import Device
from ._signal import SignalRW
from ._signal_backend import SignalDatatypeT


class Settings(MutableMapping[SignalRW[Any], Any]):
    def __init__(
        self, device: Device, settings: MutableMapping[SignalRW, Any] | None = None
    ):
        self.device = device
        self._settings = {}
        self.update(settings or {})

    def __getitem__(self, key: SignalRW[SignalDatatypeT]) -> SignalDatatypeT:
        return self._settings[key]

    def _is_in_device(self, device: Device) -> bool:
        while device.parent and device.parent is not self.device:
            # While we have a parent that is not the right device
            # continue searching up the tree
            device = device.parent
        return device.parent is self.device

    def __setitem__(
        self, key: SignalRW[SignalDatatypeT], value: SignalDatatypeT | None
    ) -> None:
        # Check the types on entry to dict to make sure we can't accidentally
        # add a non-signal type
        if not isinstance(key, SignalRW):
            raise TypeError(f"Expected SignalRW, got {key}")
        if not self._is_in_device(key):
            raise KeyError(f"Signal {key} is not a child of {self.device}")
        self._settings[key] = value

    def __delitem__(self, key: SignalRW) -> None:
        del self._settings[key]

    def __iter__(self) -> Iterator[SignalRW]:
        yield from iter(self._settings)

    def __len__(self) -> int:
        return len(self._settings)

    def __or__(self, other: MutableMapping[SignalRW, Any]) -> Settings:
        if isinstance(other, Settings) and not self._is_in_device(other.device):
            raise ValueError(f"{other.device} is not a child of {self.device}")
        return Settings(self.device, self._settings | dict(other))

    def partition(
        self, predicate: Callable[[SignalRW], bool]
    ) -> tuple[Settings, Settings]:
        where_true, where_false = Settings(self.device), Settings(self.device)
        for signal, value in self.items():
            dest = where_true if predicate(signal) else where_false
            dest[signal] = value
        return where_true, where_false


class SettingsProvider:
    @abstractmethod
    async def store(self, name: str, data: dict[str, Any]): ...

    @abstractmethod
    async def retrieve(self, name: str) -> dict[str, Any]: ...
