import asyncio
from enum import Enum
from typing import TypeVar, get_args

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorTrigger,
    TriggerInfo,
    wait_for_value,
)
from ophyd_async.epics import adcore

from ._pilatus_io import PilatusDriverIO, PilatusTriggerMode


#: Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
#: The required minimum time difference between ExpPeriod and ExpTime
#: (readout time) is 2.28 ms
#: We provide an option to override for newer Pilatus models
class PilatusReadoutTime(float, Enum):
    """Pilatus readout time per model in ms"""

    # Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
    PILATUS2 = 2.28e-3

    # Cite: https://media.dectris.com/user-manual-pilatus3-2020.pdf
    PILATUS3 = 0.95e-3


PilatusControllerT = TypeVar("PilatusControllerT", bound="PilatusController")


class PilatusController(adcore.ADBaseController[PilatusDriverIO]):
    """Controller for ADPilatus detector."""

    _supported_trigger_types = {
        DetectorTrigger.INTERNAL: PilatusTriggerMode.INTERNAL,
        DetectorTrigger.CONSTANT_GATE: PilatusTriggerMode.EXT_ENABLE,
        DetectorTrigger.VARIABLE_GATE: PilatusTriggerMode.EXT_ENABLE,
    }

    def __init__(
        self,
        driver: PilatusDriverIO,
        good_states: frozenset[adcore.DetectorState] = adcore.DEFAULT_GOOD_STATES,
        readout_time: float = PilatusReadoutTime.PILATUS3,
    ) -> None:
        super().__init__(driver, good_states=good_states)
        self._readout_time = readout_time

    @classmethod
    def controller_and_drv(
        cls: type[PilatusControllerT],
        prefix: str,
        good_states: frozenset[adcore.DetectorState] = adcore.DEFAULT_GOOD_STATES,
        name: str = "",
        readout_time: float = PilatusReadoutTime.PILATUS3,
    ) -> tuple[PilatusControllerT, PilatusDriverIO]:
        driver_cls = get_args(cls.__orig_bases__[0])[0]  # type: ignore
        driver = driver_cls(prefix, name=name)
        controller = cls(driver, good_states=good_states, readout_time=readout_time)
        return controller, driver

    def get_deadtime(self, exposure: float | None) -> float:
        return self._readout_time

    async def prepare(self, trigger_info: TriggerInfo):
        if trigger_info.livetime is not None:
            await self.set_exposure_time_and_acquire_period_if_supplied(
                trigger_info.livetime
            )
        await asyncio.gather(
            self.driver.trigger_mode.set(self._get_trigger_mode(trigger_info.trigger)),
            self.driver.num_images.set(
                999_999
                if trigger_info.total_number_of_triggers == 0
                else trigger_info.total_number_of_triggers
            ),
            self.driver.image_mode.set(adcore.ImageMode.MULTIPLE),
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

    @classmethod
    def _get_trigger_mode(cls, trigger: DetectorTrigger) -> PilatusTriggerMode:
        if trigger not in cls._supported_trigger_types.keys():
            raise ValueError(
                f"{cls.__name__} only supports the following trigger "
                f"types: {cls._supported_trigger_types.keys()} but was asked to "
                f"use {trigger}"
            )
        return cls._supported_trigger_types[trigger]
