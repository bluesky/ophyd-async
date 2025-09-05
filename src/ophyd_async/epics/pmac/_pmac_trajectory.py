import asyncio

import numpy as np
from scanspec.core import Path
from scanspec.specs import Spec

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    FlyerController,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._pmac_io import CS_LETTERS
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,
    _Trajectory,
    calculate_ramp_position_and_duration,
)


class PmacTrajectoryTriggerLogic(FlyerController):
    def __init__(self, pmac: PmacIO) -> None:
        self.pmac = pmac
        self.scantime: float | None = None

    async def prepare(self, value: Spec[Motor]):
        slice = Path(value.calculate()).consume()
        motor_info = await _PmacMotorInfo.from_motors(self.pmac, slice.axes())
        ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
            slice, motor_info, True
        )
        ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
            slice, motor_info, False
        )
        trajectory = _Trajectory.from_slice(slice, ramp_up_time, motor_info)
        await asyncio.gather(
            self._build_trajectory(
                trajectory, motor_info, ramp_down_pos, ramp_down_time
            ),
            self._move_to_start(motor_info, ramp_up_pos),
        )

    async def kickoff(self):
        if not self.scantime:
            raise RuntimeError("Cannot kickoff. Must call prepare first.")
        self.status = await self.pmac.trajectory.execute_profile.set(
            True, timeout=self.scantime + 1
        )

    async def complete(self):
        if not self.scantime:
            raise RuntimeError("Cannot complete. Must call prepare first.")
        await wait_for_value(
            self.pmac.trajectory.execute_profile,
            False,
            timeout=self.scantime + DEFAULT_TIMEOUT,
        )

    async def stop(self):
        await self.pmac.trajectory.abort_profile.set(True)

    async def _build_trajectory(
        self,
        trajectory: _Trajectory,
        motor_info: _PmacMotorInfo,
        ramp_down_pos: dict[Motor, np.float64],
        ramp_down_time: float,
    ):
        trajectory = trajectory.append_ramp_down(ramp_down_pos, ramp_down_time, 0)
        self.scantime = np.sum(trajectory.durations)
        use_axis = {axis + 1: False for axis in range(len(CS_LETTERS))}

        for motor, number in motor_info.motor_cs_index.items():
            use_axis[number + 1] = True
            await self.pmac.trajectory.positions[number + 1].set(
                trajectory.positions[motor]
            )
            await self.pmac.trajectory.velocities[number + 1].set(
                trajectory.velocities[motor]
            )

        coros = [
            self.pmac.trajectory.profile_cs_name.set(motor_info.cs_port),
            self.pmac.trajectory.time_array.set(trajectory.durations),
            self.pmac.trajectory.user_array.set(trajectory.user_programs),
            self.pmac.trajectory.points_to_build.set(len(trajectory.durations)),
            self.pmac.trajectory.calculate_velocities.set(False),
        ] + [
            self.pmac.trajectory.use_axis[number].set(use)
            for number, use in use_axis.items()
        ]
        await asyncio.gather(*coros)
        await self.pmac.trajectory.build_profile.set(True)

    async def _move_to_start(
        self, motor_info: _PmacMotorInfo, ramp_up_position: dict[Motor, np.float64]
    ):
        coord = self.pmac.coord[motor_info.cs_number]
        coros = []
        await coord.defer_moves.set(True)
        for motor, position in ramp_up_position.items():
            coros.append(
                set_and_wait_for_value(
                    coord.cs_axis_setpoint[motor_info.motor_cs_index[motor] + 1],
                    position,
                    set_timeout=10,
                    wait_for_set_completion=False,
                )
            )
        statuses = await asyncio.gather(*coros)
        await coord.defer_moves.set(False)
        await asyncio.gather(*statuses)
