from typing import Sequence

from ophyd_async.core import DirectoryProvider, SignalR, StandardDetector

from ..areadetector.controllers import ADSimController
from ..areadetector.drivers import ADBase, ADBaseShapeProvider
from ..areadetector.writers import HDFWriter, NDFileHDF


class DemoADSimDetector(StandardDetector):
    _controller: ADSimController
    _writer: HDFWriter

    def __init__(
        self,
        drv: ADBase,
        hdf: NDFileHDF,
        directory_provider: DirectoryProvider,
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
    ):
        self.drv = drv
        self.hdf = hdf

        super().__init__(
            ADSimController(self.drv),
            HDFWriter(
                self.hdf,
                directory_provider,
                lambda: self.name,
                ADBaseShapeProvider(self.drv),
            ),
            config_sigs=config_sigs,
            name=name,
        )
