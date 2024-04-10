from typing import get_args

from bluesky.protocols import HasHints, Hints
from ophyd_async.core import (
    DirectoryProvider,
    StandardDetector,
    TriggerInfo,
)
from ophyd_async.epics.areadetector.controllers.aravis_controller import (
    ADAravisController,
)
from ophyd_async.epics.areadetector.drivers import ADBaseShapeProvider
from ophyd_async.epics.areadetector.drivers.aravis_driver import ADAravisDriver
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class ADAravisDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADAravis Detector.
    The detector may be configured for an external trigger on a GPIO port,
    which must be done prior to preparing the detector
    """

    _controller: ADAravisController
    _writer: HDFWriter

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        name: str,
        gpio_number: ADAravisController.GPIO_NUMBER = 1,
        **scalar_sigs: str,
    ):
        # Must be child of Detector to pick up connect()
        self.drv = ADAravisDriver(prefix + "DET:")
        self.hdf = NDFileHDF(prefix + "HDF5:")

        super().__init__(
            ADAravisController(self.drv, gpio_number=gpio_number),
            HDFWriter(
                self.hdf,
                directory_provider,
                lambda: self.name,
                ADBaseShapeProvider(self.drv),
                **scalar_sigs,
            ),
            config_sigs=(self.drv.acquire_time, self.drv.acquire),
            name=name,
        )

    async def _prepare(self, value: TriggerInfo) -> None:
        await self._controller._fetch_deadtime()
        await super()._prepare(value)

    def get_external_trigger_gpio(self):
        return self._controller.gpio_number

    def set_external_trigger_gpio(self, gpio_number: ADAravisController.GPIO_NUMBER):
        supported_gpio_numbers = get_args(ADAravisController.GPIO_NUMBER)
        if gpio_number not in supported_gpio_numbers:
            raise ValueError(
                f"{self.__class__.__name__} only supports the following GPIO "
                f"indices: {supported_gpio_numbers} but was asked to "
                f"use {gpio_number}"
            )
        self._controller.gpio_number = gpio_number

    @property
    def hints(self) -> Hints:
        return self._writer.hints
