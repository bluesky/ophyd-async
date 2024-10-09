from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore

from ._vimba_controller import VimbaController
from ._vimba_io import VimbaDriverIO


class VimbaDetector(adcore.AreaDetector):
    """
    Ophyd-async implementation of an ADVimba Detector.
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
            VimbaController,
            VimbaDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
        )
        self.hdf = self._fileio


class VimbaDetectorTIFF(adcore.AreaDetector):
    """
    Ophyd-async implementation of an ADVimba Detector.
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
            VimbaController,
            VimbaDriverIO,
            drv_suffix=drv_suffix,
            name=name,
            config_sigs=config_sigs,
        )
        self.tiff = self._fileio
