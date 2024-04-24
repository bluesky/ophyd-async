from bluesky.protocols import HasHints, Hints

from ophyd_async.core import DirectoryProvider, StandardDetector
from ophyd_async.epics.areadetector.controllers.kinetix_controller import (
    KinetixController,
)
from ophyd_async.epics.areadetector.drivers import ADBaseShapeProvider
from ophyd_async.epics.areadetector.drivers.kinetix_driver import KinetixDriver
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class KinetixDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
    """

    _controller: KinetixController
    _writer: HDFWriter

    def __init__(
        self,
        name: str,
        directory_provider: DirectoryProvider,
        driver: KinetixDriver,
        hdf: NDFileHDF,
        **scalar_sigs: str,
    ):
        # Must be child of Detector to pick up connect()
        self.drv = driver
        self.hdf = hdf

        super().__init__(
            KinetixController(self.drv),
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
