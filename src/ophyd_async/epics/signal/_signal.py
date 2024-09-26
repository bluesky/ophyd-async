"""EPICS Signals over CA or PVA"""

from __future__ import annotations

from enum import Enum

from ophyd_async.core import (
    SignalConnector,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    get_unique,
)


def _make_unavailable_class(error: Exception) -> type:
    class TransportNotAvailable:
        def __init__(*args, **kwargs):
            raise NotImplementedError("Transport not available") from error

    return TransportNotAvailable


class EpicsProtocol(Enum):
    CA = "ca"
    PVA = "pva"


_default_epics_protocol = EpicsProtocol.CA

try:
    from ._p4p import PvaSignalConnector
except ImportError as pva_error:
    PvaSignalConnector = _make_unavailable_class(pva_error)
else:
    _default_epics_protocol = EpicsProtocol.PVA

try:
    from ._aioca import CaSignalConnector
except ImportError as ca_error:
    CaSignalConnector = _make_unavailable_class(ca_error)
else:
    _default_epics_protocol = EpicsProtocol.CA


def _protocol_pv(pv: str) -> tuple[EpicsProtocol, str]:
    split = pv.split("://", 1)
    if len(split) > 1:
        # We got something like pva://mydevice, so use specified comms mode
        scheme, pv = split
        protocol = EpicsProtocol(scheme)
    else:
        # No comms mode specified, use the default
        protocol = _default_epics_protocol
    return protocol, pv


def _epics_signal_connector(
    datatype: type[SignalDatatypeT] | None, read_pv: str, write_pv: str
) -> SignalConnector[SignalDatatypeT]:
    """Create an epics signal connector."""
    r_protocol, r_pv = _protocol_pv(read_pv)
    w_protocol, w_pv = _protocol_pv(write_pv)
    protocol = get_unique({read_pv: r_protocol, write_pv: w_protocol}, "protocols")
    match protocol:
        case EpicsProtocol.CA:
            return CaSignalConnector(datatype, r_pv, w_pv)
        case EpicsProtocol.PVA:
            return PvaSignalConnector(datatype, r_pv, w_pv)


def epics_signal_rw(
    datatype: type[SignalDatatypeT],
    read_pv: str,
    write_pv: str | None = None,
    name: str = "",
) -> SignalRW[SignalDatatypeT]:
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
    connector = _epics_signal_connector(datatype, read_pv, write_pv or read_pv)
    return SignalRW(connector, name=name)


def epics_signal_rw_rbv(
    datatype: type[SignalDatatypeT],
    write_pv: str,
    read_suffix: str = "_RBV",
    name: str = "",
) -> SignalRW[SignalDatatypeT]:
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


def epics_signal_r(
    datatype: type[SignalDatatypeT], read_pv: str, name: str = ""
) -> SignalR[SignalDatatypeT]:
    """Create a `SignalR` backed by 1 EPICS PV

    Parameters
    ----------
    datatype
        Check that the PV is of this type
    read_pv:
        The PV to read and monitor
    """
    connector = _epics_signal_connector(datatype, read_pv, read_pv)
    return SignalR(connector, name=name)


def epics_signal_w(
    datatype: type[SignalDatatypeT], write_pv: str, name: str = ""
) -> SignalW[SignalDatatypeT]:
    """Create a `SignalW` backed by 1 EPICS PVs

    Parameters
    ----------
    datatype:
        Check that the PV is of this type
    write_pv:
        The PV to write to
    """
    connector = _epics_signal_connector(datatype, write_pv, write_pv)
    return SignalW(connector, name=name)


def epics_signal_x(write_pv: str, name: str = "") -> SignalX:
    """Create a `SignalX` backed by 1 EPICS PVs

    Parameters
    ----------
    write_pv:
        The PV to write its initial value to on trigger
    """
    connector = _epics_signal_connector(None, write_pv, write_pv)
    return SignalX(connector, name=name)
