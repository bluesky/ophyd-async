import asyncio
from functools import cached_property
from typing import Callable, Optional, Type
from unittest.mock import Mock

from bluesky.protocols import Descriptor, Reading

from ophyd_async.core.signal_backend import SignalBackend
from ophyd_async.core.soft_signal_backend import SoftSignalBackend
from ophyd_async.core.utils import DEFAULT_TIMEOUT, ReadingValueCallback, T


class MockSignalBackend(SignalBackend[T]):
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
            # then we create a soft signal to mimic it

            self.soft_backend = SoftSignalBackend(datatype=datatype)
        else:
            self.soft_backend = self.initial_backend

    def source(self, name: str) -> str:
        if self.initial_backend:
            return f"mock+{self.initial_backend.source(name)}"
        return f"mock+{name}"

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        pass

    @cached_property
    def put_mock(self) -> Mock:
        return Mock(name="put", spec=Callable)

    @cached_property
    def put_proceeds(self) -> asyncio.Event:
        put_proceeds = asyncio.Event()
        put_proceeds.set()
        return put_proceeds

    async def put(self, value: Optional[T], wait=True, timeout=None):
        self.put_mock(value, wait=wait, timeout=timeout)
        await self.soft_backend.put(value, wait=wait, timeout=timeout)

        if wait:
            await asyncio.wait_for(self.put_proceeds.wait(), timeout=timeout)

    def set_value(self, value: T):
        self.soft_backend.set_value(value)

    async def get_reading(self) -> Reading:
        return await self.soft_backend.get_reading()

    async def get_value(self) -> T:
        return await self.soft_backend.get_value()

    async def get_setpoint(self) -> T:
        """For a soft signal, the setpoint and readback values are the same."""
        return await self.soft_backend.get_setpoint()

    async def get_datakey(self, source: str) -> Descriptor:
        return await self.soft_backend.get_datakey(source)

    def set_callback(self, callback: Optional[ReadingValueCallback[T]]) -> None:
        self.soft_backend.set_callback(callback)
