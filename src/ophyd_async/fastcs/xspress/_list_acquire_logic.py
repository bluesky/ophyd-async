from ophyd_async.core import DEFAULT_TIMEOUT, DetectorAcquireLogic, wait_for_value

from ._io import XspressDetectorIO
from ._xsp_list_odin_io import XspressOdinListIO


class XspressListAcquireLogic(DetectorAcquireLogic):
    def __init__(self, detector: XspressDetectorIO, list_io: XspressOdinListIO) -> None:
        self.detector = detector
        self.list_io = list_io

    async def start_acquiring(self):
        await self.detector.start_acquisition.trigger()

    async def wait_for_idle(self):
        # Not sure this is the best way of handling this.
        # I feel like I should try to make FastCS stop the driver parts once
        # the FPs have stopped writing, but for now this will sufice.
        await wait_for_value(self.list_io.writing, False, timeout=DEFAULT_TIMEOUT)

    async def ensure_stopped(self):
        await self.detector.stop_acquisition.trigger()
        await self.list_io.fp.stop_writing.trigger()
