from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics.adcore import (
    ADHDFWriter,
    ADWriter,
    AreaDetector,
    NDPluginBaseIO,
)

from ._kinetix_controller import KinetixController
from ._kinetix_io import KinetixDriverIO


class KinetixDetector(AreaDetector[KinetixController]):
    """Ophyd-async implementation of an ADKinetix Detector.

    https://github.com/NSLS-II/ADKinetix.
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
    ):
        driver = KinetixDriverIO(prefix + drv_suffix)
        controller = KinetixController(driver)

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
