from functools import cached_property

from ophyd_async.core import (
    DetectorLogic,
    PathProvider,
    StandardDetector,
    soft_signal_rw,
)
from ophyd_async.fastcs import odin
from ophyd_async.fastcs.core import fastcs_connector

from ._acquire_logic import JungfrauAcquireLogic
from ._io import AcquisitionType, JungfrauDriverIO
from ._trigger_logic import JungfrauTriggerLogic


class JungfrauDetector(StandardDetector):
    """Ophyd-async implementation of a Jungfrau Detector."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str,
        hdf_suffix: str,
        name="",
    ):
        # Need to do this first so the bit depth signal exists for the TriggerLogic
        # once FastCS Jungfrau
        # has top level 'detector' and 'odin', after which, follow
        # EigerDetector as an example of correct structure
        drv_connector = fastcs_connector(prefix + drv_suffix)
        self.detector = JungfrauDriverIO(connector=drv_connector)
        drv_connector.create_children_from_annotations(self.detector)
        self.odin = odin.OdinIO(connector=fastcs_connector(prefix + hdf_suffix))
        self.acquisition_type = soft_signal_rw(
            AcquisitionType, AcquisitionType.STANDARD
        )
        self._logic = DetectorLogic(
            JungfrauTriggerLogic(self.detector, self.acquisition_type),
            JungfrauAcquireLogic(self.detector),
            odin.OdinDataLogic(
                path_provider=path_provider,
                odin=self.odin,
                detector_bit_depth=self.detector.bit_depth,
            ),
            publish_collect_methods=self._publish_collect_methods,
        )
        super().__init__(name=name)

    @cached_property
    def logic(self) -> DetectorLogic:
        return self._logic
