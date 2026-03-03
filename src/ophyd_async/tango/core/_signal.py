"""Tango Signals over Pytango."""

from __future__ import annotations

import logging

from tango import (
    AttrWriteType,
    DeviceProxy,
)
from tango.asyncio import DeviceProxy as AsyncDeviceProxy

from ophyd_async.core import (
    Command,
    DEFAULT_TIMEOUT,
    Signal,
    SignalDatatype,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
)

from ._tango_transport import (
    CommandProxyReadCharacter,
    TangoSignalBackend,
    get_command_character,
    get_python_type,
)
from ._utils import get_device_trl_and_attr

logger = logging.getLogger("ophyd_async")


def make_backend(
    datatype: type[SignalDatatypeT] | None,
    read_trl: str = "",
    write_trl: str = "",
) -> TangoSignalBackend:
    return TangoSignalBackend(datatype, read_trl, write_trl)


def tango_signal_rw(
    datatype: type[SignalDatatypeT],
    read_trl: str,
    write_trl: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalRW[SignalDatatypeT]:
    """Create a `SignalRW` backed by 1 or 2 Tango Attribute/Command.

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    read_trl:
        The Attribute/Command to read and monitor
    write_trl:
        If given, use this Attribute/Command to write to, otherwise use read_trl
    timeout:
        The timeout for the read and write operations
    name:
        The name of the Signal

    """
    backend = make_backend(datatype, read_trl, write_trl or read_trl)
    return SignalRW(backend, timeout=timeout, name=name)


def tango_signal_r(
    datatype: type[SignalDatatypeT],
    read_trl: str,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalR[SignalDatatypeT]:
    """Create a `SignalR` backed by 1 Tango Attribute/Command.

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    read_trl:
        The Attribute/Command to read and monitor
    timeout:
        The timeout for the read operation
    name:
        The name of the Signal

    """
    backend = make_backend(datatype, read_trl, read_trl)
    return SignalR(backend, timeout=timeout, name=name)


def tango_signal_w(
    datatype: type[SignalDatatypeT],
    write_trl: str,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalW[SignalDatatypeT]:
    """Create a `SignalW` backed by 1 Tango Attribute/Command.

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    write_trl:
        The Attribute/Command to write to
    timeout:
        The timeout for the write operation
    name:
        The name of the Signal

    """
    backend = make_backend(datatype, write_trl, write_trl)
    return SignalW(backend, timeout=timeout, name=name)


def tango_signal_x(
    write_trl: str,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalX:
    """Create a `SignalX` backed by 1 Tango Attribute/Command.

    Parameters
    ----------
    write_trl:
        The Attribute/Command to write its initial value to on execute
    timeout:
        The timeout for the command operation
    name:
        The name of the Signal

    """
    backend = make_backend(None, write_trl, write_trl)
    return SignalX(backend, timeout=timeout, name=name)


async def infer_python_type(
    trl: str = "", proxy: DeviceProxy | None = None
) -> type[SignalDatatype] | None:
    """Infers the python type from the TRL."""
    # TODO: work out if this is still needed
    device_trl, tr_name = get_device_trl_and_attr(trl)
    if proxy is None:
        dev_proxy = await AsyncDeviceProxy(device_trl)  # type: ignore
    else:
        dev_proxy = proxy

    if tr_name in dev_proxy.get_command_list():
        # A Device proxy instantiated by awaiting
        # tango.asyncio.DeviceProxy is typed the same as the sync
        # despite having awaitable methods.
        config = await dev_proxy.get_command_config(tr_name)  # type: ignore
        py_type = get_python_type(config)
    elif tr_name in dev_proxy.get_attribute_list():
        config = await dev_proxy.get_attribute_config(tr_name)  # type: ignore
        py_type = get_python_type(config)
    else:
        raise RuntimeError(f"Cannot find {tr_name} in {device_trl}")
    return py_type


async def infer_signal_type(
    trl, proxy: DeviceProxy | None = None
) -> type[Signal] | type[Command] | None:
    device_trl, tr_name = get_device_trl_and_attr(trl)
    if proxy is None:
        dev_proxy = await AsyncDeviceProxy(device_trl)  # type: ignore
    else:
        dev_proxy = proxy

    if tr_name not in dev_proxy.get_attribute_list():
        if tr_name not in dev_proxy.get_command_list():
            raise RuntimeError(f"Cannot find {tr_name} in {device_trl}")

    if tr_name in dev_proxy.get_attribute_list():
        config = await dev_proxy.get_attribute_config(tr_name)  # type: ignore
        if config.writable in [AttrWriteType.READ_WRITE, AttrWriteType.READ_WITH_WRITE]:
            return SignalRW
        elif config.writable == AttrWriteType.READ:
            return SignalR
        else:
            return SignalW

    if tr_name in dev_proxy.get_command_list():
        return Command
    raise RuntimeError(f"Unable to infer signal character for {trl}")
