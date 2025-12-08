from ophyd_async.core import (
    PathProvider,
    StandardDetector,
)
from ophyd_async.fastcs.jungfrau._controller import JungfrauController
from ophyd_async.fastcs.jungfrau._signals import JungfrauDriverIO
from ophyd_async.fastcs.odin import OdinHdfIO, OdinWriter


class Jungfrau(StandardDetector[JungfrauController, OdinWriter]):
    """Ophyd-async implementation of a Jungfrau Detector."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str,
        hdf_suffix: str,
        name="",
    ):
        self.drv = JungfrauDriverIO(prefix + drv_suffix)
        self.odin = OdinHdfIO(prefix + hdf_suffix)
        writer = OdinWriter(
            path_provider,
            self.odin,
            self.drv.bit_depth,
        )
        controller = JungfrauController(self.drv)
        super().__init__(controller, writer, name=name)
