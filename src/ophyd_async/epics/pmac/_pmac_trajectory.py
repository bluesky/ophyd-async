import asyncio
from dataclasses import dataclass

import numpy as np
from scanspec.core import Path
from scanspec.specs import Spec

from ophyd_async.core import FlyerController, wait_for_value
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._pmac_io import CS_LETTERS
from ophyd_async.epics.pmac._utils import (
    TICK_S,
    _PmacMotorInfo,
    _Trajectory,
    calculate_ramp_position_and_duration,
)


@dataclass
class PmacTriggerLogic:
    spec: Spec[Motor]


class PmacTrajectoryTriggerLogic(FlyerController[PmacTriggerLogic]):
    def __init__(self, pmac: PmacIO) -> None:
        self.pmac = pmac
        self.scantime: float | None = None

    async def prepare(self, value: PmacTriggerLogic):
        _slice = Path(value.spec.calculate()).consume()
        motor_info = await _PmacMotorInfo.from_motors(self.pmac, _slice.axes())
        ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
            _slice, motor_info, True
        )
        ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
            _slice, motor_info, False
        )
        traj = _Trajectory.from_slice(_slice, ramp_up_time)
        await asyncio.gather(
            self._build_trajectory(traj, motor_info, ramp_down_pos, ramp_down_time),
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
            timeout=self.scantime + 11,  # Why 11s?
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
        await self.pmac.trajectory.profile_cs_name.set(motor_info.cs_port)
        new_time = np.append(trajectory.durations, [int(ramp_down_time / TICK_S)])
        self.scantime = np.sum(new_time)
        await self.pmac.trajectory.time_array.set(new_time)
        await self.pmac.trajectory.user_array.set(trajectory.user_programs)

        # Unselect axes to later select only the ones that will be used in the scan
        for axis in range(len(CS_LETTERS)):
            await self.pmac.trajectory.use_axis[axis + 1].set(False)

        size = 0
        for motor, number in motor_info.motor_cs_index.items():
            new_pos = np.append(trajectory.positions[motor], [ramp_down_pos[motor]])
            new_vel = np.append(trajectory.velocities[motor], [0])
            await self.pmac.trajectory.use_axis[number + 1].set(True)
            await self.pmac.trajectory.positions[number + 1].set(new_pos)
            await self.pmac.trajectory.velocities[number + 1].set(new_vel)
            size += len(new_pos)
        await self.pmac.trajectory.points_to_build.set(size)
        await self.pmac.trajectory.calculate_velocities.set(False)
        await self.pmac.trajectory.build_profile.set(True)

    async def _move_to_start(
        self, motor_info: _PmacMotorInfo, ramp_up_position: dict[Motor, np.float64]
    ):
        coord = self.pmac.coord[motor_info.cs_number]
        await coord.defer_moves.set(True)
        for motor, position in ramp_up_position.items():
            await motor.set(position)
        await coord.defer_moves.set(False)
