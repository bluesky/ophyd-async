from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any, Generic

from ._device import Device, DeviceT
from ._readable import ReadableFormats
from ._signal import SignalRW
from ._signal_backend import SignalDatatypeT


class Settings(MutableMapping[SignalRW[Any], Any], Generic[DeviceT]):
    """Used for supplying settings to signals.

    :param device: The device that the settings are for.
    :param settings: A dictionary of settings to start with.

    :example:
    ```python
    # Settings are created from a dict of signals to values
    settings1 = Settings(device, {device.sig1: 1, device.sig2: 2})
    settings2 = Settings(device, {device.sig1: 10, device.sig3: 3})
    # They act like a dictionaries
    assert settings1[device.sig1] == 1
    # Including the ability to "or" two settings together
    settings = settings1 | settings2
    assert dict(settings) == {
        device.sig1: 10,
        device.sig2: 2,
        device.sig3: 3,
    }
    ```
    """

    def __init__(
        self,
        device: DeviceT,
        settings: MutableMapping[SignalRW, Any] | None = None,
        readable_formats: ReadableFormats | None = None,
    ):
        self.device = device
        self._settings = {}
        self.update(settings or {})
        self.readable_formats: ReadableFormats = dict(readable_formats or {})
        """How the Device's children contribute to its bluesky verbs.

        Stored and applied alongside the signal values, as the two change on
        the same cadence. Applied by [](#apply_settings).
        """

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

    def __or__(self, other: MutableMapping[SignalRW, Any]) -> Settings[DeviceT]:
        """Create a new Settings that is the union of self overridden by other.

        Readable formats merge per (owner, child), the same granularity that
        values merge at and that [](#apply_readable_formats) applies at, so
        `other` only replaces the children it actually mentions.

        :raises ValueError:
            If `other` is a `Settings` for a Device outside this one, or for a
            Device below this one while carrying readable formats -- their paths
            would be relative to a different root.
        """
        formats = {
            owner: dict(entries) for owner, entries in self.readable_formats.items()
        }
        if isinstance(other, Settings):
            if other.device is not self.device:
                if not self._is_in_device(other.device):
                    msg = f"{other.device} is not a child of {self.device}"
                    raise ValueError(msg)
                if other.readable_formats:
                    # Paths in a ReadableFormats are relative to its own device,
                    # so <ROOT_DEVICE> and every dotted path would mean something
                    # different once merged. Re-rooting them is not implemented
                    # as nothing needs it yet; better to say so than to silently
                    # attach them to the wrong Device.
                    msg = (
                        f"Cannot merge readable formats from {other.device}, whose "
                        f"paths are relative to it rather than to {self.device}"
                    )
                    raise ValueError(msg)
            for owner, entries in other.readable_formats.items():
                formats.setdefault(owner, {}).update(entries)
        return Settings(self.device, self._settings | dict(other), formats)

    def partition(
        self, predicate: Callable[[SignalRW], bool]
    ) -> tuple[Settings[DeviceT], Settings[DeviceT]]:
        """Partition into two Settings based on a predicate.

        :param predicate:
            Callable that takes each signal, and returns a boolean to say if it
            should be in the first returned Settings
        :returns:
            `(where_true, where_false)` where each is a Settings object.
            The first contains the signals for which the predicate returned True,
            and the second contains the signals for which the predicate returned False.

        Both halves carry the *same* `readable_formats`. Formats are not a value
        that can differ, and a device specific apply plan normally applies only
        the halves and never the original Settings (see `apply_panda_settings`),
        so putting them on one half would mean whichever half that plan applied
        first silently decided whether formats were restored at all. Applying
        them more than once is harmless: it writes to no hardware and is
        idempotent.

        :example:
        ```python
        settings = Settings(device, {device.special: 1, device.sig: 2})
        specials, others = settings.partition(lambda sig: "special" in sig.name)
        ```
        """
        where_true = Settings(self.device, readable_formats=self.readable_formats)
        where_false = Settings(self.device, readable_formats=self.readable_formats)
        for signal, value in self.items():
            dest = where_true if predicate(signal) else where_false
            dest[signal] = value
        return where_true, where_false


class SettingsProvider:
    """Base class for providing settings."""

    @abstractmethod
    async def store(self, name: str, data: dict[str, Any]):
        """Store the data, associating it with the given name."""

    @abstractmethod
    async def retrieve(self, name: str) -> dict[str, Any]:
        """Retrieve the data associated with the given name."""
