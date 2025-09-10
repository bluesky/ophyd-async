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


class JungfrauWriter(Device):
    def __init__(self,name="jungfrau_writer"):
        # self.frame_counter = epics_signal_rw(int, "BL24I-JUNGFRAU-META:FD:NumCapture", "BL24I-JUNGFRAU-META:FD:NumCaptured_RBV")
        # self.file_name = epics_signal_rw_rbv(str, "BL24I-JUNGFRAU-META:FD:FileName")
        # self.file_path = epics_signal_rw_rbv(str, "BL24I-JUNGFRAU-META:FD:FilePath")
        self.writer_ready = epics_signal_r(str, "BL24I-JUNGFRAU-META:FD:Ready_RBV")
        super().__init__(name)