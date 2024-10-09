from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore

from ._kinetix_controller import KinetixController
from ._kinetix_io import KinetixDriverIO


class KinetixDetector(adcore.AreaDetector):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
        config_sigs: Sequence[SignalR] = (),
    ):
        super().__init__(
            prefix,
            path_provider,
            adcore.ADHDFWriter,
            hdf_suffix,
            KinetixController,
            KinetixDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
        )
        self.hdf = self._fileio


class KinetixDetectorTIFF(adcore.AreaDetector):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        tiff_suffix="TIFF1:",
        name="",
        config_sigs: Sequence[SignalR] = (),
    ):
        super().__init__(
            prefix,
            path_provider,
            adcore.ADTIFFWriter,
            tiff_suffix,
            KinetixController,
            KinetixDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
        )
        self.tiff = self._fileio
