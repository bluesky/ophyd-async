from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any

from ._device import Device
from ._signal import SignalRW, walk_rw_signals
from ._signal_backend import SignalDatatypeT


class Settings(MutableMapping[SignalRW[Any], Any]):
    def __init__(self, settings: MutableMapping[SignalRW, Any] | None = None):
        self._settings = {}
        self.update(settings or {})

    def __getitem__(self, key: SignalRW[SignalDatatypeT]) -> SignalDatatypeT:
        return self._settings[key]

    def __setitem__(
        self, key: SignalRW[SignalDatatypeT], value: SignalDatatypeT
    ) -> None:
        # Check the types on entry to dict to make sure we can't accidentally
        # add a non-signal type
        if not isinstance(key, SignalRW):
            raise TypeError(f"Expected SignalRW, got {key}")
        if key.datatype and not isinstance(value, key.datatype):
            raise TypeError(f"Expected {key.datatype}, got {value}")
        self._settings[key] = value

    def __delitem__(self, key: SignalRW) -> None:
        del self._settings[key]

    def __iter__(self) -> Iterator[SignalRW]:
        yield from iter(self._settings)

    def __len__(self) -> int:
        return len(self._settings)

    def __or__(self, other: MutableMapping[SignalRW, Any]) -> Settings:
        return Settings(self._settings | dict(other))

    def partition(
        self, predicate: Callable[[SignalRW], bool]
    ) -> tuple[Settings, Settings]:
        where_true, where_false = Settings(), Settings()
        for signal, value in self.items():
            dest = where_true if predicate(signal) else where_false
            dest[signal] = value
        return where_true, where_false

    def check_can_apply_to(self, device: Device) -> None:
        signals_in_device = walk_rw_signals(device)
        # Check that the signals in settings are actually in the Device
        unknown_signals = set(self) - set(signals_in_device.values())
        assert not unknown_signals, f"Signal {unknown_signals} are not in {device}"


class SettingsProvider:
    @abstractmethod
    async def store(self, name: str, data: dict[str, Any]): ...

    @abstractmethod
    async def retrieve(self, name: str) -> dict[str, Any]: ...
