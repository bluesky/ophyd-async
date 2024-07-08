import time

from bluesky.protocols import Flyable, Preparable

from ophyd_async.core.async_status import AsyncStatus, WatchableAsyncStatus
from ophyd_async.core.utils import WatcherUpdate
from ophyd_async.epics.pmac import Pmac, PmacCSMotor

TICK_S = 0.000001


class PmacTrajectory(Pmac, Flyable, Preparable):
    """Device that moves a PMAC Motor record"""

    def __init__(
        self, prefix: str, cs: int, motors: list[PmacCSMotor], name=""
    ) -> None:
        # Make a dict of which motors are for which cs axis
        self.motors = {}
        for motor in motors:
            self.motors[motor.csAxis] = motor
        self._fly_start: float
        self.cs = cs
        super().__init__(prefix, cs, name=name)

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
                    self.profile[axis.lower()].append(
                        scanSpecStack[0].midpoints[axis][i]
                    )
                else:
                    self.profile[axis.lower()].append(
                        int(scanSpecStack[0].midpoints[axis][i] / TICK_S)
                    )
            if axis != "DURATION":
                self.profile[axis.lower()].append(
                    scanSpecStack[0].midpoints[axis][scanSize - 1]
                )
                self.profile[axis.lower() + "_velocity"].append(0)
            else:
                self.profile[axis.lower()].append(
                    int(scanSpecStack[0].midpoints[axis][scanSize - 1] / TICK_S)
                )

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
                self.profile_cs_name.set(self.cs)
                self.points_to_build.set(scanSize)
                getattr(self, "use_" + axis.lower()).set(True)
                getattr(self, axis.lower()).set(self.profile[axis.lower()])
                getattr(self, axis.lower() + "_vel").set(
                    self.profile[axis.lower() + "_velocity"]
                )
            else:
                self.timeArray.set(self.profile["duration"])

        # MOVE TO START
        for axis in scanAxes:
            if axis != "DURATION":
                await self.motors[axis.lower()].set(self.initial_pos[axis])

        # Set No Of Points

        self.build_profile.set(True)
        self._fly_start = time.monotonic

    @AsyncStatus.wrap
    async def kickoff(self):
        await self.execute_profile.set(True)

    @WatchableAsyncStatus.wrap
    async def complete(self):
        yield WatcherUpdate(
            name=self.name,
            current=self.scan_percent,
            initial=0,
            target=100,
            unit="%",
            precision=0,
            time_elapsed=time.monotonic() - self._fly_start,
        )
