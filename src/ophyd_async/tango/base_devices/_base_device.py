from __future__ import annotations

import asyncio
from typing import Optional, Union

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    Signal,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
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

    def __init__(
        self,
        trl: Optional[str] = None,
        device_proxy: Optional[Union[AsyncDeviceProxy, SyncDeviceProxy]] = None,
        name: str = "",
    ) -> None:
        if not trl and not device_proxy:
            raise ValueError("Either 'trl' or 'device_proxy' must be provided.")

        self.trl = trl if trl else ""
        self.proxy = device_proxy if device_proxy else AsyncDeviceProxy(trl)

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
                elif isinstance(self.proxy, asyncio.Future):
                    self.proxy = await self.proxy
            except Exception as e:
                raise RuntimeError("Could not connect to device proxy") from e
            return self

        await closure()
        self.register_signals()
        # set_name should be called again to propagate the new signal names
        self.set_name(self.name)

        await super().connect(mock=mock, timeout=timeout)

    def register_signals(self):
        for name, obj_type in self.__annotations__.items():
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
                    signal._backend = backend  # noqa: SLF001

    def create_children_from_annotations(self):
        for attr_name, obj_type in self.__annotations__.items():
            if (
                isinstance(obj_type, type)
                and issubclass(obj_type, Signal)
                or obj_type is None
            ):
                if obj_type is SignalRW:
                    setattr(self, attr_name, SignalRW())
                elif obj_type is SignalR:
                    setattr(self, attr_name, SignalR())
                elif obj_type is SignalW:
                    setattr(self, attr_name, SignalW())
                elif obj_type is SignalX:
                    setattr(self, attr_name, SignalX())
                elif obj_type is Signal or obj_type is None:
                    tango_name = attr_name.lstrip("_")
                    setattr(
                        self,
                        attr_name,
                        infer_signal_frontend(trl=f"{self.trl}/" f"{tango_name}"),
                    )
                else:
                    print(obj_type, type(obj_type))
                    raise ValueError(f"Invalid signal type {obj_type}")


# --------------------------------------------------------------------
