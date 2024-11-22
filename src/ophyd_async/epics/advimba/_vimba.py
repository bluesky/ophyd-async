from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics.adcore import ADHDFWriter, ADWriter, AreaDetector, NDPluginBaseIO

from ._vimba_controller import VimbaController


class VimbaDetector(AreaDetector[VimbaController, ADWriter]):
    """
    Ophyd-async implementation of an ADVimba Detector.
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        plugins: dict[str, NDPluginBaseIO] = None,
        config_sigs: Sequence[SignalR] = (),
    ):
        if plugins is None:
            plugins = {}
        controller, driver = VimbaController.controller_and_drv(
            prefix + drv_suffix, name=name
        )

        super().__init__(
            prefix=prefix,
            driver=driver,
            controller=controller,
            writer_cls=writer_cls,
            path_provider=path_provider,
            plugins=plugins,
            name=name,
            fileio_suffix=fileio_suffix,
            config_sigs=config_sigs,
        )

        self.drv = driver
