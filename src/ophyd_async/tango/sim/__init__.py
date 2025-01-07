from ._counter import TangoCounter
from ._detector import TangoDetector
from ._mover import TangoMover
from ._tango import DemoCounter, DemoMover

__all__ = [
    "DemoCounter",
    "DemoMover",
    "TangoCounter",
    "TangoMover",
    "TangoDetector",
    "device_content",
]

device_content = (
    {
        "class": DemoMover,
        "devices": [{"name": "sim/motor/1"}],
    },
    {
        "class": DemoCounter,
        "devices": [{"name": "sim/counter/1"}, {"name": "sim/counter/2"}],
    },
)
