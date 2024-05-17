"""Demo EPICS Devices for the tutorial"""

import asyncio
import atexit
import random
import string
import subprocess
import sys
from dataclasses import replace
from enum import Enum
from pathlib import Path

import numpy as np
from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    ConfigSignal,
    Device,
    DeviceVector,
    HintedSignal,
    StandardReadable,
    WatchableAsyncStatus,
    observe_value,
)
from ophyd_async.core.utils import WatcherUpdate

from ..signal.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class EnergyMode(str, Enum):
    """Energy mode for `Sensor`"""

    #: Low energy mode
    low = "Low Energy"
    #: High energy mode
    high = "High Energy"


class Sensor(StandardReadable):
    """A demo sensor that produces a scalar value based on X and Y Movers"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(HintedSignal):
            self.value = epics_signal_r(float, prefix + "Value")
        with self.add_children_as_readables(ConfigSignal):
            self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")

        super().__init__(name=name)


class SensorGroup(StandardReadable):
    def __init__(self, prefix: str, name: str = "", sensor_count: int = 3) -> None:
        with self.add_children_as_readables():
            self.sensors = DeviceVector(
                {i: Sensor(f"{prefix}{i}:") for i in range(1, sensor_count + 1)}
            )

        super().__init__(name)


class Mover(StandardReadable, Movable, Stoppable):
    """A demo movable that moves based on velocity"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(HintedSignal):
            self.readback = epics_signal_r(float, prefix + "Readback")

        with self.add_children_as_readables(ConfigSignal):
            self.velocity = epics_signal_rw(float, prefix + "Velocity")
            self.units = epics_signal_r(str, prefix + "Readback.EGU")

        self.setpoint = epics_signal_rw(float, prefix + "Setpoint")
        self.precision = epics_signal_r(int, prefix + "Readback.PREC")
        # Signals that collide with standard methods should have a trailing underscore
        self.stop_ = epics_signal_x(prefix + "Stop.PROC")
        # Whether set() should complete successfully or not
        self._set_success = True

        super().__init__(name=name)

    def set_name(self, name: str):
        super().set_name(name)
        # Readback should be named the same as its parent in read()
        self.readback.set_name(name)

    async def _move(self, new_position: float):
        self._set_success = True
        # time.monotonic won't go backwards in case of NTP corrections
        old_position, units, precision = await asyncio.gather(
            self.setpoint.get_value(),
            self.units.get_value(),
            self.precision.get_value(),
        )
        # Wait for the value to set, but don't wait for put completion callback
        move_status = self.setpoint.set(new_position, wait=True)
        if not self._set_success:
            raise RuntimeError("Motor was stopped")
        # return a template to set() which it can use to yield progress updates
        return (
            WatcherUpdate(
                initial=old_position,
                current=old_position,
                target=new_position,
                unit=units,
                precision=precision,
            ),
            move_status,
        )

    @WatchableAsyncStatus.wrap  # uses the timeout argument from the function it wraps
    async def set(self, new_position: float, timeout: float | None = None):
        update, _ = await self._move(new_position)
        async for current_position in observe_value(self.readback):
            yield replace(
                update,
                name=self.name,
                current=current_position,
            )
            if np.isclose(current_position, new_position):
                break

    async def stop(self, success=True):
        self._set_success = success
        status = self.stop_.trigger()
        await status


class SampleStage(Device):
    """A demo sample stage with X and Y movables"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some child Devices
        self.x = Mover(prefix + "X:")
        self.y = Mover(prefix + "Y:")
        # Set name of device and child devices
        super().__init__(name=name)


def start_ioc_subprocess() -> str:
    """Start an IOC subprocess with EPICS database for sample stage and sensor
    with the same pv prefix
    """

    pv_prefix = "".join(random.choice(string.ascii_uppercase) for _ in range(12)) + ":"
    here = Path(__file__).absolute().parent
    args = [sys.executable, "-m", "epicscorelibs.ioc"]

    # Create standalone sensor
    args += ["-m", f"P={pv_prefix}"]
    args += ["-d", str(here / "sensor.db")]

    # Create sensor group
    for suffix in ["1", "2", "3"]:
        args += ["-m", f"P={pv_prefix}{suffix}:"]
        args += ["-d", str(here / "sensor.db")]

    # Create X and Y motors
    for suffix in ["X", "Y"]:
        args += ["-m", f"P={pv_prefix}{suffix}:"]
        args += ["-d", str(here / "mover.db")]

    # Start IOC
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    atexit.register(process.communicate, "exit")
    return pv_prefix
