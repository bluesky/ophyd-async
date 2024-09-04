from typing import get_args

from bluesky.protocols import HasHints, Hints

from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.epics import adcore

from ._aravis_controller import AravisController
from ._aravis_io import AravisDriverIO


class AravisDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADAravis Detector.
    The detector may be configured for an external trigger on a GPIO port,
    which must be done prior to preparing the detector
    """

    _controller: AravisController
    _writer: adcore.ADHDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
        gpio_number: AravisController.GPIO_NUMBER = 1,
    ):
        self.drv = AravisDriverIO(prefix + drv_suffix)
        self.hdf = adcore.NDFileHDFIO(prefix + hdf_suffix)

        super().__init__(
            AravisController(self.drv, gpio_number=gpio_number),
            adcore.ADHDFWriter(
                self.hdf,
                path_provider,
                lambda: self.name,
                adcore.ADBaseDatasetDescriber(self.drv),
            ),
            config_sigs=(self.drv.acquire_time,),
            name=name,
        )

    def get_external_trigger_gpio(self):
        return self._controller.gpio_number

    def set_external_trigger_gpio(self, gpio_number: AravisController.GPIO_NUMBER):
        supported_gpio_numbers = get_args(AravisController.GPIO_NUMBER)
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
