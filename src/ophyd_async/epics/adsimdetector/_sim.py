from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR, StandardDetector
from ophyd_async.epics import adcore

from ._sim_controller import SimController


class SimDetector(StandardDetector):
    _controller: SimController
    _writer: adcore.ADHDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
    ):
        self.drv = adcore.ADBaseIO(prefix + drv_suffix)
        self.hdf = adcore.NDFileHDFIO(prefix + hdf_suffix)

        super().__init__(
            SimController(self.drv),
            adcore.ADHDFWriter(
                self.hdf,
                path_provider,
                lambda: self.name,
                adcore.ADBaseDatasetDescriber(self.drv),
            ),
            config_sigs=(self.drv.acquire_period, self.drv.acquire_time, *config_sigs),
            name=name,
        )
