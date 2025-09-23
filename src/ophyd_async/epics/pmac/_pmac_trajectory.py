import asyncio

import numpy as np
from scanspec.core import Path, Slice
from scanspec.specs import Spec

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    FlyerController,
    WatchableAsyncStatus,
    WatcherUpdate,
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


class PmacTrajectoryTriggerLogic(FlyerController):
    def __init__(self, pmac: PmacIO) -> None:
        self.pmac = pmac
        self.scantime: float | None = None
        self.path: Path | None = None
        self.next_pvt: PVT | None = None
        self.motor_info: _PmacMotorInfo | None = None
        self.trajectory_status: WatchableAsyncStatus | None = None

    async def prepare(self, value: Spec[Motor]):
        self.path = Path(value.calculate())
        slice = self.path.consume(SLICE_SIZE)
        motors = slice.axes()
        self.motor_info = await _PmacMotorInfo.from_motors(self.pmac, motors)
        ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
            slice, self.motor_info, True
        )
        await asyncio.gather(
            self._append_trajectory(slice, ramp_up_time),
            self._move_to_start(self.motor_info, ramp_up_pos),
        )

    async def _append_trajectory(self, slice: Slice, ramp_up_time: float | None = None):
        if self.motor_info is None or self.path is None:
            raise RuntimeError("Cannot append to trajectory. Must call prepare first.")

        trajectory, exit_pvt = Trajectory.from_slice(
            slice,
            self.motor_info,
            None if ramp_up_time else self.next_pvt,
            ramp_up_time=ramp_up_time,
        )

        if len(self.path) == 0:
            ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
                slice, self.motor_info, False
            )
            trajectory = trajectory.append_ramp_down(
                exit_pvt, ramp_down_pos, ramp_down_time, 0
            )
        self.next_pvt = exit_pvt
        await self._build_trajectory(
            trajectory, self.motor_info, append=False if ramp_up_time else True
        )

    @WatchableAsyncStatus.wrap
    async def _execute_trajectory(self):
        if self.path is None:
            raise RuntimeError("Cannot execute trajectory. Must call prepare first.")
        loaded = SLICE_SIZE
        execute_status = self.pmac.trajectory.execute_profile.set(True)
        async for current_point in observe_value(
            self.pmac.trajectory.total_points, done_status=execute_status
        ):
            if loaded - current_point < SLICE_SIZE:
                if len(self.path) != 0:
                    # We have less than SLICE_SIZE points in the buffer, so refill
                    await self._append_trajectory(self.path.consume(SLICE_SIZE))
                    loaded += SLICE_SIZE
            yield WatcherUpdate(
                current=current_point,
                initial=0,
                target=self.path.end_index,
                name=self.pmac.name,
            )

    async def kickoff(self):
        self.trajectory_status = self._execute_trajectory()
        # Wait for the ramp up to happen
        await wait_for_value(
            self.pmac.trajectory.total_points, lambda v: v >= 1, DEFAULT_TIMEOUT
        )

    async def complete(self):
        trajectory_status = error_if_none(
            self.trajectory_status, "Cannot complete. Must call kickoff first."
        )
        await trajectory_status

    async def stop(self):
        await self.pmac.trajectory.abort_profile.set(True)

    async def _build_trajectory(
        self, trajectory: Trajectory, motor_info: _PmacMotorInfo, append: bool
    ):
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
            self.pmac.trajectory.time_array.set(trajectory.durations / TICK_S),
            self.pmac.trajectory.user_array.set(trajectory.user_programs),
            self.pmac.trajectory.points_to_build.set(len(trajectory.durations)),
            self.pmac.trajectory.calculate_velocities.set(False),
        ] + [
            self.pmac.trajectory.use_axis[number].set(use)
            for number, use in use_axis.items()
        ]
        await asyncio.gather(*coros)
        if append:
            await self.pmac.trajectory.append_profile.set(True)
        else:
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
