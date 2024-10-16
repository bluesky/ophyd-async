from collections.abc import Sequence
from enum import Enum

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics import adcore

from ._pilatus_controller import PilatusController
from ._pilatus_io import PilatusDriverIO


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


class PilatusDetector(adcore.AreaDetector):
    """A Pilatus StandardDetector writing HDF files"""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        hdf_suffix: str = "HDF1:",
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
        readout_time: PilatusReadoutTime = PilatusReadoutTime.pilatus3,
    ):
        super().__init__(
            prefix,
            path_provider,
            adcore.ADHDFWriter,
            hdf_suffix,
            PilatusController,
            PilatusDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
            readout_time=readout_time,
        )
        self.hdf = self._fileio


class PilatusDetectorTIFF(adcore.AreaDetector):
    """A Pilatus StandardDetector writing HDF files"""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        tiff_suffix: str = "TIFF1:",
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
        readout_time: PilatusReadoutTime = PilatusReadoutTime.pilatus3,
    ):
        super().__init__(
            prefix,
            path_provider,
            adcore.ADTIFFWriter,
            tiff_suffix,
            PilatusController,
            PilatusDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
            readout_time=readout_time,
        )
        self.tiff = self._fileio
