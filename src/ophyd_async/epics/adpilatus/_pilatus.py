from collections.abc import Sequence

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics.adcore._core_detector import AreaDetector
from ophyd_async.epics.adcore._core_io import NDPluginBaseIO
from ophyd_async.epics.adcore._core_writer import ADWriter
from ophyd_async.epics.adcore._hdf_writer import ADHDFWriter

from ._pilatus_controller import PilatusController, PilatusReadoutTime
from ._pilatus_io import PilatusDriverIO


class PilatusDetector(AreaDetector[PilatusController]):
    """A Pilatus StandardDetector writing HDF files."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        readout_time: PilatusReadoutTime = PilatusReadoutTime.PILATUS3,
        drv_suffix: str = "cam1:",
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
    ):
        driver = PilatusDriverIO(prefix + drv_suffix)
        controller = PilatusController(driver, readout_time=readout_time)

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
