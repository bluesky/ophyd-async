from collections.abc import Sequence

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics.adcore._core_detector import AreaDetector
from ophyd_async.epics.adcore._core_io import NDPluginBaseIO
from ophyd_async.epics.adcore._core_writer import ADWriter
from ophyd_async.epics.adcore._hdf_writer import ADHDFWriter

from ._pilatus_controller import PilatusController


class PilatusDetector(AreaDetector[PilatusController, ADWriter]):
    """A Pilatus StandardDetector writing HDF files"""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        readout_time: float,
        drv_suffix: str = "cam1:",
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        plugins: dict[str, NDPluginBaseIO] = None,
        config_sigs: Sequence[SignalR] = (),
    ):
        if plugins is None:
            plugins = {}
        controller, driver = PilatusController.controller_and_drv(
            prefix + drv_suffix, name=name, readout_time=readout_time
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
