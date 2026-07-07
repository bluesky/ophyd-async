import asyncio
from dataclasses import dataclass

from ophyd_async.core import (
    DetectorTriggerLogic as _DetectorTriggerLogic,
)
from ophyd_async.core import (
    EnableDisable,
    TriggerInfo,
)

from ._io import ADBaseDataType, ADBaseIO, ADImageMode, NDCBFlushOnSoftTrgMode, NDCircularBuffIO, NDProcessIO, NDProcessFilterType, NDProcessFilterCallbacks


async def prepare_exposures(
    driver: ADBaseIO,
    num: int,
    livetime: float = 0.0,
    deadtime: float = 0.0,
) -> None:
    """Prepare the AD driver for a given number of exposures with specified livetime and deadtime.
    
    :param driver: The ADBaseIO driver instance
    :param num: Number of exposures to prepare
    :param livetime: Exposure time for each image (default: 0.0)
    :param deadtime: Deadtime between exposures (default: 0.0)
    """
    image_mode = ADImageMode.CONTINUOUS if num == 0 else ADImageMode.MULTIPLE
    coros = [
        driver.image_mode.set(image_mode),
        driver.num_images.set(num),
    ]
    if livetime:
        coros.append(driver.acquire_time.set(livetime))
        if deadtime:
            coros.append(driver.acquire_period.set(livetime + deadtime))
    await asyncio.gather(*coros)


async def prepare_exposures_per_collection(
    process_plugin: NDProcessIO,
    exposures_per_collection: int = 1,
    filter_type: NDProcessFilterType = NDProcessFilterType.AVERAGE,
) -> None:
    """Prepare the AD process plugin for a given number of exposures per collection.
    
    :param process_plugin: The NDProcessIO plugin instance (optional)
    :param exposures_per_collection: Number of exposures per collection (default: 1)
    """
    coros = [
        process_plugin.num_filter.set(exposures_per_collection),
        process_plugin.enable_filter.set(True),
        process_plugin.filter_type.set(filter_type),
        process_plugin.auto_reset_filter.set(True),
        process_plugin.data_type_out.set(ADBaseDataType.AUTOMATIC),
        process_plugin.filter_callbacks.set(NDProcessFilterCallbacks.ARRAY_N_ONLY),
    ]
    await asyncio.gather(*coros)


async def trigger_info_from_num_images(driver: ADBaseIO, process_plugin: NDProcessIO | None = None) -> TriggerInfo:
    """Default TriggerInfo for AD detectors, reading num_images from the driver."""
    num_images = await driver.num_images.get_value()
    if process_plugin is not None:
        exposures_per_collection = await process_plugin.num_filter.get_value()
        collections_per_event = max(1, num_images // exposures_per_collection)
        return TriggerInfo(collections_per_event=collections_per_event)
    return TriggerInfo(collections_per_event=max(1, num_images))


@dataclass
class ADContAcqTriggerLogic(_DetectorTriggerLogic):
    driver: ADBaseIO
    cb_plugin: NDCircularBuffIO
    process_plugin: NDProcessIO | None = None

    async def _ensure_driver_acquiring(self, livetime: float):
        # Check the current state of the system
        image_mode, acquiring, acquire_time = await asyncio.gather(
            self.driver.image_mode.get_value(),
            self.driver.acquire.get_value(),
            self.driver.acquire_time.get_value(),
        )
        # Ensure the detector is in continuous acquisition mode
        if image_mode != ADImageMode.CONTINUOUS or not acquiring:
            raise RuntimeError(
                "Driver must be acquiring in continuous mode to use the "
                "cont acq interface"
            )
        # Not all detectors allow for changing exposure times during an acquisition,
        # so in this least-common-denominator implementation check to see if
        # exposure time matches the current exposure time.
        if livetime and livetime != acquire_time:
            raise ValueError(
                f"Detector exposure time currently set to {acquire_time}, "
                f"but requested exposure is {livetime}"
            )

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self._ensure_driver_acquiring(livetime)
        # Setup the CB plugin with the current parameters
        await asyncio.gather(
            self.cb_plugin.enable_callbacks.set(EnableDisable.ENABLE),
            self.cb_plugin.pre_count.set(0),
            self.cb_plugin.post_count.set(num),
            self.cb_plugin.preset_trigger_count.set(1),
            self.cb_plugin.flush_on_soft_trg.set(NDCBFlushOnSoftTrgMode.ON_NEW_IMAGE),
        )

    async def prepare_exposures_per_collection(self, exposures_per_collection: int):
        if self.process_plugin is not None:
            await prepare_exposures_per_collection(self.process_plugin, exposures_per_collection)

    async def default_trigger_info(self) -> TriggerInfo:
        # Read post_count (not driver.num_images) because the CB plugin's
        # post_count is what governs how many frames are buffered per trigger
        # in continuous-acquisition mode, not the driver's num_images.
        num = await self.cb_plugin.post_count.get_value()
        return TriggerInfo(collections_per_event=max(1, num))
