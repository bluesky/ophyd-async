from typing import Sequence

from ophyd_async.core import DirectoryProvider, SignalR, StandardDetector
from ophyd_async.epics.adcore import (ADBase, ADBaseShapeProvider, HDFWriter,
                                      NDFileHDF)

from ._sim_controller import SimController


class SimDetector(StandardDetector):
    _controller: SimController
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
            SimController(self.drv),
            HDFWriter(
                self.hdf,
                directory_provider,
                lambda: self.name,
                ADBaseShapeProvider(self.drv),
            ),
            config_sigs=config_sigs,
            name=name,
        )
