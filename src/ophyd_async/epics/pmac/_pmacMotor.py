from bluesky.protocols import Movable, Stoppable

from ophyd_async.epics.motion import Motor


class PmacCSMotor(Motor, Movable, Stoppable):
    def __init__(self, prefix: str, csNum: int, csAxis: str, name="") -> None:
        self.csNum = csNum
        self.csAxis = csAxis
        super().__init__(prefix=prefix, name=name)
