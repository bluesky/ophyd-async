import asyncio

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    ConnectionTimeoutError,
    Device,
    DirectoryInfo,
    SignalBackend,
    SignalRW,
    SimSignalBackend,
    StaticDirectoryProvider,
)


def test_static_directory_provider():
    """NOTE: this is a dummy test.

    It should be removed once detectors actually implement directory providers.
    This will happen in a soon to be developed PR.
    """
    dir_path, filename = "some/path", "test_file"
    provider = StaticDirectoryProvider(dir_path, filename)

    assert provider() == DirectoryInfo(dir_path, filename)


class FailingBackend(SimSignalBackend):
    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        await asyncio.sleep(timeout)
        raise ConnectionTimeoutError(self.source)


async def test_wait_for_connection():
    """Checks that ConnectionTimeoutError is aggregated correctly across Devices."""

    class DummyChildDevice(Device):
        def __init__(self, name: str = "") -> None:
            self.failing_signal = SignalRW(
                backend=FailingBackend(int, "FAILING_SIGNAL")
            )
            super().__init__(name)

    class DummyDevice(Device):
        def __init__(self, name: str = "") -> None:
            self.working_signal = SignalRW(
                backend=SimSignalBackend(int, "WORKING_SIGNAL")
            )
            self.child_device = DummyChildDevice("child_device")
            super().__init__(name)

    device = DummyDevice()

    with pytest.raises(ConnectionTimeoutError):
        await device.connect(timeout=0.01)
