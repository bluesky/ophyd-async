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
        # Tell the pattern generator about the motor positions
        self.x.user_readback.subscribe_value(pattern_generator.set_x)
        self.y.user_readback.subscribe_value(pattern_generator.set_y)
        # Set name of device and child devices
        super().__init__(name=name)
