from collections.abc import Sequence

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics import adcore

from ._aravis_controller import AravisController


class AravisDetector(adcore.AreaDetector[AravisController, adcore.ADWriter]):
    """
    Ophyd-async implementation of an ADAravis Detector.
    The detector may be configured for an external trigger on a GPIO port,
    which must be done prior to preparing the detector
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        gpio_number: AravisController.GPIO_NUMBER = 1,
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
        use_fileio_for_ds_describer: bool = False,
    ):
        controller, driver = AravisController.controller_and_drv(
            prefix + drv_suffix, gpio_number=gpio_number, name=name
        )
        writer, fileio = writer_cls.writer_and_io(
            prefix,
            path_provider,
            lambda: name,
            ds_describer_source=driver if not use_fileio_for_ds_describer else None,
            fileio_suffix=fileio_suffix,
            plugins=plugins,
        )

        super().__init__(
            driver=driver,
            controller=controller,
            fileio=fileio,
            writer=writer,
            plugins=plugins,
            name=name,
            config_sigs=config_sigs,
        )
        self.drv = driver
        self.fileio = fileio
