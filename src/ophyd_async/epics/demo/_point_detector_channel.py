from typing import Annotated as A

from ophyd_async.core import SignalR, SignalRW, StandardReadable, StrictEnum
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix


class EnergyMode(StrictEnum):
    """Energy mode for `DemoPointDetectorChannel`."""

    LOW = "Low Energy"
    """Low energy mode"""

    HIGH = "High Energy"
    """High energy mode"""


class DemoPointDetectorChannel(StandardReadable, EpicsDevice):
    """A channel for `DemoPointDetector` with int value based on X and Y Motors."""

    value: A[SignalR[int], PvSuffix("Value"), Format.HINTED_UNCACHED_SIGNAL]
    mode: A[SignalRW[EnergyMode], PvSuffix("Mode"), Format.CONFIG_SIGNAL]
