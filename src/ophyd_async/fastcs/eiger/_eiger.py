from ophyd_async.core import (
    PathProvider,
    SignalR,
    StandardDetector,
)
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.odin import OdinHdfIO, OdinWriter

from ._eiger_controller import EigerController
from ._eiger_io import EigerDetectorIO, EigerMonitorIO, EigerStreamIO


class EigerDetector(StandardDetector):
    """Ophyd-async implementation of an Eiger Detector."""

    _controller: EigerController
    _writer: OdinWriter

    stale_parameters: SignalR[bool]
    monitor: EigerMonitorIO
    stream: EigerStreamIO
    detector: EigerDetectorIO
    od: OdinHdfIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        # Need to do this first so the type hints are filled in
        connector = fastcs_connector(self, prefix)

        super().__init__(
            EigerController(self.detector),
            OdinWriter(
                path_provider,
                self.od,
                self.detector.bit_depth_image,
            ),
            name=name,
            connector=connector,
        )
