from __future__ import annotations

from ophyd_async.core import (
    Device,
    DeviceConnector,
    DeviceFiller,
    Signal,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.epics.signal import (
    PvaSignalBackend,
    pvget_with_timeout,
)


def _get_signal_details(entry: dict[str, str]) -> tuple[type[Signal], str, str]:
    match entry:
        case {"r": read_pv}:
            return SignalR, read_pv, read_pv
        case {"r": read_pv, "w": write_pv}:
            return SignalRW, read_pv, write_pv
        case {"rw": read_write_pv}:
            return SignalRW, read_write_pv, read_write_pv
        case {"x": execute_pv}:
            return SignalX, execute_pv, execute_pv
        case _:
            raise TypeError(f"Can't process entry {entry}")


class PviDeviceConnector(DeviceConnector):
    def __init__(self, pvi_pv: str = "") -> None:
        self.pvi_pv = pvi_pv

    def create_children_from_annotations(self, device: Device):
        self._filler = DeviceFiller(
            device=device,
            signal_backend_type=PvaSignalBackend,
            device_connector_type=type(self),
        )

    async def connect(
        self, device: Device, mock: bool, timeout: float, force_reconnect: bool
    ) -> None:
        if mock:
            # Make 2 entries for each DeviceVector
            self._filler.make_soft_device_vector_entries(2)
        else:
            pvi_structure = await pvget_with_timeout(self.pvi_pv, timeout)
            entries: dict[str, dict[str, str]] = pvi_structure["value"].todict()
            # Ensure we have device vectors for everything that should be there
            self._filler.make_device_vectors(list(entries))
            for name, entry in entries.items():
                if set(entry) == {"d"}:
                    backend = self._filler.make_child_device(name)
                    backend.pvi_pv = entry["d"]
                else:
                    signal_type, read_pv, write_pv = _get_signal_details(entry)
                    backend = self._filler.make_child_signal(name, signal_type)
                    backend.read_pv = read_pv
                    backend.write_pv = write_pv
            # Check that all the requested children have been created
            if unfilled := self._filler.unfilled():
                raise RuntimeError(
                    f"{device.name}: cannot provision {unfilled} from "
                    f"{self.pvi_pv}: {entries}"
                )
        return await super().connect(device, mock, timeout, force_reconnect)
