"""EPICS Signals over CA or PVA."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from enum import Enum

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    CommandBackend,
    SignalBackend,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    TriggerableCommand,
    get_unique,
)

from ._util import EpicsOptions, EpicsSignalBackend, get_pv_basename_and_field


class EpicsProtocol(Enum):
    CA = "ca"
    PVA = "pva"


_default_epics_protocol = EpicsProtocol.CA


def _make_unavailable_function(protocol: str, error: Exception):
    def transport_not_available(*args, **kwargs):
        msg = (
            f"Protocol {protocol} not available, "
            f"did you `pip install ophyd_async[{protocol}]`?"
        )
        raise NotImplementedError(msg) from error

    return transport_not_available


def _make_unavailable_class(
    protocol: str, error: Exception
) -> type[EpicsSignalBackend]:
    class TransportNotAvailable(EpicsSignalBackend):
        __init__ = _make_unavailable_function(protocol, error)

    return TransportNotAvailable


try:
    from ._p4p import PvaCommandBackend, PvaSignalBackend, pvget_with_timeout
except ImportError as pva_error:
    PvaSignalBackend = _make_unavailable_class("pva", pva_error)
    PvaCommandBackend = _make_unavailable_class("pva", pva_error)
    pvget_with_timeout = _make_unavailable_function("pva", pva_error)
else:
    _default_epics_protocol = EpicsProtocol.PVA

try:
    from ._aioca import CaCommandBackend, CaSignalBackend
except ImportError as ca_error:
    CaSignalBackend = _make_unavailable_class("ca", ca_error)
    CaCommandBackend = _make_unavailable_class("ca", ca_error)
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
    datatype: type[SignalDatatypeT] | None,
    read_pv: str,
    write_pv: str,
    options: EpicsOptions | None = None,
) -> SignalBackend[SignalDatatypeT]:
    """Create an epics signal backend."""
    r_protocol, r_pv = split_protocol_from_pv(read_pv)
    w_protocol, w_pv = split_protocol_from_pv(write_pv)
    protocol = get_unique({read_pv: r_protocol, write_pv: w_protocol}, "protocols")

    signal_backend_type = get_signal_backend_type(protocol)
    return signal_backend_type(datatype, r_pv, w_pv, options)


def epics_signal_rw(
    datatype: type[SignalDatatypeT],
    read_pv: str,
    write_pv: str | None = None,
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = 1,
    wait: bool | Callable[[SignalDatatypeT], bool] = True,
) -> SignalRW[SignalDatatypeT]:
    """Create a `SignalRW` backed by 1 or 2 EPICS PVs.

    :param datatype: Check that the PV is of this type
    :param read_pv: The PV to read and monitor
    :param write_pv: If given, use this PV to write to, otherwise use read_pv
    :param name: The name of the signal (defaults to empty string)
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    backend = _epics_signal_backend(
        datatype, read_pv, write_pv or read_pv, EpicsOptions(wait=wait)
    )
    return SignalRW(backend, name=name, timeout=timeout, attempts=attempts)


def epics_signal_rw_rbv(
    datatype: type[SignalDatatypeT],
    write_pv: str,
    read_suffix: str = "_RBV",
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = 1,
    wait: bool | Callable[[SignalDatatypeT], bool] = True,
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
        datatype, read_pv, write_pv, name, timeout=timeout, attempts=attempts, wait=wait
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
    wait: bool | Callable[[SignalDatatypeT], bool] = True,
) -> SignalW[SignalDatatypeT]:
    """Create a `SignalW` backed by 1 EPICS PVs.

    :param datatype: Check that the PV is of this type
    :param write_pv: The PV to write to
    :param name: The name of the signal (defaults to empty string)
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    backend = _epics_signal_backend(
        datatype, write_pv, write_pv, EpicsOptions(wait=wait)
    )
    return SignalW(backend, name=name, timeout=timeout, attempts=attempts)


def get_command_backend_type(protocol: EpicsProtocol) -> type:
    """Return the EPICS command backend class for the given protocol."""
    match protocol:
        case EpicsProtocol.CA:
            return CaCommandBackend
        case EpicsProtocol.PVA:
            return PvaCommandBackend
    raise TypeError(f"Unsupported protocol: {protocol}")


def epics_triggerable_command(
    write_pv: str,
    execute_value: int = 1,
    name: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> TriggerableCommand:
    """Create a [](#TriggerableCommand) backed by an EPICS PV.

    On trigger, writes `execute_value` (default 1) to `write_pv`.

    :param write_pv: The PV to write to when the command is triggered
    :param execute_value: The value to write on trigger (default: 1)
    :param name: The name of the command
    :param timeout: A timeout to be used when triggering this command
    """
    protocol, pv = split_protocol_from_pv(write_pv)
    backend: CommandBackend[[], None] = get_command_backend_type(protocol)(
        pv, execute_value
    )
    return TriggerableCommand(backend, name=name, timeout=timeout)


def epics_signal_x(
    write_pv: str, name: str = "", timeout: float = DEFAULT_TIMEOUT
) -> SignalX:
    """Create a `SignalX` backed by 1 EPICS PVs.

    ```{version-deprecated} 0.19
    Use [](#epics_triggerable_command) instead.
    ```

    :param write_pv: The PV to write its initial value to on trigger
    :param name: The name of the signal
    :param timeout: A timeout to be used when reading (not connecting) this signal
    """
    warnings.warn(
        "epics_signal_x is deprecated, use epics_triggerable_command instead",
        DeprecationWarning,
        stacklevel=2,
    )
    backend = _epics_signal_backend(None, write_pv, write_pv)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return SignalX(backend, name=name, timeout=timeout)
