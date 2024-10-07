"""Tango Signals over Pytango"""

from __future__ import annotations

from enum import Enum, IntEnum

import numpy.typing as npt

from ophyd_async.core import DEFAULT_TIMEOUT, SignalR, SignalRW, SignalW, SignalX, T
from ophyd_async.tango.signal._tango_transport import (
    TangoSignalBackend,
    get_python_type,
)
from tango import AttrDataFormat, AttrWriteType, CmdArgType, DeviceProxy, DevState
from tango.asyncio import DeviceProxy as AsyncDeviceProxy


def make_backend(
    datatype: type[T] | None,
    read_trl: str = "",
    write_trl: str = "",
    device_proxy: DeviceProxy | None = None,
) -> TangoSignalBackend:
    return TangoSignalBackend(datatype, read_trl, write_trl, device_proxy)


def tango_signal_rw(
    datatype: type[T],
    read_trl: str,
    write_trl: str = "",
    device_proxy: DeviceProxy | None = None,
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
    backend = make_backend(datatype, read_trl, write_trl or read_trl, device_proxy)
    return SignalRW(backend, timeout=timeout, name=name)


def tango_signal_r(
    datatype: type[T],
    read_trl: str,
    device_proxy: DeviceProxy | None = None,
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
    backend = make_backend(datatype, read_trl, read_trl, device_proxy)
    return SignalR(backend, timeout=timeout, name=name)


def tango_signal_w(
    datatype: type[T],
    write_trl: str,
    device_proxy: DeviceProxy | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalW[T]:
    """Create a `SignalW` backed by 1 Tango Attribute/Command

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
    backend = make_backend(datatype, write_trl, write_trl, device_proxy)
    return SignalW(backend, timeout=timeout, name=name)


def tango_signal_x(
    write_trl: str,
    device_proxy: DeviceProxy | None = None,
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


async def __tango_signal_auto(
    datatype: type[T] | None = None,
    *,
    trl: str,
    device_proxy: DeviceProxy | None,
    timeout: float = DEFAULT_TIMEOUT,
    name: str = "",
) -> SignalW | SignalX | SignalR | SignalRW | None:
    try:
        signal_character = await infer_signal_character(trl, device_proxy)
    except RuntimeError as e:
        if "Commands with different in and out dtypes" in str(e):
            return None
        else:
            raise e

    if datatype is None:
        datatype = await infer_python_type(trl, device_proxy)

    backend = make_backend(datatype, trl, trl, device_proxy)
    if signal_character == "RW":
        return SignalRW(backend=backend, timeout=timeout, name=name)
    if signal_character == "R":
        return SignalR(backend=backend, timeout=timeout, name=name)
    if signal_character == "W":
        return SignalW(backend=backend, timeout=timeout, name=name)
    if signal_character == "X":
        return SignalX(backend=backend, timeout=timeout, name=name)


async def infer_python_type(
    trl: str = "", proxy: DeviceProxy | None = None
) -> object | npt.NDArray | type[DevState] | IntEnum:
    device_trl, tr_name = trl.rsplit("/", 1)
    if proxy is None:
        dev_proxy = await AsyncDeviceProxy(device_trl)
    else:
        dev_proxy = proxy

    if tr_name in dev_proxy.get_command_list():
        config = await dev_proxy.get_command_config(tr_name)
        isarray, py_type, _ = get_python_type(config.in_type)
    elif tr_name in dev_proxy.get_attribute_list():
        config = await dev_proxy.get_attribute_config(tr_name)
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


async def infer_signal_character(trl, proxy: DeviceProxy | None = None) -> str:
    device_trl, tr_name = trl.rsplit("/", 1)
    if proxy is None:
        dev_proxy = await AsyncDeviceProxy(device_trl)
    else:
        dev_proxy = proxy

    if tr_name in dev_proxy.get_pipe_list():
        raise NotImplementedError("Pipes are not supported")

    if tr_name not in dev_proxy.get_attribute_list():
        if tr_name not in dev_proxy.get_command_list():
            raise RuntimeError(f"Cannot find {tr_name} in {device_trl}")

    if tr_name in dev_proxy.get_attribute_list():
        config = await dev_proxy.get_attribute_config(tr_name)
        if config.writable in [AttrWriteType.READ_WRITE, AttrWriteType.READ_WITH_WRITE]:
            return "RW"
        elif config.writable == AttrWriteType.READ:
            return "R"
        else:
            return "W"

    if tr_name in dev_proxy.get_command_list():
        config = await dev_proxy.get_command_config(tr_name)
        if config.in_type == CmdArgType.DevVoid:
            return "X"
        elif config.in_type != config.out_type:
            raise RuntimeError(
                "Commands with different in and out dtypes are not" " supported"
            )
        else:
            return "RW"
    raise RuntimeError(f"Unable to infer signal character for {trl}")
