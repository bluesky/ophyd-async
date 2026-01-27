from typing import Annotated as A

from ophyd_async.core import SignalR, SignalRW, StandardReadable, StrictEnum
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.core import StandardReadable
from ophyd_async.tango.core import TangoPolling, TangoDevice


class EnergyMode(StrictEnum):
    """Energy mode for `DemoPointDetectorChannel`."""

    LOW = "Low Energy"
    """Low energy mode"""

    HIGH = "High Energy"
    """High energy mode"""


class DemoPointDetectorChannel(TangoDevice, StandardReadable):
    """A channel for `DemoPointDetector` with int value based on X and Y Motors."""

    value: A[SignalR[int], TangoPolling(0.1, 0.1, 0.1), Format.HINTED_UNCACHED_SIGNAL]
    mode: A[SignalRW[EnergyMode], TangoPolling(0.1, 0.1, 0.1), Format.CONFIG_SIGNAL]

