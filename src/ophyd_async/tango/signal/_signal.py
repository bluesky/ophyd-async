"""Tango Signals over Pytango"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Optional, Type, Union

import numpy.typing as npt

from ophyd_async.core import DEFAULT_TIMEOUT, SignalR, SignalRW, SignalW, SignalX, T
from ophyd_async.tango.signal._tango_transport import (
    TangoSignalBackend,
    get_python_type,
)
from tango import AttrDataFormat, AttrWriteType, CmdArgType, DevState
from tango import DeviceProxy as SyncDeviceProxy
from tango.asyncio import DeviceProxy


def make_backend(
    datatype: Optional[Type[T]],
    read_trl: str,
    write_trl: str,
    device_proxy: Optional[DeviceProxy] = None,
) -> TangoSignalBackend:
    return TangoSignalBackend(datatype, read_trl, write_trl, device_proxy)


# --------------------------------------------------------------------
def tango_signal_rw(
    datatype: Optional[Type[T]] = None,
    *,
    read_trl: str,
    write_trl: Optional[str] = None,
    device_proxy: Optional[DeviceProxy] = None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalRW[T]:
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
    timeout:
        The timeout for the read and write operations
    name:
        The name of the Signal
    """
    if datatype is None:
        datatype = infer_python_type(read_trl)
    backend = make_backend(datatype, read_trl, write_trl or read_trl, device_proxy)
    return SignalRW(backend, timeout=timeout, name=name)


# --------------------------------------------------------------------
def tango_signal_r(
    datatype: Optional[Type[T]] = None,
    *,
    read_trl: str,
    device_proxy: Optional[DeviceProxy] = None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
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
    timeout:
        The timeout for the read operation
    name:
        The name of the Signal
    """
    if datatype is None:
        datatype = infer_python_type(read_trl)
    backend = make_backend(datatype, read_trl, read_trl, device_proxy)
    return SignalR(backend, timeout=timeout, name=name)


# --------------------------------------------------------------------
def tango_signal_w(
    datatype: Optional[Type[T]] = None,
    *,
    write_trl: str,
    device_proxy: Optional[DeviceProxy] = None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalW[T]:
    """Create a `TangoSignalW` backed by 1 Tango Attribute/Command

    Parameters
    ----------
    datatype:
        Check that the Attribute/Command is of this type
    write_trl:
        The Attribute/Command to write to
    device_proxy:
        If given, this DeviceProxy will be used
    timeout:
        The timeout for the write operation
    name:
        The name of the Signal
    """
    if datatype is None:
        datatype = infer_python_type(write_trl)
    backend = make_backend(datatype, write_trl, write_trl, device_proxy)
    return SignalW(backend, timeout=timeout, name=name)


# --------------------------------------------------------------------
def tango_signal_x(
    write_trl: str,
    device_proxy: Optional[DeviceProxy] = None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalX:
    """Create a `SignalX` backed by 1 Tango Attribute/Command

    Parameters
    ----------
    write_trl:
        The Attribute/Command to write its initial value to on execute
    device_proxy:
        If given, this DeviceProxy will be used
    timeout:
        The timeout for the command operation
    name:
        The name of the Signal
    """
    backend = make_backend(None, write_trl, write_trl, device_proxy)
    return SignalX(backend, timeout=timeout, name=name)


# --------------------------------------------------------------------
def tango_signal_auto(
    datatype: Optional[Type[T]] = None,
    *,
    trl: str,
    device_proxy: Optional[DeviceProxy] = None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> Union[SignalW, SignalX, SignalR, SignalRW]:
    if datatype is None:
        datatype = infer_python_type(trl)
    backend = make_backend(datatype, trl, trl, device_proxy)
    signal = infer_signal_frontend(trl, name, timeout)
    signal._backend = backend  # noqa: SLF001

    return signal


# --------------------------------------------------------------------
def infer_python_type(trl: str) -> Type[T]:
    device_trl, tr_name = trl.rsplit("/", 1)
    syn_proxy = SyncDeviceProxy(device_trl)

    if tr_name in syn_proxy.get_command_list():
        config = syn_proxy.get_command_config(tr_name)
        isarray, py_type, _ = get_python_type(config.in_type)
    elif tr_name in syn_proxy.get_attribute_list():
        config = syn_proxy.get_attribute_config(tr_name)
        isarray, py_type, _ = get_python_type(config.data_type)
        if py_type is Enum:
            enum_dict = {label: i for i, label in enumerate(config.enum_labels)}
            py_type = IntEnum("TangoEnum", enum_dict)
        if config.data_format in [AttrDataFormat.SPECTRUM, AttrDataFormat.IMAGE]:
            isarray = True
    else:
        raise RuntimeError(f"Cannot find {tr_name} in {device_trl}")

    if py_type is CmdArgType.DevState:
        py_type = DevState

    return npt.NDArray[py_type] if isarray else py_type


# --------------------------------------------------------------------
def infer_signal_frontend(trl, name: str = "", timeout: float = DEFAULT_TIMEOUT):
    device_trl, tr_name = trl.rsplit("/", 1)
    proxy = SyncDeviceProxy(device_trl)

    if tr_name in proxy.get_pipe_list():
        raise NotImplementedError("Pipes are not supported")

    if tr_name not in proxy.get_attribute_list():
        if tr_name not in proxy.get_command_list():
            raise RuntimeError(f"Cannot find {tr_name} in {device_trl}")

    if tr_name in proxy.get_attribute_list():
        config = proxy.get_attribute_config(tr_name)
        if config.writable in [AttrWriteType.READ_WRITE, AttrWriteType.READ_WITH_WRITE]:
            return SignalRW(name=name, timeout=timeout)
        elif config.writable == AttrWriteType.READ:
            return SignalR(name=name, timeout=timeout)
        else:
            return SignalW(name=name, timeout=timeout)

    if tr_name in proxy.get_command_list():
        config = proxy.get_command_config(tr_name)
        if config.in_type == CmdArgType.DevVoid:
            return SignalX(name=name, timeout=timeout)
        elif config.out_type != CmdArgType.DevVoid:
            return SignalRW(name=name, timeout=timeout)
