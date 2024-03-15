from ophyd_async.epics.signal.signal import epics_signal_rw
from ophyd_async.sim import SimDriver
from tests.epics.motion.test_motor import sim_motor


class SimSample:
    x_motor = epics_signal_rw(sim_motor, name="x_motor")
    y_motor = epics_signal_rw(sim_motor, name="y_motor")
    patternGenerator: SimDriver

    def __init__(self, patternGenerator: SimDriver) -> None:
        self.patternGenerator = patternGenerator

    def set_x(self, value: float) -> None:
        self.patternGenerator.set_x(value)

    def set_y(self, value: float) -> None:
        self.patternGenerator.set_y(value)
