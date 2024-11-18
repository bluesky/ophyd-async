from collections.abc import Sequence
from typing import get_args

from ophyd_async.core import PathProvider
from ophyd_async.core._detector import StandardDetector
from ophyd_async.core._signal import SignalR
from ophyd_async.epics import adcore

from ._aravis_controller import AravisController
from ._aravis_io import AravisDriverIO


class AravisDetector(StandardDetector[AravisController]):
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
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
        name="",
    ):
        self.drv, self.hdf, writer = adcore.areadetector_driver_and_hdf(
            drv_cls=AravisDriverIO,
            prefix=prefix,
            drv_suffix=drv_suffix,
            fileio_suffix=hdf_suffix,
            path_provider=path_provider,
        )
        super().__init__(
            controller=AravisController(self.drv, gpio_number),
            writer=writer,
            config_sigs=config_sigs,
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


class AravisDetectorTIFF(StandardDetector[AravisController]):
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
        tiff_suffix="TIFF1:",
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
        name="",
    ):
        self.drv, self.tiff, writer = adcore.areadetector_driver_and_tiff(
            drv_cls=AravisDriverIO,
            prefix=prefix,
            drv_suffix=drv_suffix,
            fileio_suffix=tiff_suffix,
            path_provider=path_provider,
        )
        super().__init__(
            controller=AravisController(self.drv, gpio_number),
            writer=writer,
            config_sigs=config_sigs,
            name=name,
        )
