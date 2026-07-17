from typing import Annotated as A

from ophyd_async.core import StandardReadable
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix

from ._motor import DemoMotor


class DemoStage(StandardReadable, EpicsDevice):
    """A simulated sample stage with X and Y movables."""

    # The stage has a fixed set of child Devices, so we can declare them the
    # same way as Signals: a PvSuffix addresses each motor relative to the
    # stage's prefix, and Format.CHILD merges its readings into the stage.
    x: A[DemoMotor, PvSuffix("X:"), Format.CHILD]
    y: A[DemoMotor, PvSuffix("Y:"), Format.CHILD]
