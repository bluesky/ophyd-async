"""Tango Signals over Pytango"""

from __future__ import annotations

from typing import Optional, Type
from tango import DeviceProxy

from ophyd_async.core import SignalR, SignalX, T

from ophyd_async.tango._backend import TangoTransport, TangoSignalRW, TangoSignalW, TangoSignalBackend

__all__ = ("tango_signal_rw",
           "tango_signal_r",
           "tango_signal_w",
           "tango_signal_x")


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
    """Create a `SignalW` backed by 1 Tango Attribute/Command

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
