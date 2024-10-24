from __future__ import annotations

from typing import (
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    Signal,
)
from ophyd_async.tango.signal import (
    TangoSignalBackend,
    __tango_signal_auto,
    make_backend,
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
        self.trl = trl if trl else ""
        self.proxy = device_proxy
        tango_create_children_from_annotations(self)
        super().__init__(name=name)

    def set_trl(self, trl: str):
        """Set the Tango resource locator."""
        if not isinstance(trl, str):
            raise ValueError("TRL must be a string.")
        self.trl = trl

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        if self.trl and self.proxy is None:
            self.proxy = await AsyncDeviceProxy(self.trl)
        elif self.proxy and not self.trl:
            self.trl = self.proxy.name()

        # Set the trl of the signal backends
        for child in self.children():
            if isinstance(child[1], Signal):
                if isinstance(child[1]._backend, TangoSignalBackend):  # noqa: SLF001
                    resource_name = child[0].lstrip("_")
                    read_trl = f"{self.trl}/{resource_name}"
                    child[1]._backend.set_trl(read_trl, read_trl)  # noqa: SLF001

        if self.proxy is not None:
            self.register_signals()
            await _fill_proxy_entries(self)

        # set_name should be called again to propagate the new signal names
        self.set_name(self.name)

        # Set the polling configuration
        if self._polling[0]:
            for child in self.children():
                child_type = type(child[1])
                if issubclass(child_type, Signal):
                    if isinstance(child[1]._backend, TangoSignalBackend):  # noqa: SLF001  # type: ignore
                        child[1]._backend.set_polling(*self._polling)  # noqa: SLF001  # type: ignore
                        child[1]._backend.allow_events(False)  # noqa: SLF001  # type: ignore
        if self._signal_polling:
            for signal_name, polling in self._signal_polling.items():
                if hasattr(self, signal_name):
                    attr = getattr(self, signal_name)
                    if isinstance(attr._backend, TangoSignalBackend):  # noqa: SLF001
                        attr._backend.set_polling(*polling)  # noqa: SLF001
                        attr._backend.allow_events(False)  # noqa: SLF001

        await super().connect(mock=mock, timeout=timeout)

    # Users can override this method to register new signals
    def register_signals(self):
        pass


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


def tango_create_children_from_annotations(
    device: TangoDevice, included_optional_fields: tuple[str, ...] = ()
):
    """Initialize blocks at __init__ of `device`."""
    for name, device_type in get_type_hints(type(device)).items():
        if name in ("_name", "parent"):
            continue

        # device_type, is_optional = _strip_union(device_type)
        # if is_optional and name not in included_optional_fields:
        #     continue
        #
        # is_device_vector, device_type = _strip_device_vector(device_type)
        # if is_device_vector:
        #     n_device_vector = DeviceVector()
        #     setattr(device, name, n_device_vector)

        # else:
        origin = get_origin(device_type)
        origin = origin if origin else device_type

        if issubclass(origin, Signal):
            type_args = get_args(device_type)
            datatype = type_args[0] if type_args else None
            backend = make_backend(datatype=datatype, device_proxy=device.proxy)
            setattr(device, name, origin(name=name, backend=backend))

        elif issubclass(origin, Device) or isinstance(origin, Device):
            assert callable(origin), f"{origin} is not callable."
            setattr(device, name, origin())


async def _fill_proxy_entries(device: TangoDevice):
    if device.proxy is None:
        raise RuntimeError(f"Device proxy is not connected for {device.name}")
    proxy_trl = device.trl
    children = [name.lstrip("_") for name, _ in device.children()]
    proxy_attributes = list(device.proxy.get_attribute_list())
    proxy_commands = list(device.proxy.get_command_list())
    combined = proxy_attributes + proxy_commands

    for name in combined:
        if name not in children:
            full_trl = f"{proxy_trl}/{name}"
            try:
                auto_signal = await __tango_signal_auto(
                    trl=full_trl, device_proxy=device.proxy
                )
                setattr(device, name, auto_signal)
            except RuntimeError as e:
                if "Commands with different in and out dtypes" in str(e):
                    print(
                        f"Skipping {name}. Commands with different in and out dtypes"
                        f" are not supported."
                    )
                    continue
                raise e


# def _strip_union(field: T | T) -> tuple[T, bool]:
#     if get_origin(field) is Union:
#         args = get_args(field)
#         is_optional = type(None) in args
#         for arg in args:
#             if arg is not type(None):
#                 return arg, is_optional
#     return field, False
#
#
# def _strip_device_vector(field: type[Device]) -> tuple[bool, type[Device]]:
#     if get_origin(field) is DeviceVector:
#         return True, get_args(field)[0]
#     return False, field
