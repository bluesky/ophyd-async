import asyncio
from typing import Optional

from ophyd_async.core import (DEFAULT_TIMEOUT, AsyncStatus, DetectorControl,
                              DetectorTrigger, wait_for_value)
from ophyd_async.epics import ImageMode, stop_busy_record
from ophyd_async.epics.adcore import start_acquiring_driver_and_ensure_status

from ._pilatus_io import PilatusDriverIO, PilatusTriggerMode


class PilatusController(DetectorControl):
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

    def get_deadtime(self, exposure: float) -> float:
        return self._readout_time

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        if exposure is not None:
            await self._drv.acquire_time.set(exposure)
        await asyncio.gather(
            self._drv.trigger_mode.set(self._get_trigger_mode(trigger)),
            self._drv.num_images.set(999_999 if num == 0 else num),
            self._drv.image_mode.set(ImageMode.multiple),
        )

        # Standard arm the detector and wait for the acquire PV to be True
        idle_status = await start_acquiring_driver_and_ensure_status(self._drv)

        # The pilatus has an additional PV that goes True when the camserver
        # is actually ready. Should wait for that too or we risk dropping
        # a frame
        await wait_for_value(
            self._drv.armed_for_triggers,
            True,
            timeout=DEFAULT_TIMEOUT,
        )

        return idle_status

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
        await stop_busy_record(self._drv.acquire, False, timeout=1)
