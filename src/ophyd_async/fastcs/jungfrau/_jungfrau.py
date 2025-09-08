from ophyd_async.core import (
    PathProvider,
    StandardDetector,
)
from ophyd_async.fastcs.jungfrau._controller import JungfrauController
from ophyd_async.fastcs.jungfrau._signals import JungfrauDriverIO
from ophyd_async.fastcs.jungfrau._writer import JunfrauCommissioningWriter


class Jungfrau(StandardDetector[JungfrauController, JunfrauCommissioningWriter]):
    """Ophyd-async implementation of a Jungfrau Detector."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str,
        hdf_suffix: str,
        odin_nodes: int,
        name="",
    ):
        self.drv = JungfrauDriverIO(prefix + drv_suffix)
        writer = JunfrauCommissioningWriter()
        controller = JungfrauController(self.drv)
        super().__init__(controller, writer, name=name)
