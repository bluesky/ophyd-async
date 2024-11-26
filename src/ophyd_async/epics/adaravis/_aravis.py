from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore

from ._aravis_controller import AravisController
from ._aravis_io import AravisDriverIO


class AravisDetector(adcore.AreaDetector[AravisController]):
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
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
    ):
        driver = AravisDriverIO(prefix + drv_suffix)
        controller = AravisController(driver, gpio_number=gpio_number)
        writer = writer_cls.with_io(
            prefix, fileio_suffix, path_provider, driver, plugins
        )
        super().__init__(driver, controller, writer, plugins, config_sigs, name)
