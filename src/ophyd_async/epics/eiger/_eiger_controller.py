import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorController,
    DetectorTrigger,
    set_and_wait_for_other_value,
)
from ophyd_async.core._detector import TriggerInfo

from ._eiger_io import EigerDriverIO, EigerTriggerMode

EIGER_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: EigerTriggerMode.internal,
    DetectorTrigger.constant_gate: EigerTriggerMode.gate,
    DetectorTrigger.variable_gate: EigerTriggerMode.gate,
    DetectorTrigger.edge_trigger: EigerTriggerMode.edge,
}


class EigerController(DetectorController):
    def __init__(
        self,
        driver: EigerDriverIO,
    ) -> None:
        self._drv = driver

    def get_deadtime(self, exposure: float | None) -> float:
        # See https://media.dectris.com/filer_public/30/14/3014704e-5f3b-43ba-8ccf-8ef720e60d2a/240202_usermanual_eiger2.pdf
        return 0.0001

    async def set_energy(self, energy: float, tolerance: float = 0.1):
        """Changing photon energy takes some time so only do so if the current energy is
        outside the tolerance."""
        current_energy = await self._drv.photon_energy.get_value()
        if abs(current_energy - energy) > tolerance:
            await self._drv.photon_energy.set(energy)

    async def prepare(self, trigger_info: TriggerInfo):
        coros = [
            self._drv.trigger_mode.set(
                EIGER_TRIGGER_MODE_MAP[trigger_info.trigger].value
            ),
            self._drv.num_images.set(trigger_info.total_number_of_triggers),
        ]
        if trigger_info.livetime is not None:
            coros.extend(
                [
                    self._drv.acquire_time.set(trigger_info.livetime),
                    self._drv.acquire_period.set(trigger_info.livetime),
                ]
            )
        await asyncio.gather(*coros)

    async def arm(self):
        # TODO: Detector state should be an enum see https://github.com/DiamondLightSource/eiger-fastcs/issues/43
        self._arm_status = set_and_wait_for_other_value(
            self._drv.arm, 1, self._drv.state, "ready", timeout=DEFAULT_TIMEOUT
        )

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        await self._drv.disarm.set(1)
