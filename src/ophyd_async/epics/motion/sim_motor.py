import asyncio
import time
from typing import Callable, List

from ophyd_async.core import set_sim_value
from ophyd_async.epics.motion import Motor


class SimMotor(Motor):
    def __init__(self, prefix: str, name="", instant=True) -> None:
        """
        Simulated motor device

        args:
        - prefix: str: PV prefix
        - name: str: name of device
        - instant: bool: whether to move instantly, or with a delay
        """
        self._instant = instant

        super().__init__(prefix, name=name)

        # a useful default
        self.velocity.set(1)

    async def _move(self, new_position: float, watchers: List[Callable] = []):
        self._set_success = True
        start = time.monotonic()

        current_position = await self.user_readback.get_value()
        distance = abs(new_position - current_position)
        travel_time = 0 if self._instant else distance / await self.velocity.get_value()

        old_position, units, precision = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.motor_egu.get_value(),
            self.precision.get_value(),
        )

        async def update_position():
            while True:
                time_elapsed = time.monotonic() - start
                if time_elapsed >= travel_time:
                    current_position = new_position
                    break
                else:
                    current_position = (
                        old_position + distance * time_elapsed / travel_time
                    )

            set_sim_value(self.user_readback, current_position)
            await asyncio.sleep(0.1)

        def update_watchers(current_position: float):
            for watcher in watchers:
                watcher(
                    name=self.name,
                    current=current_position,
                    initial=old_position,
                    target=new_position,
                    unit=units,
                    precision=precision,
                    time_elapsed=time.monotonic() - start,
                )

        asyncio.create_task(update_position())

        self.user_readback.subscribe_value(update_watchers)
