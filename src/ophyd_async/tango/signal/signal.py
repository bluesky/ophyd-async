"""Tango Signals over Pytango"""

from __future__ import annotations

from typing import Optional, Tuple, Type
from tango import DeviceProxy

from ophyd_async.core import (
    SignalBackend,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    T,
)

from .._backend import TangoTransport


def tango_signal_rw(datatype: Type[T],
                    read_pv: str,
                    write_pv: Optional[str] = None,
                    device_proxy: Optional[DeviceProxy] = None
                    ) -> SignalRW[T]:
    """Create a `SignalRW` backed by 1 or 2 EPICS PVs

    Parameters
    ----------
    datatype:
        Check that the PV is of this type
    read_pv:
        The PV to read and monitor
    write_pv:
        If given, use this PV to write to, otherwise use read_pv
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend = TangoTransport(datatype, read_pv, write_pv or read_pv, device_proxy)
    return SignalRW(backend)


def tango_signal_r(datatype: Type[T],
                   read_pv: str,
                   device_proxy: Optional[DeviceProxy] = None
                   ) -> SignalR[T]:
    """Create a `SignalR` backed by 1 EPICS PV

    Parameters
    ----------
    datatype:
        Check that the PV is of this type
    read_pv:
        The PV to read and monitor
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend = TangoTransport(datatype, read_pv, read_pv, device_proxy)
    return SignalR(backend)


def tango_signal_w(datatype: Type[T],
                   write_pv: str,
                   device_proxy: Optional[DeviceProxy] = None
                   ) -> SignalW[T]:
    """Create a `SignalW` backed by 1 EPICS PVs

    Parameters
    ----------
    datatype:
        Check that the PV is of this type
    write_pv:
        The PV to write to
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend = TangoTransport(datatype, write_pv, write_pv, device_proxy)
    return SignalW(backend)


def tango_signal_x(write_pv: str,
                   device_proxy: Optional[DeviceProxy] = None
                   ) -> SignalX:
    """Create a `SignalX` backed by 1 EPICS PVs

    Parameters
    ----------
    write_pv:
        The PV to write its initial value to on execute
    device_proxy:
        If given, this DeviceProxy will be used
    """
    backend: SignalBackend = TangoTransport(None, write_pv, write_pv, device_proxy)
    return SignalX(backend)
