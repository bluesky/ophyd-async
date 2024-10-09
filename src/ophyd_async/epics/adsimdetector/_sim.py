from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore


class SimDetector(adcore.AreaDetector):

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        hdf_suffix:str="HDF1:",
        drv_suffix:str="cam1:",
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
    ):

        super().__init__(
            prefix,
            path_provider,
            adcore.ADHDFWriter,
            hdf_suffix,
            adcore.ADBaseController,
            adcore.ADBaseIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
        )
        self.hdf = self._fileio


class SimDetectorTIFF(adcore.AreaDetector):

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        tiff_suffix:str="TIFF1:",
        drv_suffix:str="cam1:",
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
    ):

        super().__init__(
            prefix,
            path_provider,
            adcore.ADTIFFWriter,
            tiff_suffix,
            adcore.ADBaseController,
            adcore.ADBaseIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
        )
        self.tiff = self._fileio
