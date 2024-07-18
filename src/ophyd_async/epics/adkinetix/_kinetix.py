from bluesky.protocols import HasHints, Hints

from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.epics import adcore

from ._kinetix_controller import KinetixController
from ._kinetix_driver import KinetixDriver


class KinetixDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
    """

    _controller: KinetixController
    _writer: adcore.HDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        self.drv = KinetixDriver(prefix + drv_suffix)
        self.hdf = adcore.NDFileHDF(prefix + hdf_suffix)

        super().__init__(
            KinetixController(self.drv),
            adcore.HDFWriter(
                self.hdf,
                path_provider,
                lambda: self.name,
                adcore.ADBaseShapeProvider(self.drv),
            ),
            config_sigs=(self.drv.acquire_time,),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
