from __future__ import annotations

from typing import TypeVar
from unittest.mock import Mock

from ophyd_async.core import Device, DeviceConnector, DeviceFiller
from ophyd_async.tango.signal import (
    TangoSignalBackend,
    infer_python_type,
    infer_signal_type,
)
from tango import DeviceProxy as DeviceProxy
from tango.asyncio import DeviceProxy as AsyncDeviceProxy

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
    _polling: tuple[bool, float, float | None, float | None] = (False, 0.1, None, 0.1)
    _signal_polling: dict[str, tuple[bool, float, float, float]] = {}
    _poll_only_annotated_signals: bool = True

    def __init__(
        self,
        trl: str | None = None,
        device_proxy: DeviceProxy | None = None,
        name: str = "",
    ) -> None:
        connector = TangoDeviceConnector(
            trl=trl,
            device_proxy=device_proxy,
            polling=self._polling,
            signal_polling=self._signal_polling,
        )
        super().__init__(name=name, connector=connector)


def tango_polling(
    polling: tuple[float, float, float]
    | dict[str, tuple[float, float, float]]
    | None = None,
    signal_polling: dict[str, tuple[float, float, float]] | None = None,
):
    """
    Class decorator to configure polling for Tango devices.

    This decorator allows for the configuration of both device-level and signal-level
    polling for Tango devices. Polling is useful for device servers that do not support
    event-driven updates.

    Parameters
    ----------
    polling : Optional[Union[Tuple[float, float, float],
              Dict[str, Tuple[float, float, float]]]], optional
        Device-level polling configuration as a tuple of three floats representing the
        polling interval, polling timeout, and polling delay. Alternatively,
        a dictionary can be provided to specify signal-level polling configurations
        directly.
    signal_polling : Optional[Dict[str, Tuple[float, float, float]]], optional
        Signal-level polling configuration as a dictionary where keys are signal names
        and values are tuples of three floats representing the polling interval, polling
        timeout, and polling delay.
    """
    if isinstance(polling, dict):
        signal_polling = polling
        polling = None

    def decorator(cls):
        if polling is not None:
            cls._polling = (True, *polling)
        if signal_polling is not None:
            cls._signal_polling = {k: (True, *v) for k, v in signal_polling.items()}
        return cls

    return decorator


class TangoDeviceConnector(DeviceConnector):
    def __init__(
        self,
        trl: str | None,
        device_proxy: DeviceProxy | None,
        polling: tuple[bool, float, float | None, float | None],
        signal_polling: dict[str, tuple[bool, float, float, float]],
    ) -> None:
        self.trl = trl
        self.proxy = device_proxy
        self._polling = polling
        self._signal_polling = signal_polling

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            self.filler = DeviceFiller(
                device=device,
                signal_backend_factory=TangoSignalBackend,
                device_connector_factory=lambda: TangoDeviceConnector(
                    None, None, (False, 0.1, None, None), {}
                ),
            )
            list(self.filler.create_devices_from_annotations(filled=False))
            list(self.filler.create_signals_from_annotations(filled=False))
            self.filler.check_created()

    async def connect(
        self, device: Device, mock: bool | Mock, timeout: float, force_reconnect: bool
    ) -> None:
        if mock:
            # Make 2 entries for each DeviceVector
            self.filler.create_device_vector_entries_to_mock(2)
        else:
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
                    if polling := self._signal_polling.get(name, ()):
                        backend.set_polling(*polling)
                        backend.allow_events(False)
                    elif self._polling[0]:
                        backend.set_polling(*self._polling)
                        backend.allow_events(False)
            # Check that all the requested children have been filled
            self.filler.check_filled(f"{self.trl}: {children}")
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect(device, mock, timeout, force_reconnect)
