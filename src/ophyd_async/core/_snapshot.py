from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic

from ._device import DeviceT
from ._readable import ReadableFormats, StandardReadable, StandardReadableFormat
from ._settings import Settings
from ._signal import walk_devices, walk_rw_signals


class DeviceSnapshot(Generic[DeviceT]):
    """Stored values and readable format changes of a Device tree, by path.

    The paths are resolved against the Device when the snapshot is made.

    :param device: The Device the paths are relative to.
    :param values: `SignalRW` values by dotted path from `device`.
    :param formats:
        Readable format changes by (owner path, child path), where an owner path
        of `""` is `device` itself. A format of `None` stops the child
        contributing. `None` leaves formats alone.
    :raises NameError:
        If a value path does not name a `SignalRW` in the Device, a format path
        does not name a Device in the tree, or a format owner is not a
        `StandardReadable`. Every bad path is listed in one error.

    :example:
    ```python
    snapshot = DeviceSnapshot(
        det,
        {"acquire_time": 0.1},
        {("", "temperature"): StandardReadableFormat.HINTED_SIGNAL},
    )
    ```
    """

    def __init__(
        self,
        device: DeviceT,
        values: Mapping[str, Any],
        formats: Mapping[tuple[str, str], StandardReadableFormat | None] | None = None,
    ):
        self.device = device
        signals = walk_rw_signals(device)
        devices = walk_devices(device)
        problems = []
        unknown_names = set(values) - set(signals)
        if unknown_names:
            problems.append(f"Unknown signal names {sorted(unknown_names)}")
        self._settings = Settings(
            device, {signals[k]: v for k, v in values.items() if k in signals}
        )
        self._formats: ReadableFormats | None = None
        if formats is not None:
            self._formats = {}
            unknown_paths: list[tuple[str, str]] = []
            not_readable: list[str] = []
            for (owner_path, child_path), format in formats.items():
                owner = devices.get(owner_path) if owner_path else device
                if owner is None:
                    unknown_paths.append((owner_path, child_path))
                elif not isinstance(owner, StandardReadable):
                    not_readable.append(owner_path)
                else:
                    child = walk_devices(owner).get(child_path)
                    if child is None:
                        unknown_paths.append((owner_path, child_path))
                    else:
                        self._formats.setdefault(owner, {})[child] = format
            if unknown_paths:
                problems.append(
                    f"Unknown readable format paths {sorted(unknown_paths)}"
                )
            if not_readable:
                problems.append(
                    "Readable format owners that are not a StandardReadable "
                    f"{sorted(set(not_readable))}"
                )
        if problems:
            raise NameError("; ".join(problems))

    @property
    def settings(self) -> Settings[DeviceT]:
        """The signal values, as a new `Settings` of the Device."""
        return Settings(self.device, dict(self._settings))

    @property
    def readable_formats(self) -> ReadableFormats | None:
        """The readable format changes, as a new `ReadableFormats` of the Device.

        `None` if the snapshot was given no formats. Empty formats give `{}`,
        which resets every `StandardReadable` when applied.
        """
        if self._formats is None:
            return None
        return {owner: dict(changes) for owner, changes in self._formats.items()}
