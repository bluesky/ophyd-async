from ophyd_async.core import PathProvider, SignalR, StandardDetector
from ophyd_async.fastcs import odin
from ophyd_async.fastcs.core import fastcs_connector

from ._arm_logic import EigerArmLogic
from ._io import EigerDetectorIO, EigerMonitorIO, EigerStreamIO
from ._trigger_logic import EigerTriggerLogic


class EigerDetector(StandardDetector):
    """Ophyd-async implementation of an Eiger Detector."""

    stale_parameters: SignalR[bool]
    monitor: EigerMonitorIO
    stream: EigerStreamIO
    detector: EigerDetectorIO
    od: odin.OdinIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        # Need to do this first so the type hints are filled in
        connector = fastcs_connector(prefix, self)
        self.add_logics(
            EigerTriggerLogic(self.detector),
            EigerArmLogic(self.detector),
            odin.OdinDataLogic(
                path_provider=path_provider,
                odin=self.od,
                detector_bit_depth=self.detector.bit_depth_image,
            ),
        )
        super().__init__(name=name, connector=connector)
