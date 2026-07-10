"""Demo Tango Devices for the tutorial."""

from pathlib import Path

from ._motor import DemoMotor
from ._point_detector import DemoPointDetector
from ._point_detector_channel import DemoPointDetectorChannel, EnergyMode
from ._stage import DemoStage

#: Path to the standalone script serving this tutorial's motor/channel/
#: detector device servers - pass to `ophyd_async.tango.testing.
#: start_tango_device_servers`. A plain path constant rather than a module
#: reference so nothing needs to import `_tango_device_servers.py` (which
#: would pull in `tango.server`/`tango.test_context`) just to launch it.
DEVICE_SERVERS = Path(__file__).parent / "_tango_device_servers.py"

__all__ = [
    "DEVICE_SERVERS",
    "DemoMotor",
    "DemoStage",
    "EnergyMode",
    "DemoPointDetectorChannel",
    "DemoPointDetector",
]
