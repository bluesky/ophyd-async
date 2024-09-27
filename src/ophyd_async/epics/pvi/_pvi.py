import re
from typing import get_args, get_type_hints

from ophyd_async.core import (
    Device,
    DeviceVector,
    Signal,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.core._device import DeviceChildConnector
from ophyd_async.core._utils import get_ultimate_origin
from ophyd_async.epics.signal._p4p import (
    PvaSignalConnector,
    pvget_with_timeout,
)


def _strip_number_from_string(string: str) -> tuple[str, int | None]:
    match = re.match(r"(.*?)(\d*)$", string)
    assert match

    name = match.group(1)
    number = match.group(2) or None
    if number is None:
        return name, None
    else:
        return name, int(number)


def get_signal_details(entry: dict[str, str]) -> tuple[type[Signal], str, str]:
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


def make_pvi_device(device_type: type[Device], pvi_pv: str) -> Device:
    device = device_type()
    device.connect = PviDeviceConnector(device=device, pvi_pv=pvi_pv)
    return device


class PviDeviceConnector(DeviceChildConnector):
    def __init__(self, device: Device, pvi_pv: str) -> None:
        self.pvi_pv = pvi_pv
        self._device_vector: dict[str, tuple[dict, type[Device]]] = {}
        for name, annotation in get_type_hints(device).items():
            origin = get_ultimate_origin(annotation)
            # Create empty Signals, DeviceVectors or Devices
            if issubclass(origin, Signal):
                if annotation is SignalX:
                    datatype = None
                else:
                    datatype = get_args(annotation)[0]
                setattr(device, name, origin(PvaSignalConnector(datatype, "", "")))
            elif origin == DeviceVector:
                children = {}
                self._device_vector[name] = (children, get_args(annotation)[0])
                setattr(device, name, DeviceVector(children))
            elif issubclass(origin, Device):
                setattr(device, name, make_pvi_device(origin, ""))
        super().__init__(device=device)

    def _make_device_vectors(self, entries: dict[str, dict[str, str]]):
        basename_numbers: dict[str, set[int]] = {}
        # Calculate the numbers associated with each basename
        for name in entries:
            basename, number = _strip_number_from_string(name)
            if number is not None:
                basename_numbers.setdefault(basename, set()).add(number)
        # If we have continuous numbers we should put them in a vector
        for basename, numbers in basename_numbers.items():
            if numbers == set(range(1, max(numbers) + 1)):
                if basename not in self._device_vector:
                    children = {}
                    self._device_vector[basename] = (children, Device)
                    setattr(self._device, basename, DeviceVector(children))

    def _make_child_device(self, name: str, pvi_pv: str):
        basename, number = _strip_number_from_string(name)
        attr = getattr(self, name, None)
        if basename in self._device_vector:
            # We made the device vectors above, so add to it
            children, device_type = self._device_vector[basename]
            children[number] = make_pvi_device(device_type, pvi_pv)
        elif isinstance(attr, Device):
            # Fill in PVI pv for existing device
            if not isinstance(attr.connect, PviDeviceConnector):
                raise TypeError(f"Expected {name} to be a PviDevice, got {attr}")
            attr.connect.pvi_pv = pvi_pv
        elif attr is None:
            # Don't know the type, so make a base Device
            setattr(self._device, name, make_pvi_device(Device, pvi_pv))
        else:
            raise TypeError(f"Cannot make PviDevice {name} as it would shadow {attr}")

    def _make_child_signal(self, name: str, entry: dict[str, str]):
        signal_cls, read_pv, write_pv = get_signal_details(entry)
        signal = getattr(self, name, None)
        if signal:
            # Validate or fill in PVI signal
            if not isinstance(signal, signal_cls):
                raise TypeError(f"Expected {name} to be {signal_cls}, got {signal}")
            connect = signal.connect
            if not isinstance(connect, PvaSignalConnector):
                raise TypeError(f"Expected {name} to be a PvaSignal, got {connect}")
            connect.read_pv = read_pv
            connect.write_pv = write_pv
        else:
            # Make a new signal
            connector = PvaSignalConnector(None, read_pv, write_pv)
            setattr(self, name, signal_cls(connector))

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        pvi_structure = await pvget_with_timeout(self.pvi_pv, timeout)
        # Ensure we have device vectors for everything that should be there
        self._make_device_vectors(pvi_structure["value"])
        for name, entry in pvi_structure["value"].items():
            if set(entry) == {"d"}:
                self._make_child_device(name, pvi_pv=entry["d"])
            else:
                self._make_child_signal(name, entry)
        # Make sure children as named
        self._device.set_name(self._device.name)
        return await super().connect(mock, timeout, force_reconnect)
