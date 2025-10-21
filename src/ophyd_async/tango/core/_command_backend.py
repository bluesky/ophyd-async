from __future__ import annotations

from typing import Any, Generic

from tango import CommandInfo, DeviceProxy

from ophyd_async.core import (
    CommandArguments,
    CommandBackend,
    CommandReturn,
    NotConnectedError,
    CommandR,
    CommandRW,
    CommandW,
    CommandX,
)

from ._tango_transport import (
    CommandProxy,
    CommandProxyReadCharacter,
    get_command_character,
    get_tango_trl,
    make_converter,
)


class TangoCommandBackend(CommandBackend[CommandArguments, CommandReturn], Generic[CommandArguments, CommandReturn]):
    """Tango backend that invokes a Tango command via CommandProxy.

    Parameters
    ----------
    command_trl:
        Full Tango resource locator to the command, e.g.
        "tango://host:port/device/CommandName" or "device/CommandName".
    datatype:
        Optional Python type used to specialize conversions (e.g. StrictEnum for
        DevEnum input). If not given, default conversion is used.
    device_proxy:
        Optional already-created DeviceProxy to use.
    """

    def __init__(
        self,
        command_trl: str,
        *,
        datatype: type[Any] | None = None,
        device_proxy: DeviceProxy | None = None,
    ) -> None:
        self._command_trl = command_trl
        self._datatype = datatype
        self._device_proxy = device_proxy
        self._proxy: CommandProxy | None = None
        self._config: CommandInfo | None = None
        self._character: CommandProxyReadCharacter | None = None

    async def connect(self, timeout: float) -> None:
        if not self._command_trl:
            raise RuntimeError(f"TRL not set for {self}")
        try:
            proxy = await get_tango_trl(self._command_trl, self._device_proxy, timeout)
            # Ensure it is a CommandProxy
            if not isinstance(proxy, CommandProxy):
                raise NotConnectedError(f"{self._command_trl} is not a Tango Command")
            await proxy.connect()
            config: CommandInfo = await proxy.get_config()
            converter = make_converter(config, self._datatype)
            proxy.set_converter(converter)
            self._proxy = proxy
            self._config = config
            self._character = get_command_character(config)
        except TimeoutError as exc:
            raise NotConnectedError(f"tango://{self._command_trl}") from exc

    async def call(
        self, *args: CommandArguments.args, **kwargs: CommandArguments.kwargs
    ) -> CommandReturn:
        proxy = self._proxy
        if proxy is None or self._config is None or self._character is None:
            raise NotConnectedError(f"Not connected to {self._command_trl}")

        if kwargs:
            raise TypeError("Tango commands do not support keyword arguments")

        # Determine input value based on command signature
        value: Any | None
        if self._character in (CommandProxyReadCharacter.WRITE, CommandProxyReadCharacter.READ_WRITE):
            if len(args) != 1:
                raise TypeError("This Tango command requires exactly one positional argument")
            value = args[0]
        else:
            if len(args) != 0:
                raise TypeError("This Tango command does not take any arguments")
            value = None

        await proxy.put(value, wait=True, timeout=None)

        # Decide what to return based on command character
        if self._character in (CommandProxyReadCharacter.READ, CommandProxyReadCharacter.READ_WRITE):
            # Command has an output value
            result = await proxy.get()
            return result  # type: ignore[return-value]
        else:
            # WRITE/EXECUTE return no value
            return None  # type: ignore[return-value]


def tango_command_rw(
    command_trl: str,
    *,
    datatype: type[Any] | None = None,
    name: str = "",
) -> CommandRW:
    """Create a CommandRW backed by a Tango command.

    Parameters
    ----------
    command_trl:
        Full Tango resource locator for the command (e.g. "device/echo").
    datatype:
        Optional Python type to guide conversion (e.g. a StrictEnum for DevEnum).
    name:
        Optional name for the command device.
    """
    backend = TangoCommandBackend(command_trl, datatype=datatype)
    return CommandRW(backend=backend, name=name)



def tango_command_r(
    datatype: type[Any],
    command_trl: str,
    *,
    name: str = "",
) -> CommandR:
    """Create a CommandR (no input, returns a value) backed by a Tango command.

    Parameters
    ----------
    datatype:
        Expected return datatype; may be used for conversion (e.g. enums).
    command_trl:
        Full Tango resource locator for the command.
    name:
        Optional name for the command device.
    """
    backend = TangoCommandBackend(command_trl, datatype=datatype)
    return CommandR(backend=backend, name=name)



def tango_command_w(
    datatype: type[Any],
    command_trl: str,
    *,
    name: str = "",
) -> CommandW:
    """Create a CommandW (input only, no return) backed by a Tango command.

    Parameters
    ----------
    datatype:
        Expected input datatype; may be used for conversion (e.g. enums).
    command_trl:
        Full Tango resource locator for the command.
    name:
        Optional name for the command device.
    """
    backend = TangoCommandBackend(command_trl, datatype=datatype)
    return CommandW(backend=backend, name=name)



def tango_command_x(
    command_trl: str,
    *,
    name: str = "",
) -> CommandX:
    """Create a CommandX (no input, no return) backed by a Tango command.

    Parameters
    ----------
    command_trl:
        Full Tango resource locator for the command.
    name:
        Optional name for the command device.
    """
    backend = TangoCommandBackend(command_trl)
    return CommandX(backend=backend, name=name)
