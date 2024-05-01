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
        name: str,
        directory_provider: DirectoryProvider,
        driver: VimbaDriver,
        hdf: NDFileHDF,
        **scalar_sigs: str,
    ):
        # Must be child of Detector to pick up connect()
        self.drv = driver
        self.hdf = hdf

        super().__init__(
            VimbaController(self.drv),
            HDFWriter(
                self.hdf,
                directory_provider,
                lambda: self.name,
                ADBaseShapeProvider(self.drv),
                **scalar_sigs,
            ),
            config_sigs=(self.drv.acquire_time, self.drv.acquire),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
