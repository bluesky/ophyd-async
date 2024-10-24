from bluesky.protocols import HasHints, Hints

from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.epics import adcore

from ._kinetix_controller import KinetixController
from ._kinetix_io import KinetixDriverIO


class KinetixDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
    """

    _controller: KinetixController
    _writer: adcore.ADHDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        self.drv = KinetixDriverIO(prefix + drv_suffix)
        self.hdf = adcore.NDFileHDFIO(prefix + hdf_suffix)

        super().__init__(
            KinetixController(self.drv),
            adcore.ADHDFWriter(
                self.hdf,
                path_provider,
                lambda: self.name,
                adcore.ADBaseDatasetDescriber(self.drv),
            ),
            config_sigs=(self.drv.acquire_time,),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
