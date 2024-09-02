from __future__ import annotations

from typing import Optional, Union, get_type_hints

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    Signal,
)
from ophyd_async.tango.signal import (
    infer_python_type,
    infer_signal_frontend,
    make_backend,
)
from tango import DeviceProxy as SyncDeviceProxy
from tango.asyncio import DeviceProxy as AsyncDeviceProxy


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
    proxy: Optional[Union[AsyncDeviceProxy, SyncDeviceProxy]] = None
    _polling: tuple = (False, 0.1, None, 0.1)

    def __init__(
        self,
        trl: Optional[str] = None,
        device_proxy: Optional[Union[AsyncDeviceProxy, SyncDeviceProxy]] = None,
        name: str = "",
    ) -> None:
        if not trl and not device_proxy:
            raise ValueError("Either 'trl' or 'device_proxy' must be provided.")

        self.trl = trl if trl else ""
        self.proxy = device_proxy

        self.create_children_from_annotations()
        super().__init__(name=name)

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        async def closure():
            try:
                if self.proxy is None:
                    self.proxy = await AsyncDeviceProxy(self.trl)
            except Exception as e:
                raise RuntimeError("Could not connect to device proxy") from e
            return self

        if self.trl in ["", None]:
            self.trl = self.proxy.name()

        await closure()
        self.register_signals()
        # set_name should be called again to propagate the new signal names
        self.set_name(self.name)

        await super().connect(mock=mock, timeout=timeout)

    def register_signals(self):
        annots = get_type_hints(self.__class__)
        for name, obj_type in annots.items():
            if hasattr(self, name):
                signal = getattr(self, name)
                if issubclass(type(signal), Signal):
                    tango_name = name.lstrip("_")
                    read_trl = f"{self.trl}/{tango_name}"
                    datatype = infer_python_type(read_trl)
                    backend = make_backend(
                        datatype=datatype,
                        read_trl=read_trl,
                        write_trl=read_trl,
                        device_proxy=self.proxy,
                    )
                    if self._polling[0]:
                        backend.allow_events(False)
                        backend.set_polling(*self._polling)
                    signal._backend = backend  # noqa: SLF001

    def create_children_from_annotations(self):
        annots = get_type_hints(self.__class__)
        for attr_name, obj_type in annots.items():
            if isinstance(obj_type, type):
                if obj_type is Signal:
                    tango_name = attr_name.lstrip("_")
                    trl = f"{self.trl}/{tango_name}"
                    setattr(
                        self, attr_name, infer_signal_frontend(trl=trl, name=attr_name)
                    )
                elif issubclass(obj_type, Signal):
                    setattr(self, attr_name, obj_type(name=attr_name))


def tango_polling(*args):
    """
    Class decorator to set polling for Tango devices. This is useful for device servers
    that do not support event-driven updates.
    """

    def decorator(cls):
        cls._polling = (True, *args)
        return cls

    return decorator
