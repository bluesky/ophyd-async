import asyncio
from collections.abc import Callable
from functools import cached_property
from unittest.mock import AsyncMock

from bluesky.protocols import Reading
from event_model import DataKey

from ._derived_signal_backend import DerivedSignalBackend
from ._signal_backend import SignalBackend, SignalDatatypeT
from ._soft_signal_backend import SoftSignalBackend
from ._utils import Callback, LazyMock


class MockSignalBackend(SignalBackend[SignalDatatypeT]):
    """Signal backend for testing, created by ``Device.connect(mock=True)``."""

    def __init__(
        self,
        initial_backend: SignalBackend[SignalDatatypeT],
        mock: LazyMock,
    ) -> None:
        if isinstance(initial_backend, MockSignalBackend):
            raise ValueError("Cannot make a MockSignalBackend for a MockSignalBackend")

        self.initial_backend = initial_backend

        if isinstance(self.initial_backend, SoftSignalBackend | DerivedSignalBackend):
            # Backend is already a SoftSignalBackend, so use it
            self.soft_backend = self.initial_backend
        else:
            # Backend is not a SoftSignalBackend, so create one to mimic it
            self.soft_backend = SoftSignalBackend(
                datatype=self.initial_backend.datatype
            )

        # use existing Mock if provided
        self.mock = mock
        super().__init__(datatype=self.initial_backend.datatype)

    @cached_property
    def put_mock(self) -> AsyncMock:
        """Return the mock that will track calls to `put()`."""
        put_mock = AsyncMock(name="put", spec=Callable)
        self.mock().attach_mock(put_mock, "put")
        return put_mock

    def set_value(self, value: SignalDatatypeT):
        """Set the value of the signal."""
        self.soft_backend.set_value(value)

    def source(self, name: str, read: bool) -> str:
        return f"mock+{self.initial_backend.source(name, read)}"

    async def connect(self, timeout: float) -> None:
        raise RuntimeError("It is not possible to connect a MockSignalBackend")

    @cached_property
    def put_proceeds(self) -> asyncio.Event:
        """Return an Event that will block `put()` until set.

        The Event is initially set, but can be unset to block `put()`.
        """
        put_proceeds = asyncio.Event()
        put_proceeds.set()
        return put_proceeds

    async def put(self, value: SignalDatatypeT | None, wait: bool):
        await self.put_mock(value, wait=wait)
        await self.soft_backend.put(value, wait=wait)
        if wait:
            await self.put_proceeds.wait()

    async def get_reading(self) -> Reading:
        return await self.soft_backend.get_reading()

    async def get_value(self) -> SignalDatatypeT:
        return await self.soft_backend.get_value()

    async def get_setpoint(self) -> SignalDatatypeT:
        return await self.soft_backend.get_setpoint()

    async def get_datakey(self, source: str) -> DataKey:
        return await self.soft_backend.get_datakey(source)

    def set_callback(self, callback: Callback[Reading[SignalDatatypeT]] | None) -> None:
        self.soft_backend.set_callback(callback)
