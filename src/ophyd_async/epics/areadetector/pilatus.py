from bluesky.protocols import Hints

from ophyd_async.core import DirectoryProvider
from ophyd_async.core.detector import StandardDetector
from ophyd_async.epics.areadetector.controllers.pilatus_controller import (
    PilatusController,
)
from ophyd_async.epics.areadetector.drivers.ad_base import ADBaseShapeProvider
from ophyd_async.epics.areadetector.drivers.pilatus_driver import PilatusDriver
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF

#: Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
#: The required minimum time difference between ExpPeriod and ExpTime
#: (readout time) is 2.28 ms
#: We provide an option to override for newer Pilatus models
DEFAULT_READOUT_TIME_SECONDS: float = 2.28e-3


class PilatusDetector(StandardDetector):
    """A Pilatus StandardDetector writing HDF files"""

    _controller: PilatusController
    _writer: HDFWriter

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        readout_time: float = DEFAULT_READOUT_TIME_SECONDS,
        drv_suffix: str = "cam1:",
        hdf_suffix: str = "HDF1:",
        name: str = "",
    ):
        self.drv = PilatusDriver(prefix + drv_suffix)
        self.hdf = NDFileHDF(prefix + hdf_suffix)

        super().__init__(
            PilatusController(self.drv, readout_time=readout_time),
            HDFWriter(
                self.hdf,
                directory_provider,
                lambda: self.name,
                ADBaseShapeProvider(self.drv),
            ),
            config_sigs=(self.drv.acquire_time,),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
