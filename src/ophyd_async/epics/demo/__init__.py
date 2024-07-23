"""Demo EPICS Devices for the tutorial"""

import atexit
import random
import string
import subprocess
import sys
from pathlib import Path

from ._mover import Mover, SampleStage
from ._sensor import EnergyMode, Sensor, SensorGroup

__all__ = [
    "Mover",
    "SampleStage",
    "EnergyMode",
    "Sensor",
    "SensorGroup",
]


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
