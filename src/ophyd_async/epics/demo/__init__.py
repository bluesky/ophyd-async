"""Demo EPICS Devices for the tutorial."""

from pathlib import Path

from ._motor import DemoMotor
from ._point_detector import DemoPointDetector
from ._point_detector_channel import DemoPointDetectorChannel, EnergyMode
from ._stage import DemoStage

#: Path to the standalone script serving this tutorial's IOC - pass to
#: `ophyd_async.epics.testing.start_ioc`. A plain path constant rather than a
#: module reference so nothing needs to import `_ioc.py` just to launch it.
IOC = Path(__file__).parent / "_ioc.py"

__all__ = [
    "IOC",
    "DemoMotor",
    "DemoStage",
    "EnergyMode",
    "DemoPointDetectorChannel",
    "DemoPointDetector",
]
