import asyncio
from enum import Enum

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorTrigger,
    TriggerInfo,
    wait_for_value,
)
from ophyd_async.epics import adcore

from ._pilatus_io import PilatusDriverIO, PilatusTriggerMode


class PilatusReadoutTime(float, Enum):
    """Pilatus readout time per model in ms."""

    # Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
    PILATUS2 = 2.28e-3

    # Cite: https://media.dectris.com/user-manual-pilatus3-2020.pdf
    PILATUS3 = 0.95e-3


class PilatusController(adcore.ADBaseController[PilatusDriverIO]):
    """`DetectorController` for a `PilatusDriverIO`."""

    _supported_trigger_types = {
        DetectorTrigger.INTERNAL: PilatusTriggerMode.INTERNAL,
        DetectorTrigger.CONSTANT_GATE: PilatusTriggerMode.EXT_ENABLE,
        DetectorTrigger.VARIABLE_GATE: PilatusTriggerMode.EXT_ENABLE,
        DetectorTrigger.EDGE_TRIGGER: PilatusTriggerMode.EXT_TRIGGER,
    }

    def __init__(
        self,
        driver: PilatusDriverIO,
        good_states: frozenset[adcore.ADState] = adcore.DEFAULT_GOOD_STATES,
        readout_time: float = PilatusReadoutTime.PILATUS3,
    ) -> None:
        super().__init__(driver, good_states=good_states)
        self._readout_time = readout_time

    def get_deadtime(self, exposure: float | None) -> float:
        return self._readout_time

    async def prepare(self, trigger_info: TriggerInfo):
        if trigger_info.livetime is not None:
            await self.set_exposure_time_and_acquire_period_if_supplied(
                trigger_info.livetime
            )
        await asyncio.gather(
            self.driver.trigger_mode.set(
                self._supported_trigger_types[trigger_info.trigger]
            ),
            self.driver.num_images.set(
                999_999
                if trigger_info.total_number_of_exposures == 0
                else trigger_info.total_number_of_exposures
            ),
            self.driver.image_mode.set(adcore.ADImageMode.MULTIPLE),
        )

    async def arm(self):
        # Standard arm the detector and wait for the acquire PV to be True
        self._arm_status = await self.start_acquiring_driver_and_ensure_status()

        # The pilatus has an additional PV that goes True when the camserver
        # is actually ready. Should wait for that too or we risk dropping
        # a frame
        await wait_for_value(
            self.driver.armed,
            True,
            timeout=DEFAULT_TIMEOUT,
        )
