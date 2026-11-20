import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import numpy as np
from scanspec.core import Path, Slice
from scanspec.specs import Spec

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    KICKED_OFF,
    FlyableLogic,
    SignalR,
    gather_dict,
    observe_value,
    set_and_wait_for_value,
    wait_for_value,
)
from ophyd_async.epics.motor import Motor

from ._pmac_io import CS_INDEX, PmacExecuteState, PmacIO, PmacStatus
from ._pmac_trajectory_generation import (
    PVT,
    Trajectory,
    UserProgram,
    _get_velocity_profile,
)
from ._utils import (
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
class PmacScanInfo:
    spec: Spec[Motor]
    ramp_time: float | None
    turnaround_time: float | None


@dataclass
class PmacPrepareCtx:
    """What a PMAC fly scan needs after `prepare_to_fly` has worked it out."""

    #: The path to fly, consumed a slice at a time as the trajectory runs.
    path: Path
    #: The first slice of the path, which is built into the trajectory to start with.
    first_slice: Slice
    #: How many points of the path are left after the first slice.
    path_length: int
    motor_info: _PmacMotorInfo
    ramp_up_pos: dict[Motor, np.float64]
    ramp_up_time: float
    turnaround_time: float | None
    #: The PVT the last built slice exited at, which the next slice starts from.
    next_pvt: PVT | None = None
    #: The number of points loaded into the PMAC so far.
    loaded: int = 0


class PmacTrajectoryFlyableLogic(FlyableLogic[PmacScanInfo, PmacPrepareCtx]):
    def __init__(self, pmac: PmacIO) -> None:
        self.pmac = pmac

    async def prepare_to_fly(
        self, name: str, value: PmacScanInfo, previous_ctx: PmacPrepareCtx | None
    ) -> AsyncGenerator[PmacPrepareCtx, None]:
        path = Path(value.spec.calculate())
        first_slice = path.consume(SLICE_SIZE)
        motor_info = await _PmacMotorInfo.from_motors(self.pmac, first_slice.axes())
        ramp_up_pos, ramp_up_time = calculate_ramp_position_and_duration(
            first_slice, motor_info, True, value.ramp_time
        )
        ctx = PmacPrepareCtx(
            path=path,
            first_slice=first_slice,
            path_length=len(path),
            motor_info=motor_info,
            ramp_up_pos=ramp_up_pos,
            ramp_up_time=ramp_up_time,
            turnaround_time=value.turnaround_time,
        )
        yield ctx
        await asyncio.gather(
            self._build_trajectory(ctx),
            self._move_to_start(ctx.motor_info, ctx.ramp_up_pos),
        )

    async def fly(self, ctx: PmacPrepareCtx) -> AsyncGenerator[KICKED_OFF, None]:
        """Execute the trajectory, appending the rest of the path as it runs."""
        trajectory = self.pmac.trajectory
        async with trajectory.execute_profile.set(True, timeout=None) as execute:
            # Wait for the ramp up to happen
            await wait_for_value(
                trajectory.total_points,
                lambda v: v >= 1,
                ctx.ramp_up_time + DEFAULT_TIMEOUT,
            )
            yield KICKED_OFF
            # We consume SLICE_SIZE from self.path and parse a trajectory
            # containing at least 2 * SLICE_SIZE, as a gapless trajectory
            # will contain 2 points per slice frame. If gaps are present,
            # additional points are inserted, overfilling the buffer.
            min_buffer_size = SLICE_SIZE * 2
            async for current_point in observe_value(
                trajectory.total_points,
                done_status=execute,
                # Limit on PMAC is 4 seconds between points
                # Thus this timeout is fine.
                timeout=DEFAULT_TIMEOUT,
            ):
                # Keep a minimum buffer size, if we have more points to append
                if len(ctx.path) != 0 and ctx.loaded - current_point < min_buffer_size:
                    # Less than SLICE_SIZE * 2 points in the buffer, so refill
                    next_slice = ctx.path.consume(SLICE_SIZE)
                    await self._append_trajectory(ctx, next_slice, len(ctx.path))
        await self._check_profile_status(
            trajectory.execute_status, trajectory.execute_message
        )

    async def ensure_stopped(self) -> None:
        """Abort the trajectory if one is running, and wait until it has stopped."""
        trajectory = self.pmac.trajectory
        if await trajectory.execute_state.get_value() == PmacExecuteState.EXECUTING:
            await trajectory.abort_profile.trigger()
            await wait_for_value(
                trajectory.execute_state,
                lambda v: v != PmacExecuteState.EXECUTING,
                timeout=DEFAULT_TIMEOUT,
            )

    async def ensure_ready(self) -> None:
        """Stop, then run an empty fly scan to reset EQU on Panda Brick."""
        await self.ensure_stopped()
        for use_axis in self.pmac.trajectory.use_axis.values():
            await use_axis.set(False)

        await asyncio.gather(
            self.pmac.trajectory.time_array.set(np.array([0])),
            self.pmac.trajectory.user_array.set(np.array([UserProgram.END])),
            self.pmac.trajectory.points_to_build.set(1),
        )
        await self.pmac.trajectory.build_profile.trigger()
        await self.pmac.trajectory.execute_profile.set(True)

    async def _check_profile_status(
        self,
        status_signal: SignalR,
        message_signal: SignalR,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        status = None
        try:
            async for status in observe_value(status_signal, done_timeout=timeout):
                if status is PmacStatus.SUCCESS:
                    return
        except TimeoutError as exc:
            if status is not None:
                message = await message_signal.get_value()
                raise ValueError(
                    f"PMAC profile {status_signal.name} '{status}' "
                    f"is not in good end state of '{PmacStatus.SUCCESS}'. "
                    f"Message reported from pmac is: '{message}'"
                ) from exc
            else:
                raise TimeoutError(
                    f"Could not monitor PMAC status: {status_signal.source} "
                ) from exc

    async def _append_trajectory(
        self, ctx: PmacPrepareCtx, slice: Slice, path_length: int
    ):
        trajectory = await self._parse_trajectory(ctx, slice, path_length, None)
        await self._set_trajectory_arrays(trajectory, ctx.motor_info)
        await self.pmac.trajectory.append_profile.trigger()

        await self._check_profile_status(
            self.pmac.trajectory.append_status,
            self.pmac.trajectory.append_message,
        )

    async def _build_trajectory(self, ctx: PmacPrepareCtx):
        motor_info = ctx.motor_info
        trajectory = await self._parse_trajectory(
            ctx, ctx.first_slice, ctx.path_length, ctx.ramp_up_time
        )
        use_axis = {
            i: (i in motor_info.motor_cs_index.values()) for i in CS_INDEX.values()
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
        await self._check_profile_status(
            self.pmac.trajectory.build_status,
            self.pmac.trajectory.build_message,
        )

    async def _parse_trajectory(
        self,
        ctx: PmacPrepareCtx,
        slice: Slice,
        path_length: int,
        ramp_up_time: float | None = None,
    ) -> Trajectory:
        motor_info = ctx.motor_info
        trajectory, exit_pvt = Trajectory.from_slice(
            slice,
            motor_info,
            None if ramp_up_time else ctx.next_pvt,
            ramp_up_time=ramp_up_time,
            turnaround_time=ctx.turnaround_time,
        )

        if path_length == 0:
            ramp_down_pos, ramp_down_time = calculate_ramp_position_and_duration(
                slice, motor_info, False
            )
            trajectory = trajectory.with_ramp_down(
                exit_pvt, ramp_down_pos, ramp_down_time, 0
            )
        ctx.next_pvt = exit_pvt
        ctx.loaded += len(trajectory)

        return trajectory

    async def _set_trajectory_arrays(
        self, trajectory: Trajectory, motor_info: _PmacMotorInfo
    ):
        coros = []
        for motor, cs_index in motor_info.motor_cs_index.items():
            coros.append(
                self.pmac.trajectory.positions[cs_index].set(
                    trajectory.positions[motor]
                )
            )
            coros.append(
                self.pmac.trajectory.velocities[cs_index].set(
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

        motors = list(ramp_up_position.keys())

        motor_readbacks = await gather_dict(
            {motor: motor.user_readback.get_value() for motor in motors}
        )

        start_and_end_velocities = {motor: np.float64(0) for motor in motors}
        distances = {
            motor: float(abs(final_position - motor_readbacks[motor]))
            for motor, final_position in ramp_up_position.items()
        }
        time_arrays, _ = _get_velocity_profile(
            motors=motors,
            motor_info=motor_info,
            start_velocities=start_and_end_velocities,
            end_velocities=start_and_end_velocities,
            distances=distances,
        )

        # Get final timestamp for arbitrary motor
        # as this is the total time required for all motors
        longest_move_time = time_arrays[motors[0]][-1]

        for motor, position in ramp_up_position.items():
            coros.append(
                set_and_wait_for_value(
                    coord.cs_axis_setpoint[motor_info.motor_cs_index[motor]],
                    position,
                    set_timeout=longest_move_time + DEFAULT_TIMEOUT,
                    wait_for_set_completion=False,
                )
            )
        statuses = await asyncio.gather(*coros)
        await coord.defer_moves.set(False)
        await asyncio.gather(*statuses)
