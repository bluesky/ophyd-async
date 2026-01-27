from ophyd_async.core import StandardReadable

from ._motor import DemoMotor


class DemoStage(StandardReadable):
    """A simulated sample stage with X and Y movables."""

    def __init__(self, x_trl: str | None = "", y_trl: str | None = "", name="") -> None:
        # Define some child Devices
        with self.add_children_as_readables():
            self.x = DemoMotor(x_trl)
            self.y = DemoMotor(y_trl)
        # Set name of device and child devices
        super().__init__(name=name)
