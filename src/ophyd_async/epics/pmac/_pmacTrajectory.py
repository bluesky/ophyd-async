from bluesky.protocols import Flyable, Preparable

from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.epics.pmac import Pmac, PmacCSMotor


class PmacTrajectory(Pmac, Flyable, Preparable):
    """Device that moves a PMAC Motor record"""

    def __init__(
        self, prefix: str, cs: int, motors: list[PmacCSMotor], name=""
    ) -> None:
        # Make a dict of which motors are for which cs axis
        self.motors = {}
        for motor in motors:
            self.motors[motor.csAxis] = motor

        super().__init__(prefix, name=name)

    async def _ramp_up_velocity_pos(
        self, velocity: float, motor: PmacCSMotor, end_velocity
    ):
        # Assuming ramping to or from 0
        accl_time = await motor.acceleration_time.get_value()
        return 0.5 * (velocity + end_velocity) * accl_time

    @AsyncStatus.wrap
    async def prepare(self, scanSpecStack):
        # Which Axes are in use?

        scanSize = len(scanSpecStack[0])
        scanAxes = scanSpecStack[0].axes()

        self.profile = {}
        for axis in scanAxes:
            self.profile[axis.lower()] = []
            if axis != "DURATION":
                self.profile[axis.lower() + "_velocity"] = []

        # Calc Velocity

        for axis in scanAxes:
            for i in range(scanSize - 1):
                if axis != "DURATION":
                    self.profile[axis.lower() + "_velocity"].append(
                        (
                            scanSpecStack[0].midpoints[axis][i + 1]
                            - scanSpecStack[0].midpoints[axis][i]
                        )
                        / (scanSpecStack[0].midpoints["DURATION"][i])
                    )
                self.profile[axis.lower()].append(scanSpecStack[0].midpoints[axis][i])
            self.profile[axis.lower()].append(
                scanSpecStack[0].midpoints[axis][scanSize - 1]
            )
            if axis != "DURATION":
                self.profile[axis.lower() + "_velocity"].append(0)

        # Calculate Starting Position to allow ramp up to velocity
        self.initial_pos = {}
        for axis in scanAxes:
            if axis != "DURATION":
                self.initial_pos[axis] = self.profile[axis.lower()][
                    0
                ] - await self._ramp_up_velocity_pos(
                    0,
                    self.motors[axis.lower()],
                    self.profile[axis.lower() + "_velocity"][0],
                )

        # Send trajectory to brick
        for axis in scanAxes:
            if axis != "DURATION":
                getattr(self, "use_" + axis.lower()).set(True)
                getattr(self, axis.lower()).set(self.profile[axis.lower()])
                getattr(self, axis.lower() + "_vel").set(
                    self.profile[axis.lower() + "_velocity"]
                )
            else:
                self.timeArray.set(self.profile["duration"])

        # MOVE TO START

    async def kickoff(self):
        pass

    async def complete(self):
        pass
