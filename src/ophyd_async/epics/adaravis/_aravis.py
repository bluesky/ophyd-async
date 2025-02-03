from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore

from ._aravis_controller import AravisController
from ._aravis_io import AravisDriverIO


class AravisDetector(adcore.AreaDetector[AravisController]):
    """Implementation of an ADAravis Detector.

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
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
    ):
        driver = AravisDriverIO(prefix + drv_suffix)
        controller = AravisController(driver)
        writer = writer_cls.with_io(
            prefix,
            path_provider,
            dataset_source=driver,
            fileio_suffix=fileio_suffix,
            plugins=plugins,
        )
        super().__init__(
            controller=controller,
            writer=writer,
            plugins=plugins,
            name=name,
            config_sigs=config_sigs,
        )
