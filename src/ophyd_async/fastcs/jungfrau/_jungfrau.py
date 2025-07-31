from ophyd_async.core import (
    PathProvider,
    StandardDetector,
)
from ophyd_async.epics.odin import Odin, OdinWriter
from ophyd_async.fastcs.jungfrau._controller import JungfrauController
from ophyd_async.fastcs.jungfrau._signals import JungfrauDriverIO


class Jungfrau(StandardDetector[JungfrauController, OdinWriter]):
    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str,
        hdf_suffix: str,
        odin_nodes: int,
        name="",
    ):
        # TODO find out which of these should have defaults
        self.drv = JungfrauDriverIO(prefix + drv_suffix)
        writer = OdinWriter(
            path_provider,
            Odin(prefix + hdf_suffix, nodes=odin_nodes),
            self.drv.bit_depth,
        )
        controller = JungfrauController(self.drv)
        super().__init__(controller, writer, name=name)
