from ophyd_async.core import StandardReadable
from ophyd_async.sim._pattern_generator import PatternGenerator

from ._motor import SimMotor


class SimStage(StandardReadable):
    """A simulated sample stage with X and Y movables."""

    def __init__(self, pattern_generator: PatternGenerator, name="") -> None:
        self.pattern_generator = pattern_generator
        # Define some child Devices
        with self.add_children_as_readables():
            self.x = SimMotor(instant=False)
            self.y = SimMotor(instant=False)
        # Set name of device and child devices
        super().__init__(name=name)

    def stage(self):
        """Stage the motors and report the position to the pattern generator."""
        # Tell the pattern generator about the motor positions
        self.x.user_readback.subscribe_value(self.pattern_generator.set_x)
        self.y.user_readback.subscribe_value(self.pattern_generator.set_y)
        return super().stage()

    def unstage(self):
        """Unstage the motors and remove the position subscription."""
        self.x.user_readback.clear_sub(self.pattern_generator.set_x)
        self.y.user_readback.clear_sub(self.pattern_generator.set_y)
        return super().unstage()
