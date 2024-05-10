import asyncio
from typing import Optional, Type
from unittest.mock import MagicMock

from bluesky.protocols import Descriptor, Reading

from ophyd_async.core.signal_backend import SignalBackend
from ophyd_async.core.soft_signal_backend import SoftSignalBackend
from ophyd_async.core.utils import DEFAULT_TIMEOUT, ReadingValueCallback, T


class MockSignalBackend(SignalBackend):
    def __init__(
        self,
        datatype: Optional[Type[T]] = None,
        initial_backend: Optional[SignalBackend[T]] = None,
    ) -> None:
        if isinstance(initial_backend, MockSignalBackend):
            raise ValueError("Cannot make a MockSignalBackend for a MockSignalBackends")

        self.initial_backend = initial_backend

        if datatype is None:
            assert (
                self.initial_backend
            ), "Must supply either initial_backend or datatype"
            datatype = self.initial_backend.datatype

        self.datatype = datatype

        if not isinstance(self.initial_backend, SoftSignalBackend):
            # If the backend is a hard signal backend, or not provided,
            # then we create a soft signal to mimick it

            self.soft_backend = SoftSignalBackend(datatype=datatype)
        else:
            self.soft_backend = initial_backend

        self.mock = MagicMock()

        self.put_proceeds = asyncio.Event()
        self.put_proceeds.set()

    def source(self, name: str) -> str:
        self.mock.source(name)
        if self.initial_backend:
            return f"mock+{self.initial_backend.source(name)}"
        return f"mock+{name}"

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.mock.connect(timeout=timeout)

    async def put(self, value: Optional[T], wait=True, timeout=None):
        self.mock.put(value, wait=wait, timeout=timeout)
        await self.soft_backend.put(value, wait=wait, timeout=timeout)

        if wait:
            await asyncio.wait_for(self.put_proceeds.wait(), timeout=timeout)

    def set_value(self, value: T):
        self.mock.set_value(value)
        self.soft_backend.set_value(value)

    async def get_descriptor(self, source: str) -> Descriptor:
        self.mock.get_descriptor(source)
        return await self.soft_backend.get_descriptor(source)

    async def get_reading(self) -> Reading:
        self.mock.get_reading()
        return await self.soft_backend.get_reading()

    async def get_value(self) -> T:
        self.mock.get_value()
        return await self.soft_backend.get_value()

    async def get_setpoint(self) -> T:
        """For a soft signal, the setpoint and readback values are the same."""
        self.mock.get_setpoint()
        return await self.soft_backend.get_setpoint()

    async def get_datakey(self, source: str) -> Descriptor:
        return await self.soft_backend.get_datakey(source)

    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        self.mock.set_callback(callback)
        self.soft_backend.set_callback(callback)
