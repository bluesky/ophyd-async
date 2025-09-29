import asyncio
from dataclasses import dataclass

import numpy as np
from scanspec.core import Path, Slice
from scanspec.specs import Spec

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    FlyerController,
    error_if_none,
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.epics.motor import Motor
from ophyd_async.epics.pmac import PmacIO
from ophyd_async.epics.pmac._pmac_io import CS_LETTERS
from ophyd_async.epics.pmac._pmac_trajectory_generation import PVT, Trajectory
from ophyd_async.epics.pmac._utils import (
    _PmacMotorInfo,
    calculate_ramp_position_and_duration,
)

# PMAC durations are in milliseconds
# We must convert from scanspec durations (seconds) to milliseconds
# PMAC motion program multiples durations by 0.001
# (see https://github.com/DiamondLightSource/pmac/blob/afe81f8bb9179c3a20eff351f30bc6cfd1539ad9/pmacApp/pmc/trajectory_scan_code_ppmac.pmc#L241)
# Therefore, we must divide scanspec durations by 10e-6
TICK_S = 0.000001
SLICE_SIZE = 4000


@dataclass
class PmacPrepareContext:
    path: Path
    motor_info: _PmacMotorInfo
    ramp_up_time: float


class PmacTrajectoryTriggerLogic(FlyerController):
    def __init__(self, pmac: PmacIO) -> None:
        self.pmac = pmac
        self._next_pvt: PVT | None
        self._loaded: int = 0
        self._trajectory_status: AsyncStatus | None = None
        self._prepare_context: PmacPrepareContext | None = None

    async def prepare(self, value: Spec[Motor]):
        path = Path(value.calculate())
        slice = path.consume(SLICE_SIZE)
        path_length = len(path)
        motors = slice.axes()
        motor_info = await _PmacMotorInfo.from_motors(self.pmac, motors)
        ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
            slice, motor_info, True
        )
        self._prepare_context = PmacPrepareContext(
            path=path, motor_info=motor_info, ramp_up_time=ramp_up_time
        )
        await asyncio.gather(
            self._build_trajectory(motor_info, slice, path_length, ramp_up_time),
            self._move_to_start(motor_info, ramp_up_pos),
        )

    async def kickoff(self):
        prepare_context = error_if_none(
            self._prepare_context, "Cannot kickoff. Must call prepare first."
        )
        self._prepare_context = None
        self._trajectory_status = self._execute_trajectory(
            prepare_context.path, prepare_context.motor_info
        )
        # Wait for the ramp up to happen
        await wait_for_value(
            self.pmac.trajectory.total_points,
            lambda v: v >= 1,
            prepare_context.ramp_up_time + DEFAULT_TIMEOUT,
        )

    async def complete(self):
        trajectory_status = error_if_none(
            self._trajectory_status, "Cannot complete. Must call kickoff first."
        )
        await trajectory_status
        # Reset trajectory status and number of loaded points
        self._trajectory_status = None
        self._loaded = 0

    async def stop(self):
        await self.pmac.trajectory.abort_profile.trigger()

    @AsyncStatus.wrap
    async def _execute_trajectory(self, path: Path, motor_info: _PmacMotorInfo):
        execute_status = self.pmac.trajectory.execute_profile.set(
            True, wait=True, timeout=None
        )
        # We consume SLICE_SIZE from self.path and parse a trajectory
        # containing at least 2 * SLICE_SIZE, as a gapless trajectory
        # will contain 2 points per slice frame. If gaps are present,
        # additional points are inserted, overfilling the buffer.
        min_buffer_size = SLICE_SIZE * 2
        async for current_point in observe_value(
            self.pmac.trajectory.total_points,
            done_status=execute_status,
            timeout=DEFAULT_TIMEOUT,
        ):
            # Ensure we maintain a minimum buffer size, if we have more points to append
            if len(path) != 0 and self._loaded - current_point < min_buffer_size:
                # We have less than SLICE_SIZE * 2 points in the buffer, so refill
                next_slice = path.consume(SLICE_SIZE)
                path_length = len(path)
                await self._append_trajectory(next_slice, path_length, motor_info)

    async def _append_trajectory(
        self, slice: Slice, path_length: int, motor_info: _PmacMotorInfo
    ):
        trajectory = await self._parse_trajectory(slice, path_length, motor_info)
        await self._set_trajectory_arrays(trajectory, motor_info)
        await self.pmac.trajectory.append_profile.trigger()

    async def _build_trajectory(
        self,
        motor_info: _PmacMotorInfo,
        slice: Slice,
        path_length: int,
        ramp_up_time: float,
    ):
        trajectory = await self._parse_trajectory(
            slice, path_length, motor_info, ramp_up_time
        )
        use_axis = {
            axis + 1: (axis in motor_info.motor_cs_index.values())
            for axis in range(len(CS_LETTERS))
        }

        coros = [
            self.pmac.trajectory.profile_cs_name.set(motor_info.cs_port),
            self.pmac.trajectory.calculate_velocities.set(False),
            self._set_trajectory_arrays(trajectory, motor_info),
        ] + [
            self.pmac.trajectory.use_axis[number].set(use)
            for number, use in use_axis.items()
        ]

        await asyncio.gather(*coros)
        await self.pmac.trajectory.build_profile.trigger()

    async def _parse_trajectory(
        self,
        slice: Slice,
        path_length: int,
        motor_info: _PmacMotorInfo,
        ramp_up_time: float | None = None,
    ) -> Trajectory:
        trajectory, exit_pvt = Trajectory.from_slice(
            slice,
            motor_info,
            None if ramp_up_time else self._next_pvt,
            ramp_up_time=ramp_up_time,
        )

        if path_length == 0:
            ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
                slice, motor_info, False
            )
            trajectory = trajectory.with_ramp_down(
                exit_pvt, ramp_down_pos, ramp_down_time, 0
            )
        self._next_pvt = exit_pvt
        self._loaded += len(trajectory)

        return trajectory

    async def _set_trajectory_arrays(
        self, trajectory: Trajectory, motor_info: _PmacMotorInfo
    ):
        coros = []
        for motor, number in motor_info.motor_cs_index.items():
            coros.append(
                self.pmac.trajectory.positions[number + 1].set(
                    trajectory.positions[motor]
                )
            )
            coros.append(
                self.pmac.trajectory.velocities[number + 1].set(
                    trajectory.velocities[motor]
                )
            )
        coros.extend(
            [
                self.pmac.trajectory.time_array.set(trajectory.durations / TICK_S),
                self.pmac.trajectory.user_array.set(trajectory.user_programs),
                self.pmac.trajectory.points_to_build.set(len(trajectory.durations)),
            ]
        )
        await asyncio.gather(*coros)

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
