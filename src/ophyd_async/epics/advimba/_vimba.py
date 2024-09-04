from bluesky.protocols import HasHints, Hints

from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.epics import adcore

from ._vimba_controller import VimbaController
from ._vimba_io import VimbaDriverIO


class VimbaDetector(StandardDetector, HasHints):
    """
    Ophyd-async implementation of an ADVimba Detector.
    """

    _controller: VimbaController
    _writer: adcore.ADHDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        self.drv = VimbaDriverIO(prefix + drv_suffix)
        self.hdf = adcore.NDFileHDFIO(prefix + hdf_suffix)

        super().__init__(
            VimbaController(self.drv),
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
