from bluesky.protocols import HasHints, Hints

from ophyd_async.core import DirectoryProvider, StandardDetector
from ophyd_async.epics.areadetector.controllers.vimba_controller import VimbaController
from ophyd_async.epics.areadetector.drivers import ADBaseShapeProvider
from ophyd_async.epics.areadetector.drivers.vimba_driver import VimbaDriver
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class VimbaDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADVimba Detector.
    """

    _controller: VimbaController
    _writer: HDFWriter

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        self.drv = VimbaDriver(prefix + drv_suffix)
        self.hdf = NDFileHDF(prefix + hdf_suffix)

        super().__init__(
            VimbaController(self.drv),
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
