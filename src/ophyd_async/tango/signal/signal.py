"""Tango Signals over Pytango"""

from __future__ import annotations

from typing import Optional, Type, Union
from tango.asyncio import DeviceProxy
from tango import DeviceProxy as SyncDeviceProxy
from tango import AttrWriteType, CmdArgType


from ophyd_async.core import SignalR, SignalX, T

from ophyd_async.tango._backend import TangoTransport, TangoSignalRW, TangoSignalW, TangoSignalBackend

__all__ = ("tango_signal_rw",
           "tango_signal_r",
           "tango_signal_w",
           "tango_signal_x",
           "tango_signal_auto")


# --------------------------------------------------------------------
def tango_signal_rw(datatype: Type[T],
                    read_trl: str,
                    write_trl: Optional[str] = None,
                    device_proxy: Optional[DeviceProxy] = None
                    ) -> TangoSignalRW[T]:
    """Create a `SignalRW` backed by 1 or 2 Tango Attribute/Command

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    read_trl:
        The Attribute/Command to read and monitor
    write_trl:
        If given, use this Attribute/Command to write to, otherwise use read_trl
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend = TangoTransport(datatype, read_trl, write_trl or read_trl, device_proxy)
    return TangoSignalRW(backend)


# --------------------------------------------------------------------
def tango_signal_r(datatype: Type[T],
                   read_trl: str,
                   device_proxy: Optional[DeviceProxy] = None
                   ) -> SignalR[T]:
    """Create a `SignalR` backed by 1 Tango Attribute/Command

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    read_trl:
        The Attribute/Command to read and monitor
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend = TangoTransport(datatype, read_trl, read_trl, device_proxy)
    return SignalR(backend)


# --------------------------------------------------------------------
def tango_signal_w(datatype: Type[T],
                   write_trl: str,
                   device_proxy: Optional[DeviceProxy] = None
                   ) -> TangoSignalW[T]:
    """Create a `TangoSignalW` backed by 1 Tango Attribute/Command

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    write_trl:
        The Attribute/Command to write to
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend = TangoTransport(datatype, write_trl, write_trl, device_proxy)
    return TangoSignalW(backend)


# --------------------------------------------------------------------
def tango_signal_x(write_trl: str,
                   device_proxy: Optional[DeviceProxy] = None
                   ) -> SignalX:
    """Create a `SignalX` backed by 1 Tango Attribute/Command

    Parameters
    ----------
    write_trl:
        The Attribute/Command to write its initial value to on execute
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend: TangoSignalBackend = TangoTransport(None, write_trl, write_trl, device_proxy)
    return SignalX(backend)


# --------------------------------------------------------------------
def tango_signal_auto(datatype: Type[T], full_trl: str, device_proxy: Optional[DeviceProxy] = None) -> \
        Union[TangoSignalW, SignalX, SignalR, TangoSignalRW]:
    backend: TangoSignalBackend = TangoTransport(datatype, full_trl, full_trl, device_proxy)

    device_trl, tr_name = full_trl.rsplit('/', 1)
    device_proxy = SyncDeviceProxy(device_trl)
    if tr_name in device_proxy.get_attribute_list():
        config = device_proxy.get_attribute_config(tr_name)
        if config.writable in [AttrWriteType.READ_WRITE, AttrWriteType.READ_WITH_WRITE]:
            return TangoSignalRW(backend)
        elif config.writable == AttrWriteType.READ:
            return SignalR(backend)
        else:
            return TangoSignalW(backend)

    if tr_name in device_proxy.get_command_list():
        config = device_proxy.get_command_config(tr_name)
        if config.in_type == CmdArgType.DevVoid:
            return SignalX(backend)
        elif config.out_type != CmdArgType.DevVoid:
            return TangoSignalRW(backend)
        else:
            return SignalR(backend)

    if tr_name in device_proxy.get_pipe_list():
        raise NotImplemented("Pipes are not supported")

    raise RuntimeError(f"Cannot find {tr_name} in {device_trl}")
