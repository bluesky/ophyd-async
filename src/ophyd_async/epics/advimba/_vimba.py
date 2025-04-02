from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore

from ._vimba_controller import VimbaController
from ._vimba_io import VimbaDriverIO


class VimbaDetector(adcore.AreaDetector[VimbaController]):
    """Ophyd-async implementation of an ADVimba Detector.

    https://github.com/areaDetector/ADVimba
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
        driver = VimbaDriverIO(prefix + drv_suffix)
        controller = VimbaController(driver)

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
