import asyncio
import time
from contextlib import AbstractContextManager
from typing import Self

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import SignalR


class MonitorQueue(AbstractContextManager):
    def __init__(self, signal: SignalR):
        self.signal = signal
        self.updates: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
        self.signal.subscribe(self.updates.put_nowait)

    async def assert_updates(self, expected_value):
        # Get a reading
        update = await self.updates.get()
        # Work out what we were expecting
        expected_reading = {
            self.signal.name: {
                "value": expected_value,
                "timestamp": pytest.approx(time.time(), rel=0.1),
                "alarm_severity": 0,
            }
        }
        backend_value = await self.signal.get_value()
        backend_reading = await self.signal.read()
        # Check it matches
        assert update[self.signal.name]["value"] == expected_value == backend_value
        assert update == expected_reading == backend_reading

    def __enter__(self) -> Self:
        self.signal.subscribe(self.updates.put_nowait)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.signal.clear_sub(self.updates.put_nowait)
