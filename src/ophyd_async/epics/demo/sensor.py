from enum import Enum

from ophyd_async.core import ConfigSignal, DeviceVector, HintedSignal, StandardReadable
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw


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
