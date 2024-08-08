import time

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, Field
from scanspec.specs import Frames, Path

from ophyd_async.core import TriggerLogic
from ophyd_async.core.async_status import AsyncStatus, WatchableAsyncStatus
from ophyd_async.core.signal import observe_value
from ophyd_async.core.utils import WatcherUpdate
from ophyd_async.epics.motion import Motor
from ophyd_async.epics.pmac import Pmac

TICK_S = 0.000001


class PmacTrajInfo(BaseModel):
    stack: list[Frames[Motor]] = Field(strict=True)
    # pmac: Pmac = Field(strict=True)


class PmacTrajectoryTriggerLogic(TriggerLogic[PmacTrajInfo]):
    """Device that moves a PMAC Motor record"""

    def __init__(self, pmac: Pmac) -> None:
        # Make a dict of which motors are for which cs axis
        self.pmac = pmac

    async def _ramp_up_velocity_pos(
        self, velocity: float, motor: Motor, end_velocity: float
    ):
        # Assuming ramping to or from 0
        max_velocity_acceleration_time = await motor.acceleration_time.get_value()
        max_velocity = await motor.max_velocity.get_value()
        delta_v = abs(end_velocity - velocity)
        accl_time = max_velocity_acceleration_time * delta_v / max_velocity
        disp = 0.5 * (velocity + end_velocity) * accl_time
        return [disp, accl_time]

    @AsyncStatus.wrap
    async def prepare(self, value: PmacTrajInfo):
        # Which Axes are in use?
        path = Path(value.stack)
        chunk = path.consume()
        scan_size = len(chunk)
        scan_axes = chunk.axes()

        cs_ports = set()
        positions: dict[int, npt.NDArray[np.float64]] = {}
        velocities: dict[int, npt.NDArray[np.float64]] = {}
        time_array: npt.NDArray[np.float64] = []
        cs_axes: dict[Motor, int] = {}
        for axis in scan_axes:
            if axis != "DURATION":
                cs_port, cs_index = await self.get_cs_info(axis)
                positions[cs_index] = np.empty((3 * scan_size,), dtype=np.float64)
                velocities[cs_index] = np.empty((scan_size,), dtype=np.float64)
                cs_ports.add(cs_port)
                cs_axes[axis] = cs_index
        assert len(cs_ports) == 1, "Motors in more than one CS"
        cs_port = cs_ports.pop()
        self.scantime = sum(chunk.midpoints["DURATION"])

        # Calc Velocity

        gaps = self._calculate_gaps(chunk)
        gaps = np.append(gaps, scan_size)
        start = 0
        for gap in gaps:
            for axis in scan_axes:
                if axis != "DURATION":
                    positions[cs_axes[axis]][3 * start : (3 * gap) + 1 : 3] = (
                        chunk.lower[axis][start : gap + 1]
                    )
                    positions[cs_axes[axis]][(3 * start) + 1 : 3 * gap + 2 : 3] = (
                        chunk.midpoints[axis][start : gap + 1]
                    )
                    positions[cs_axes[axis]][(3 * start) + 2 : 3 * gap + 3 : 3] = (
                        chunk.upper[axis][start : gap + 1]
                    )
                    velocities[cs_axes[axis]][start : gap + 1] = (
                        positions[cs_axes[axis]][(3 * start) + 2 : 3 * gap + 3 : 3]
                        - positions[cs_axes[axis]][(3 * start) : 3 * gap + 1 : 3]
                        / chunk.midpoints["DURATION"][start : gap + 1]
                    )
            start = gap + 1
        time_array = chunk.midpoints["DURATION"] / TICK_S
        # Calculate Starting and end Position to allow ramp up and trail off velocity
        self.initial_pos = {}
        run_up_time = 0
        final_time = 0
        for axis in scan_axes:
            if axis != "DURATION":
                run_up_disp, run_up_t = await self._ramp_up_velocity_pos(
                    0,
                    axis,
                    velocities[cs_axes[axis]][0],
                )
                self.initial_pos[cs_axes[axis]] = (
                    positions[cs_axes[axis]][0] - run_up_disp
                )
                # trail off position and time
                if velocities[cs_axes[axis]][0] == velocities[cs_axes[axis]][-1]:
                    final_pos = positions[cs_axes[axis]][-1] + run_up_disp
                    final_time = run_up_t
                else:
                    ramp_down_disp, ramp_down_time = await self._ramp_up_velocity_pos(
                        velocities[cs_axes[axis]][-1],
                        axis,
                        0,
                    )
                    final_pos = positions[cs_axes[axis]][-1] + ramp_down_disp
                    final_time = max(ramp_down_time, final_time)
                positions[cs_axes[axis]] = np.append(
                    positions[cs_axes[axis]], final_pos
                )
                velocities[cs_axes[axis]] = np.append(velocities[cs_axes[axis]], 0)
                run_up_time = max(run_up_time, run_up_t)

        self.scantime += run_up_time + final_time
        time_array[0] += int(run_up_time / TICK_S)
        time_array = np.append(time_array, int(final_time / TICK_S))

        for axis in scan_axes:
            if axis != "DURATION":
                self.pmac.profile_cs_name.set(cs_port)
                self.pmac.points_to_build.set(scan_size + 1)
                self.pmac.use_axis[cs_axes[axis] + 1].set(True)
                self.pmac.positions[cs_axes[axis] + 1].set(
                    np.append(
                        positions[cs_axes[axis]][1::3], positions[cs_axes[axis]][-1]
                    )
                )
                self.pmac.velocities[cs_axes[axis] + 1].set(velocities[cs_axes[axis]])
            else:
                self.pmac.time_array.set(time_array)

        # MOVE TO START
        for axis in scan_axes:
            if axis != "DURATION":
                await axis.set(self.initial_pos[cs_axes[axis]])

        # Set PMAC to use Velocity Array
        self.pmac.profile_calc_vel.set(False)
        self.pmac.build_profile.set(True)
        self._fly_start = time.monotonic()

    @AsyncStatus.wrap
    async def kickoff(self):
        self.status = self.execute_profile.set(1, timeout=self.scantime + 10)

    @WatchableAsyncStatus.wrap
    async def complete(self):
        async for percent in observe_value(self.scan_percent):
            yield WatcherUpdate(
                name=self.name,
                current=percent,
                initial=0,
                target=100,
                unit="%",
                precision=0,
                time_elapsed=time.monotonic() - self._fly_start,
            )
            if percent >= 100:
                break

    async def get_cs_info(self, motor: Motor) -> tuple[str, int]:
        output_link = await motor.output_link.get_value()
        # Split "@asyn(PORT,num)" into ["PORT", "num"]
        split = output_link.split("(")[1].rstrip(")").split(",")
        cs_port = split[0].strip()
        assert "CS" in cs_port, f"{self.name} not in a CS. It is not a compound motor."
        cs_index = int(split[1].strip()) - 1
        return cs_port, cs_index

    def _calculate_gaps(self, chunk: Frames[Motor]):
        inds = np.argwhere(chunk.gap)
        if len(inds) == 0:
            return len(chunk)
        else:
            return inds[0]
