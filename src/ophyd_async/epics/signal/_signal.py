"""EPICS Signals over CA or PVA"""

from __future__ import annotations

from ophyd_async.core import (
    SignalBackend,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    T,
    get_unique,
)

from ._epics_transport import _EpicsTransport

_default_epics_transport = _EpicsTransport.ca


def _transport_pv(pv: str) -> tuple[_EpicsTransport, str]:
    split = pv.split("://", 1)
    if len(split) > 1:
        # We got something like pva://mydevice, so use specified comms mode
        transport_str, pv = split
        transport = _EpicsTransport[transport_str]
    else:
        # No comms mode specified, use the default
        transport = _default_epics_transport
    return transport, pv


def _epics_signal_backend(
    datatype: type[T] | None, read_pv: str, write_pv: str
) -> SignalBackend[T]:
    """Create an epics signal backend."""
    r_transport, r_pv = _transport_pv(read_pv)
    w_transport, w_pv = _transport_pv(write_pv)
    transport = get_unique({read_pv: r_transport, write_pv: w_transport}, "transports")
    return transport.value(datatype, r_pv, w_pv)


def epics_signal_rw(
    datatype: type[T], read_pv: str, write_pv: str | None = None, name: str = ""
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
    """
    backend = _epics_signal_backend(datatype, read_pv, write_pv or read_pv)
    return SignalRW(backend, name=name)


def epics_signal_rw_rbv(
    datatype: type[T], write_pv: str, read_suffix: str = "_RBV", name: str = ""
) -> SignalRW[T]:
    """Create a `SignalRW` backed by 1 or 2 EPICS PVs, with a suffix on the readback pv

    Parameters
    ----------
    datatype:
        Check that the PV is of this type
    write_pv:
        The PV to write to
    read_suffix:
        Append this suffix to the write pv to create the readback pv
    """
    return epics_signal_rw(datatype, f"{write_pv}{read_suffix}", write_pv, name)


def epics_signal_r(datatype: type[T], read_pv: str, name: str = "") -> SignalR[T]:
    """Create a `SignalR` backed by 1 EPICS PV

    Parameters
    ----------
    datatype
        Check that the PV is of this type
    read_pv:
        The PV to read and monitor
    """
    backend = _epics_signal_backend(datatype, read_pv, read_pv)
    return SignalR(backend, name=name)


def epics_signal_w(datatype: type[T], write_pv: str, name: str = "") -> SignalW[T]:
    """Create a `SignalW` backed by 1 EPICS PVs

    Parameters
    ----------
    datatype:
        Check that the PV is of this type
    write_pv:
        The PV to write to
    """
    backend = _epics_signal_backend(datatype, write_pv, write_pv)
    return SignalW(backend, name=name)


def epics_signal_x(write_pv: str, name: str = "") -> SignalX:
    """Create a `SignalX` backed by 1 EPICS PVs

    Parameters
    ----------
    write_pv:
        The PV to write its initial value to on trigger
    """
    backend: SignalBackend = _epics_signal_backend(None, write_pv, write_pv)
    return SignalX(backend, name=name)
