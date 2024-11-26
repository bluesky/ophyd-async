from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore._core_io import ADBaseDatasetDescriber

from ._vimba_controller import VimbaController


class VimbaDetector(adcore.AreaDetector[VimbaController, adcore.ADWriter]):
    """
    Ophyd-async implementation of an ADVimba Detector.
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
    ):
        controller, driver = VimbaController.controller_and_drv(
            prefix + drv_suffix, name=name
        )
        writer, fileio = writer_cls.writer_and_io(
            prefix,
            path_provider,
            lambda: name,
            ADBaseDatasetDescriber(driver),
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
