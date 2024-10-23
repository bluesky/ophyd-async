from collections.abc import Sequence
from typing import cast, get_args

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics import adcore

from ._aravis_controller import AravisController
from ._aravis_io import AravisDriverIO


class AravisDetector(adcore.AreaDetector):
    """
    Ophyd-async implementation of an ADAravis Detector.
    The detector may be configured for an external trigger on a GPIO port,
    which must be done prior to preparing the detector
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
    ):
        super().__init__(
            prefix,
            path_provider,
            adcore.ADHDFWriter,
            hdf_suffix,
            AravisController,
            AravisDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
            gpio_number=gpio_number,
        )
        self.hdf = self._fileio

    @property
    def controller(self) -> AravisController:
        return cast(AravisController, self._controller)

    def get_external_trigger_gpio(self):
        return self.controller.gpio_number

    def set_external_trigger_gpio(self, gpio_number: AravisController.GPIO_NUMBER):
        supported_gpio_numbers = get_args(AravisController.GPIO_NUMBER)
        if gpio_number not in supported_gpio_numbers:
            raise ValueError(
                f"{self.__class__.__name__} only supports the following GPIO "
                f"indices: {supported_gpio_numbers} but was asked to "
                f"use {gpio_number}"
            )
        self.controller.gpio_number = gpio_number


class AravisDetectorTIFF(adcore.AreaDetector):
    """
    Ophyd-async implementation of an ADAravis Detector.
    The detector may be configured for an external trigger on a GPIO port,
    which must be done prior to preparing the detector
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
    ):
        super().__init__(
            prefix,
            path_provider,
            adcore.ADTIFFWriter,
            hdf_suffix,
            AravisController,
            AravisDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
            gpio_number=gpio_number,
        )
        self.tiff = self._fileio
