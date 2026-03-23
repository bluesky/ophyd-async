from __future__ import annotations

import inspect
from typing import cast

import numpy as np
from tango import CommandInfo, DeviceProxy

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Array1D,
    AsyncStatus,
    Command,
    CommandBackend,
    NotConnectedError,
    SignalDatatype,
    StrictEnum,
    TriggerableCommand,
)

from ._converters import (
    TangoConverter,
)
from ._tango_transport import (
    CommandProxy,
    get_python_type,
    get_tango_trl,
    make_converter,
)
from ._utils import P, T


class TangoCommandBackend(CommandBackend[P, T]):
    """A backend for executing commands on a Tango device.

    This backend interfaces with a Tango device's command via a Tango `CommandProxy`.
    It handles connection, type conversion, and execution of commands, while enforcing
    Tango's limitations (e.g., no keyword arguments, single positional argument).

    Args:
        call_spec (inspect.Signature): Type signature of the Tango command.
        trl (str): The Tango Resource Locator (TRL) of the command (e.g., `tango://host:port/device/command`).
        device_proxy (DeviceProxy | None): An optional pre-configured Tango
         `DeviceProxy`.
            If provided, it will be used to resolve the TRL.

    Raises:
        TypeError: If `datatype` is `Array1D[np.int8]` (unsupported by Tango).
        NotConnectedError: If the backend fails to connect to the Tango command.
        TypeError: If the Tango command's actual type does not match `datatype`.
    """

    param_types: list[type[SignalDatatype] | None]

    def __init__(
        self,
        call_spec: inspect.Signature | None,
        trl: str = "",
        device_proxy: DeviceProxy | None = None,
    ):
        self.param_types = []
        if call_spec is None:
            datatype = None
            self.param_types = [None]
        else:
            # Extract input parameter types
            input_types = []
            for param in call_spec.parameters.values():
                input_types.append(param.annotation)
            self.param_types = input_types

            # Extract return type
            datatype = call_spec.return_annotation

        if len(self.param_types) > 1:
            raise TypeError(
                "Commands with more than one input parameter are not yet supported."
            )

        self._trl = trl
        self.device_proxy = device_proxy
        self._proxy: CommandProxy | None = None
        self._config: CommandInfo | None = None
        self._converter: TangoConverter | None = None
        self._timeout: float | None = DEFAULT_TIMEOUT

        if datatype == Array1D[np.int8]:
            raise TypeError(
                "Arrays of type np.int8 are not supported by tango."
                " Use np.uint8 or np.int16."
            )

        super().__init__(datatype=datatype)

    def set_timeout(self, timeout: float | None) -> None:
        self._timeout = timeout

    def set_trl(self, trl: str) -> None:
        self._trl = trl

    def source(self, name: str) -> str:  # noqa: ARG002
        return self._trl

    async def connect(self, timeout: float) -> None:
        command_proxy = await get_tango_trl(self._trl, self.device_proxy, timeout)
        if not isinstance(command_proxy, CommandProxy):
            raise NotConnectedError(f"{self._trl} is not a Tango Command")
        self._proxy = command_proxy
        await self._proxy.connect()
        self._config = await self._proxy.get_config()
        # Configure converters and character
        self._converter = make_converter(self._config, self.datatype)
        self._proxy.set_converter(self._converter)

        param = get_python_type(self._config, return_input_type=True)
        if self.param_types[0] is not None:
            if param is StrictEnum:
                pass
            elif param != self.param_types[0]:
                raise TypeError(
                    f"Tango command {self._trl} has input parameter of"
                    f" type {param}, not {self.param_types[0]}"
                )
        datatype = get_python_type(self._config)
        # Skip type validation on connect if self.datatype is not specified
        if self.datatype is None:
            return
        if datatype is StrictEnum:
            pass
        elif datatype != self.datatype:
            raise TypeError(
                f"Tango command {self._trl} has type {datatype}, not {self.datatype}"
            )

    @AsyncStatus.wrap
    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore[override]
        if kwargs:
            raise TypeError("Tango commands do not support keyword arguments")
        if self._proxy is None or self._config is None:
            raise NotConnectedError(f"Not connected to {self._trl}")

        # Tango commands accept either no value or a single value.
        # This limitation may be removed in future Tango releases if
        # multi-parameter commands are implemented
        if len(args) > 1:
            raise TypeError(
                f"{self._trl} expected 0 or 1 positional argument, got {len(args)}"
            )
        value: T | None = cast("T | None", args[0]) if args else None

        reply = await self._proxy.put(value)
        return cast(T, reply)

def tango_command(
    call_spec: inspect.Signature,
    trl: str,
    device_proxy: DeviceProxy | None = None,
    *,
    timeout: float | None = DEFAULT_TIMEOUT,
    name: str = "",
    triggerable: bool = False,
) -> Command[P, object] | TriggerableCommand:
    """Factory function to create a Tango-backed command.

    Creates a `Command` or `TriggerableCommand` that executes a Tango device command.
    The command can be configured to accept arguments and return a typed result.

    Args:
        call_spec (inspect.Signature): Callable signature of the tango command.
        trl (str): The Tango Resource Locator (TRL) of the command (e.g.,
         `tango://host:port/device/command`).
        device_proxy (DeviceProxy | None): An optional pre-configured Tango
         `DeviceProxy`.
            If provided, it will be used to resolve the TRL.
        timeout (float | None): Timeout (in seconds) for connecting to the Tango
         device.
            Defaults to `DEFAULT_TIMEOUT`.
        name (str): Optional name for the command (used in logging and debugging).
        triggerable (bool): If `True`, returns a command with a trigger method
        (no arguments, returns `None`).
            Defaults to `False`.

    Returns:
        Command[P, T] | TriggerableCommand: A command instance that
         can be executed asynchronously.

    """
    backend: TangoCommandBackend[P, object] = TangoCommandBackend(
        call_spec, trl, device_proxy
    )
    if triggerable:
        return TriggerableCommand(
            cast("CommandBackend[[], None]", backend),
            timeout=timeout,
            name=name,
        )
    else:
        return Command(backend, timeout=timeout, name=name)
