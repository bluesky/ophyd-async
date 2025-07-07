"""EPICS Signals over CA or PVA."""

from __future__ import annotations

from enum import Enum

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    SignalBackend,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    get_unique,
)

from ._util import EpicsSignalBackend, get_pv_basename_and_field


class EpicsProtocol(Enum):
    CA = "ca"
    PVA = "pva"


_default_epics_protocol = EpicsProtocol.CA


def _make_unavailable_function(error: Exception):
    def transport_not_available(*args, **kwargs):
        raise NotImplementedError("Transport not available") from error

    return transport_not_available


def _make_unavailable_class(error: Exception) -> type[EpicsSignalBackend]:
    class TransportNotAvailable(EpicsSignalBackend):
        __init__ = _make_unavailable_function(error)

    return TransportNotAvailable


try:
    from ._p4p import PvaSignalBackend, pvget_with_timeout
except ImportError as pva_error:
    PvaSignalBackend = _make_unavailable_class(pva_error)
    pvget_with_timeout = _make_unavailable_function(pva_error)
else:
    _default_epics_protocol = EpicsProtocol.PVA

try:
    from ._aioca import CaSignalBackend
except ImportError as ca_error:
    CaSignalBackend = _make_unavailable_class(ca_error)
else:
    _default_epics_protocol = EpicsProtocol.CA


def split_protocol_from_pv(pv: str) -> tuple[EpicsProtocol, str]:
    split = pv.split("://", 1)
    if len(split) > 1:
        # We got something like pva://mydevice, so use specified comms mode
        scheme, pv = split
        protocol = EpicsProtocol(scheme)
    else:
        # No comms mode specified, use the default
        protocol = _default_epics_protocol
    return protocol, pv


def get_signal_backend_type(protocol: EpicsProtocol) -> type[EpicsSignalBackend]:
    match protocol:
        case EpicsProtocol.CA:
            return CaSignalBackend
        case EpicsProtocol.PVA:
            return PvaSignalBackend
    raise TypeError(f"Unsupported protocol: {protocol}")


def _epics_signal_backend(
    datatype: type[SignalDatatypeT] | None, read_pv: str, write_pv: str
) -> SignalBackend[SignalDatatypeT]:
    """Create an epics signal backend."""
    r_protocol, r_pv = split_protocol_from_pv(read_pv)
    w_protocol, w_pv = split_protocol_from_pv(write_pv)
    protocol = get_unique({read_pv: r_protocol, write_pv: w_protocol}, "protocols")
    signal_backend_type = get_signal_backend_type(protocol)
    return signal_backend_type(datatype, r_pv, w_pv)


def epics_signal_rw(
    datatype: type[SignalDatatypeT],
    read_pv: str,
    write_pv: str | None = None,
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = 1,
) -> SignalRW[SignalDatatypeT]:
    """Create a `SignalRW` backed by 1 or 2 EPICS PVs.

    :param datatype: Check that the PV is of this type
    :param read_pv: The PV to read and monitor
    :param write_pv: If given, use this PV to write to, otherwise use read_pv
    :param name: The name of the signal (defaults to empty string)
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    backend = _epics_signal_backend(datatype, read_pv, write_pv or read_pv)
    return SignalRW(backend, name=name, timeout=timeout, attempts=attempts)


def epics_signal_rw_rbv(
    datatype: type[SignalDatatypeT],
    write_pv: str,
    read_suffix: str = "_RBV",
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = 1,
) -> SignalRW[SignalDatatypeT]:
    """Create a `SignalRW` backed by 1 or 2 EPICS PVs, with a suffix on the readback pv.

    :param datatype: Check that the PV is of this type
    :param write_pv: The PV to write to
    :param read_suffix: Append this suffix to the write pv to create the readback pv
    :param name: The name of the signal (defaults to empty string)
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    base_pv, field = get_pv_basename_and_field(write_pv)
    if field is not None:
        read_pv = f"{base_pv}{read_suffix}.{field}"
    else:
        read_pv = f"{write_pv}{read_suffix}"

    return epics_signal_rw(
        datatype, read_pv, write_pv, name, timeout=timeout, attempts=attempts
    )


def epics_signal_r(
    datatype: type[SignalDatatypeT],
    read_pv: str,
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> SignalR[SignalDatatypeT]:
    """Create a `SignalR` backed by 1 EPICS PV.

    :param datatype: Check that the PV is of this type
    :param read_pv: The PV to read from
    :param name: The name of the signal (defaults to empty string)
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    backend = _epics_signal_backend(datatype, read_pv, read_pv)
    return SignalR(backend, name=name, timeout=timeout)


def epics_signal_w(
    datatype: type[SignalDatatypeT],
    write_pv: str,
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = 1,
) -> SignalW[SignalDatatypeT]:
    """Create a `SignalW` backed by 1 EPICS PVs.

    :param datatype: Check that the PV is of this type
    :param write_pv: The PV to write to
    :param name: The name of the signal (defaults to empty string)
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    backend = _epics_signal_backend(datatype, write_pv, write_pv)
    return SignalW(backend, name=name, timeout=timeout, attempts=attempts)


def epics_signal_x(
    write_pv: str, name: str = "", timeout: float = DEFAULT_TIMEOUT
) -> SignalX:
    """Create a `SignalX` backed by 1 EPICS PVs.

    :param write_pv: The PV to write its initial value to on trigger
    :param name: The name of the signal
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    backend = _epics_signal_backend(None, write_pv, write_pv)
    return SignalX(backend, name=name, timeout=timeout)
