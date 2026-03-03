from __future__ import annotations

from typing import cast

from tango import CommandInfo, DeviceProxy

from ophyd_async.core import (
    Command,
    CommandBackend,
    CommandConnector,
    DEFAULT_TIMEOUT,
    NotConnectedError,
)

from ._converters import (
    TangoConverter,
)

from ._tango_transport import(
    CommandProxy,
    CommandProxyReadCharacter,
    get_tango_trl,
    make_converter,
    get_python_type
)

from ophyd_async.core._utils import P, T


class TangoCommandBackend(CommandBackend[P, T]):
    def __init__(self, trl: str, device_proxy: DeviceProxy | None = None, datatype: type[T] | None = None):
        self._trl = trl
        self.device_proxy = device_proxy
        self.datatype: type[T] | None = datatype
        self._proxy: CommandProxy | None = None
        self._config: CommandInfo | None = None
        self._character: CommandProxyReadCharacter | None = None
        self._converter: TangoConverter | None = None

    def get_return_type(self) -> T | None:
        return get_python_type(self._config)

    def set_trl(self, trl: str) -> None:
        self._trl = trl

    def source(self, name: str) -> str:  # noqa: ARG002
        return self._trl

    async def connect(self, timeout: float) -> None:
        tp = await get_tango_trl(self._trl, self.device_proxy, timeout)
        if not isinstance(tp, CommandProxy):
            raise NotConnectedError(f"{self._trl} is not a Tango Command")
        self._proxy = tp
        await self._proxy.connect()
        self._config = await self._proxy.get_config()
        # Configure converters and character
        self._converter = make_converter(self._config, self.datatype)
        self._proxy.set_converter(self._converter)
        self._character = self._proxy._read_character  # set by connect()
        self.datatype = self.get_return_type()

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
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
        value: T | None = args[0] if args else None

        # Execute
        await self._proxy.put(value, timeout=None)

        # Decide what to return
        # If command has an output (READ or READ_WRITE), return the last reading's value
        # Otherwise return None
        if self._character in (
            CommandProxyReadCharacter.READ,
            CommandProxyReadCharacter.READ_WRITE,
        ):
            reading = await self._proxy.get_reading()
            return cast(T, reading["value"])
        return cast(T, None)

class TangoCommandConnector(CommandConnector):
    pass

def tango_command(
    trl: str,
    device_proxy: DeviceProxy | None = None,
    datatype: type[T] | None = None,
    *,
    timeout: float | None = DEFAULT_TIMEOUT,
    name: str = "",
) -> Command[P, T]:
    backend: TangoCommandBackend[P, T] = TangoCommandBackend(trl, device_proxy, datatype)
    return Command(backend, timeout=timeout, name=name)
