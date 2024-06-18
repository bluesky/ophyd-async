from enum import Enum

from bluesky.protocols import Hints

from ophyd_async.core import DirectoryProvider, StandardDetector
from ophyd_async.epics.adcore import ADBaseShapeProvider, HDFWriter, NDFileHDF

from ._pilatus_controller import PilatusController
from ._pilatus_driver import PilatusDriver


#: Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
#: The required minimum time difference between ExpPeriod and ExpTime
#: (readout time) is 2.28 ms
#: We provide an option to override for newer Pilatus models
class PilatusReadoutTime(float, Enum):
    """Pilatus readout time per model in ms"""

    # Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
    pilatus2 = 2.28e-3

    # Cite: https://media.dectris.com/user-manual-pilatus3-2020.pdf
    pilatus3 = 0.95e-3


class PilatusDetector(StandardDetector):
    """A Pilatus StandardDetector writing HDF files"""

    _controller: PilatusController
    _writer: HDFWriter

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        readout_time: PilatusReadoutTime = PilatusReadoutTime.pilatus3,
        drv_suffix: str = "cam1:",
        hdf_suffix: str = "HDF1:",
        name: str = "",
    ):
        self.drv = PilatusDriver(prefix + drv_suffix)
        self.hdf = NDFileHDF(prefix + hdf_suffix)

        super().__init__(
            PilatusController(self.drv, readout_time=readout_time.value),
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