from ophyd_async.core import Device, PathProvider, StandardDetector
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.jungfrau._controller import JungfrauController
from ophyd_async.fastcs.jungfrau._signals import JungfrauDriverIO
from ophyd_async.fastcs.odin import OdinWriter
from ophyd_async.fastcs.odin._io import FrameProcessorIO, MetaWriterIO


# TODO: Delete this duplicate device, once FastCS Jungfrau
# has top level 'detector' and 'odin', after which, follow
# EigerDetector as an example of correct structure
class OdinHdfIO(Device):
    fp: FrameProcessorIO
    mw: MetaWriterIO

    def __init__(self, uri: str, name: str = ""):
        super().__init__(name=name, connector=fastcs_connector(self, uri))


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
            self.odin,  # type: ignore
            self.drv.bit_depth,
        )
        controller = JungfrauController(self.drv)
        super().__init__(controller, writer, name=name)
