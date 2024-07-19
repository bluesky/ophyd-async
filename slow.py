import asyncio
import subprocess
from collections import defaultdict
from typing import Dict
from unittest.mock import ANY, Mock, call, patch

import pytest
from bluesky import plans as bp
from bluesky.protocols import Reading
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DeviceCollector,
    NotConnected,
    assert_emitted,
    assert_reading,
    assert_value,
    callback_on_mock_put,
    set_mock_value,
)
from ophyd_async.epics import demo

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_WHILE = 0.001


class DemoWatcher:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._mock = Mock()

    def __call__(
        self,
        *args,
        current: float,
        initial: float,
        target: float,
        name: str | None = None,
        unit: str | None = None,
        precision: float | None = None,
        fraction: float | None = None,
        time_elapsed: float | None = None,
        time_remaining: float | None = None,
        **kwargs,
    ):
        self._mock(
            *args,
            current=current,
            initial=initial,
            target=target,
            name=name,
            unit=unit,
            precision=precision,
            time_elapsed=time_elapsed,
            **kwargs,
        )
        self._event.set()

    async def wait_for_call(self, *args, **kwargs):
        await asyncio.wait_for(self._event.wait(), timeout=1)
        assert self._mock.call_count == 1
        assert self._mock.call_args == call(*args, **kwargs)
        self._mock.reset_mock()
        self._event.clear()


async def test_mover_moving_well() -> None:
    async with DeviceCollector(mock=True):
        mock_mover = demo.Mover("BLxxI-MO-TABLE-01:X:")
        # Signals connected here

    assert mock_mover.name == "mock_mover"
    set_mock_value(mock_mover.units, "mm")
    set_mock_value(mock_mover.precision, 3)
    set_mock_value(mock_mover.velocity, 1)
    s = mock_mover.set(0.55)
    watcher = DemoWatcher()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await watcher.wait_for_call(
        name="mock_mover",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )

    await assert_value(mock_mover.setpoint, 0.55)
    assert not s.done
    done.assert_not_called()
    await asyncio.sleep(0.1)
    set_mock_value(mock_mover.readback, 0.1)
    await watcher.wait_for_call(
        name="mock_mover",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.05),
    )
    set_mock_value(mock_mover.readback, 0.5499999)
    await asyncio.sleep(A_WHILE)
    assert s.done
    assert s.success
    done.assert_called_once_with(s)
    done2 = Mock()
    s.add_callback(done2)
    done2.assert_called_once_with(s)


async def do_many():
    for i in range(200):
        await test_mover_moving_well()


if __name__ == "__main__":
    asyncio.run(do_many())
