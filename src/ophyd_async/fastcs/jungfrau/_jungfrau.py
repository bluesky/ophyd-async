from ophyd_async.core import (
    PathProvider,
    StandardDetector,
    Device,
)
from ophyd_async.fastcs.jungfrau._controller import JungfrauController
from ophyd_async.fastcs.jungfrau._signals import JungfrauDriverIO
from ophyd_async.fastcs.jungfrau._writer import JunfrauCommissioningWriter
from ophyd_async.epics.core import epics_signal_r

class Jungfrau(StandardDetector[JungfrauController, JunfrauCommissioningWriter]):
    """Ophyd-async implementation of a Jungfrau Detector."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        self.drv = JungfrauDriverIO(prefix)
        writer = JunfrauCommissioningWriter(path_provider)
        controller = JungfrauController(self.drv)
        super().__init__(controller, writer, name=name)


