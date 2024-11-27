from bluesky.protocols import Hints

from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.epics.adcore import ADBaseDatasetDescriber, ADHDFWriter, NDFileHDFIO

from ._andor_controller import Andor2Controller
from ._andor_io import Andor2DriverIO


class Andor2Detector(StandardDetector):
    """
    Andor 2 area detector device (CCD detector 56fps with full chip readout).
    Andor model:DU897_BV.
    """

    _controller: Andor2Controller
    _writer: ADHDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        self.drv = Andor2DriverIO(prefix + drv_suffix)
        self.hdf = NDFileHDFIO(prefix + hdf_suffix)
        super().__init__(
            Andor2Controller(self.drv),
            ADHDFWriter(
                self.hdf,
                path_provider,
                lambda: self.name,
                ADBaseDatasetDescriber(self.drv),
            ),
            config_sigs=(self.drv.acquire_time,),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
