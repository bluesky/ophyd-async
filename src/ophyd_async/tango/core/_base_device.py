from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from tango import DeviceProxy
from tango.asyncio import DeviceProxy as AsyncDeviceProxy

from ophyd_async.core import Device, DeviceConnector, DeviceFiller, LazyMock

from ._signal import TangoSignalBackend, infer_python_type, infer_signal_type
from ._utils import get_full_attr_trl

T = TypeVar("T")


class TangoDevice(Device):
    """General class for TangoDevices.

    Extends Device to provide attributes for Tango devices.

    :param trl: Tango resource locator, typically of the device server.
        An asynchronous DeviceProxy object will be created using the
        trl and awaited when the device is connected.
    """

    trl: str = ""
    proxy: DeviceProxy | None = None

    def __init__(
        self,
        trl: str | None,
        support_events: bool = False,
        name: str = "",
        auto_fill_signals: bool = True,
    ) -> None:
        connector = TangoDeviceConnector(
            trl=trl,
            support_events=support_events,
            auto_fill_signals=auto_fill_signals,
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
        support_events: bool,
        auto_fill_signals: bool = True,
    ) -> None:
        self.trl = trl
        self._support_events = support_events
        self._auto_fill_signals = auto_fill_signals

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            self.filler = DeviceFiller(
                device=device,
                signal_backend_factory=TangoSignalBackend,
                device_connector_factory=lambda: TangoDeviceConnector(
                    None, self._support_events
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
        if not self.trl:
            raise RuntimeError(f"Could not created Device Proxy for TRL {self.trl}")
        self.proxy = await AsyncDeviceProxy(self.trl)
        children = sorted(
            set()
            .union(self.proxy.get_attribute_list())
            .union(self.proxy.get_command_list())
        )

        children = [
            child for child in children if child not in self.filler.ignored_signals
        ]

        not_filled = {unfilled for unfilled, _ in device.children()}

        # If auto_fill_signals is True, fill all children inferred from the device
        # else fill only the children that are annotated
        for name in children:
            if self._auto_fill_signals or name in not_filled:
                # TODO: strip attribute name
                full_trl = get_full_attr_trl(self.trl, name)
                signal_type = await infer_signal_type(full_trl, self.proxy)
                if signal_type:
                    backend = self.filler.fill_child_signal(name, signal_type)
                    # don't overlaod datatype if provided by annotation
                    if backend.datatype is None:
                        backend.datatype = await infer_python_type(full_trl, self.proxy)
                    backend.set_trl(full_trl)

        # Check that all the requested children have been filled
        self.filler.check_filled(f"{self.trl}: {children}")

        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_real(device, timeout, force_reconnect)
