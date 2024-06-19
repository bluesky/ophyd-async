from bluesky.protocols import HasHints, Hints

from ophyd_async.core import DirectoryProvider, StandardDetector
from ophyd_async.epics.adcore import ADBaseShapeProvider, HDFWriter, NDFileHDF

from ._kinetix_controller import KinetixController
from ._kinetix_io import KinetixDriverIO


class KinetixDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
    """

    _controller: KinetixController
    _writer: HDFWriter

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        self.drv = KinetixDriverIO(prefix + drv_suffix)
        self.hdf = NDFileHDF(prefix + hdf_suffix)

        super().__init__(
            KinetixController(self.drv),
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
