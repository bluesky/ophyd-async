from collections.abc import Sequence

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics.adcore._core_detector import AreaDetector
from ophyd_async.epics.adcore._core_io import NDPluginBaseIO

# from ophyd_async.epics.adcore._core_logic import ad_driver_factory, ad_writer_factory
from ophyd_async.epics.adcore._core_writer import ADWriter
from ophyd_async.epics.adcore._hdf_writer import ADHDFWriter

from ._aravis_controller import AravisController


class AravisDetector(AreaDetector[AravisController, ADWriter]):
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
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, NDPluginBaseIO] = None,
    ):
        if plugins is None:
            plugins = {}
        controller, driver = AravisController.controller_and_drv(
            prefix + drv_suffix, gpio_number=gpio_number, name=name
        )

        super().__init__(
            prefix=prefix,
            driver=driver,
            controller=controller,
            writer_cls=writer_cls,
            fileio_suffix=fileio_suffix,
            path_provider=path_provider,
            plugins=plugins,
            name=name,
            config_sigs=config_sigs,
        )

        self.drv = driver
