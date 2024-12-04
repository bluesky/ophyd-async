from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from ophyd_async.core import Device, DeviceConnector, DeviceFiller, LazyMock
from tango import DeviceProxy as DeviceProxy
from tango.asyncio import DeviceProxy as AsyncDeviceProxy

from ._signal import TangoSignalBackend, infer_python_type, infer_signal_type

T = TypeVar("T")


class TangoDevice(Device):
    """
    General class for TangoDevices. Extends Device to provide attributes for Tango
    devices.

    Parameters
    ----------
    trl: str
        Tango resource locator, typically of the device server.
    device_proxy: Optional[Union[AsyncDeviceProxy, SyncDeviceProxy]]
        Asynchronous or synchronous DeviceProxy object for the device. If not provided,
        an asynchronous DeviceProxy object will be created using the trl and awaited
        when the device is connected.
    """

    trl: str = ""
    proxy: DeviceProxy | None = None

    def __init__(
        self,
        trl: str | None = None,
        device_proxy: DeviceProxy | None = None,
        support_events: bool = False,
        name: str = "",
    ) -> None:
        connector = TangoDeviceConnector(
            trl=trl, device_proxy=device_proxy, support_events=support_events
        )
        super().__init__(name=name, connector=connector)


@dataclass
class TangoPolling(Generic[T]):
    ophyd_polling_period: float = 0.1
    abs_change: T | None = None
    rel_change: T | None = None


def fill_backend_with_polling(
    support_events: bool, backend: TangoSignalBackend, annotations: list[Any]
):
    unhandled = []
    while annotations:
        annotation = annotations.pop(0)
        backend.allow_events(support_events)
        if isinstance(annotation, TangoPolling):
            backend.set_polling(
                not support_events,
                annotation.ophyd_polling_period,
                annotation.abs_change,
                annotation.rel_change,
            )
        else:
            unhandled.append(annotation)
    annotations.extend(unhandled)
    # These leftover annotations will now be handled by the iterator


class TangoDeviceConnector(DeviceConnector):
    def __init__(
        self,
        trl: str | None,
        device_proxy: DeviceProxy | None,
        support_events: bool,
    ) -> None:
        self.trl = trl
        self.proxy = device_proxy
        self._support_events = support_events

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            self.filler = DeviceFiller(
                device=device,
                signal_backend_factory=TangoSignalBackend,
                device_connector_factory=lambda: TangoDeviceConnector(
                    None, None, self._support_events
                ),
            )
            list(self.filler.create_devices_from_annotations(filled=False))
            for backend, annotations in self.filler.create_signals_from_annotations(
                filled=False
            ):
                fill_backend_with_polling(self._support_events, backend, annotations)
            self.filler.check_created()

    async def connect_mock(self, device: Device, mock: LazyMock):
        # Make 2 entries for each DeviceVector
        self.filler.create_device_vector_entries_to_mock(2)
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_mock(device, mock)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        if self.trl and self.proxy is None:
            self.proxy = await AsyncDeviceProxy(self.trl)
        elif self.proxy and not self.trl:
            self.trl = self.proxy.name()
        else:
            raise TypeError("Neither proxy nor trl supplied")

        children = sorted(
            set()
            .union(self.proxy.get_attribute_list())
            .union(self.proxy.get_command_list())
        )
        for name in children:
            # TODO: strip attribute name
            full_trl = f"{self.trl}/{name}"
            signal_type = await infer_signal_type(full_trl, self.proxy)
            if signal_type:
                backend = self.filler.fill_child_signal(name, signal_type)
                backend.datatype = await infer_python_type(full_trl, self.proxy)
                backend.set_trl(full_trl)
        # Check that all the requested children have been filled
        self.filler.check_filled(f"{self.trl}: {children}")
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_real(device, timeout, force_reconnect)
