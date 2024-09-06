from __future__ import annotations

from typing import Dict, Optional, Tuple, Union, get_type_hints

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
    _polling: Tuple[bool, float, float, float] = (False, 0.1, None, 0.1)
    _signal_polling: Dict[str, Tuple[bool, float, float, float]] = {}

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
                    if name in self._signal_polling:
                        backend.allow_events(False)
                        backend.set_polling(*self._signal_polling[name])
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


def tango_polling(
    polling: Optional[
        Union[Tuple[float, float, float], Dict[str, Tuple[float, float, float]]]
    ] = None,
    signal_polling: Optional[Dict[str, Tuple[float, float, float]]] = None,
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

    Returns
    -------
    Callable
        A class decorator that sets the `_polling` and `_signal_polling` attributes on
        the decorated class.

    Example
    -------
    Device-level and signal-level polling:
    @tango_polling(
        polling=(0.5, 1.0, 0.1),
        signal_polling={
            'signal1': (0.5, 1.0, 0.1),
            'signal2': (1.0, 2.0, 0.2),
        }
    )
    class MyTangoDevice(TangoDevice):
        signal1: Signal
        signal2: Signal
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
