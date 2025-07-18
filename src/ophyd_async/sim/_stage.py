from bluesky.protocols import Reading

from ophyd_async.core import StandardReadable
from ophyd_async.sim._pattern_generator import PatternGenerator

from ._motor import SimMotor


class SimStage(StandardReadable):
    """A simulated sample stage with X and Y movables."""

    def __init__(self, pattern_generator: PatternGenerator, name="") -> None:
        # Define some child Devices
        with self.add_children_as_readables():
            self.x = SimMotor(instant=False)
            self.y = SimMotor(instant=False)

        def _set_x_from_reading(readings: dict[str, Reading[float]]):
            (x_reading,) = readings.values()
            pattern_generator.set_x(x_reading["value"])

        def _set_y_from_reading(readings: dict[str, Reading[float]]):
            (y_reading,) = readings.values()
            pattern_generator.set_y(y_reading["value"])

        # Tell the pattern generator about the motor positions
        self.x.user_readback.subscribe_reading(_set_x_from_reading)
        self.y.user_readback.subscribe_reading(_set_y_from_reading)
        # Set name of device and child devices
        super().__init__(name=name)
