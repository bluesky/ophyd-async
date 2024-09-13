import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorController,
    DetectorTrigger,
    wait_for_value,
)
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.core._status import AsyncStatus
from ophyd_async.epics import adcore

from ._pilatus_io import PilatusDriverIO, PilatusTriggerMode


class PilatusController(DetectorController):
    _supported_trigger_types = {
        DetectorTrigger.internal: PilatusTriggerMode.internal,
        DetectorTrigger.constant_gate: PilatusTriggerMode.ext_enable,
        DetectorTrigger.variable_gate: PilatusTriggerMode.ext_enable,
    }

    def __init__(
        self,
        driver: PilatusDriverIO,
        readout_time: float,
    ) -> None:
        self._drv = driver
        self._readout_time = readout_time
        self._arm_status: AsyncStatus | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        return self._readout_time

    async def prepare(self, trigger_info: TriggerInfo):
        if trigger_info.livetime is not None:
            await adcore.set_exposure_time_and_acquire_period_if_supplied(
                self, self._drv, trigger_info.livetime
            )
        await asyncio.gather(
            self._drv.trigger_mode.set(self._get_trigger_mode(trigger_info.trigger)),
            self._drv.num_images.set(
                999_999
                if trigger_info.total_number_of_triggers == 0
                else trigger_info.total_number_of_triggers
            ),
            self._drv.image_mode.set(adcore.ImageMode.multiple),
        )

    async def arm(self):
        # Standard arm the detector and wait for the acquire PV to be True
        self._arm_status = await adcore.start_acquiring_driver_and_ensure_status(
            self._drv
        )
        # The pilatus has an additional PV that goes True when the camserver
        # is actually ready. Should wait for that too or we risk dropping
        # a frame
        await wait_for_value(
            self._drv.armed,
            True,
            timeout=DEFAULT_TIMEOUT,
        )

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    @classmethod
    def _get_trigger_mode(cls, trigger: DetectorTrigger) -> PilatusTriggerMode:
        if trigger not in cls._supported_trigger_types.keys():
            raise ValueError(
                f"{cls.__name__} only supports the following trigger "
                f"types: {cls._supported_trigger_types.keys()} but was asked to "
                f"use {trigger}"
            )
        return cls._supported_trigger_types[trigger]

    async def disarm(self):
        await adcore.stop_busy_record(self._drv.acquire, False, timeout=1)
