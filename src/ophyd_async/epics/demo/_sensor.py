from typing import Annotated as A

from ophyd_async.core import (
    DeviceVector,
    SignalR,
    SignalRW,
    StandardReadable,
    StrictEnum,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix


class EnergyMode(StrictEnum):
    """Energy mode for `Sensor`"""

    #: Low energy mode
    low = "Low Energy"
    #: High energy mode
    high = "High Energy"


class Sensor(StandardReadable, EpicsDevice):
    """A demo sensor that produces a scalar value based on X and Y Movers"""

    value: A[SignalR[float], PvSuffix("Value"), Format.HINTED_SIGNAL]
    mode: A[SignalRW[EnergyMode], PvSuffix("Mode"), Format.CONFIG_SIGNAL]


class SensorGroup(StandardReadable):
    def __init__(self, prefix: str, name: str = "", sensor_count: int = 3) -> None:
        with self.add_children_as_readables():
            self.sensors = DeviceVector(
                {i: Sensor(f"{prefix}{i}:") for i in range(1, sensor_count + 1)}
            )

        super().__init__(name)
