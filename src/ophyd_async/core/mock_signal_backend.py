import asyncio
from typing import Optional
from unittest.mock import MagicMock

from bluesky.protocols import Descriptor, Reading

from ophyd_async.core.signal_backend import SignalBackend
from ophyd_async.core.soft_signal_backend import SoftSignalBackend
from ophyd_async.core.utils import DEFAULT_TIMEOUT, ReadingValueCallback, T


class MockSignalBackend(SoftSignalBackend[T]):
    def __init__(
        self,
        datatype: Optional[type[T]],
        initial_value: Optional[T] = None,
        init_backend: Optional[SignalBackend] = None,
    ) -> None:
        super().__init__(datatype, initial_value=initial_value)
        self.mock = MagicMock()
        self.init_backend = init_backend

        self.put_proceeds = asyncio.Event()
        self.put_proceeds.set()

    def source(self, name: str) -> str:
        self.mock.source(name)
        if self.init_backend:
            return f"mock+{self.init_backend.source(name)}"
        return f"mock+{name}"

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.mock.connect(timeout=timeout)
        await super().connect(timeout=timeout)

    async def put(self, value: Optional[T], wait=True, timeout=None):
        self.mock.put(value, wait=wait, timeout=timeout)
        await super().put(value, wait=wait, timeout=timeout)

        if wait:
            await asyncio.wait_for(self.put_proceeds.wait(), timeout=timeout)

    def set_value(self, value: T):
        self.mock.set_value(value)
        super().set_value(value)

    async def get_descriptor(self, source: str) -> Descriptor:
        self.mock.get_descriptor(source)
        return await super().get_descriptor(source)

    async def get_reading(self) -> Reading:
        self.mock.get_reading()
        return await super().get_reading()

    async def get_value(self) -> T:
        self.mock.get_value()
        return await super().get_value()

    async def get_setpoint(self) -> T:
        """For a soft signal, the setpoint and readback values are the same."""
        self.mock.get_setpoint()
        return await super().get_setpoint()

    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        self.mock.set_callback(callback)
        super().set_callback(callback)
