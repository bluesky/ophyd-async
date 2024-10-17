from __future__ import annotations

from collections.abc import Callable, Iterator


class DeviceConnector:
    async def connect(
        self,
        children: Iterator[tuple[str, Device]],
        mock: bool,
        timeout: float,
        force_reconnect: bool,
    ): ...


class FillingDeviceConnector:
    def __init__(self, signal_backend_cls: type): ...
    def fill(self, device: Device):
        if isinstance(child, Device):
            connector = type(self)(self.signal_backend_cls)
            child = device_cls(connector)


class EpicsPrefixDeviceConnector(FillingDeviceConnector) ...

class PviDeviceConnector(FillingDeviceConnector):
    def __init__(self, prefix: str = ""):
        self.prefix = prefix
        super().__init__(PvaSignalBackend)

    async def connect(
        self,
        children: Iterator[tuple[str, Device]],
        mock: bool,
        timeout: float,
        force_reconnect: bool,
    ): ...


class TangoDeviceConnector(FillingDeviceConnector):
    def __init__(self, trl: str = ""):
        self.trl = trl
        super().__init__(TangoSignalBackend)

    async def connect(
        self,
        children: Iterator[tuple[str, Device]],
        mock: bool,
        timeout: float,
        force_reconnect: bool,
    ): ...


class Device:
    def __init__(self, connector: DeviceConnector | None):
        self._connector = connector or DeviceConnector()

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool):
        if not "cached":
            await self._connector.connect(
                self.children(), mock, timeout, force_reconnect
            )

    def children(self) -> Iterator[tuple[str, Device]]:
        for name, value in self.__dict__.items():
            if isinstance(value, Device):
                yield name, value


class FastCsDevice(Device):
    def __init__(self, connector: FillingDeviceConnector):
        connector.fill(self)
        super().__init__(connector)


class PandaSeq(Device):
    active: SignalRW[int]


class PandaHdfDevice:
    def __init__(self, uri: str):
        connector = PviDeviceConnector(uri) if "epics" else TangoDeviceConnector(uri)
        connector.fill(self)
        writer = HdfWriter(self.pcap)
        super().__init__(writer, connector)
