from ophyd_async.core import StandardReadable

from ._motor import DemoMotor


class DemoStage(StandardReadable):
    """A simulated sample stage with X and Y movables."""

    def __init__(self, prefix: str, name="") -> None:
        # Define some child Devices
        with self.add_children_as_readables():
            self.x = DemoMotor(prefix + "X:")
            self.y = DemoMotor(prefix + "Y:")
        # Set name of device and child devices
        super().__init__(name=name)
