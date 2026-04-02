from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.fastcs import odin
from ophyd_async.fastcs.core import fastcs_connector

from ._arm_logic import XspressArmLogic
from ._io import XspressDetectorIO
from ._trigger_logic import XspressTriggerLogic


class XspressDetector(StandardDetector):
    """Ophyd-async implementation of an Xspress Detector."""

    # detector: XspressDetectorIO
    # od: odin.OdinIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str,
        hdf_suffix: str,
        name="",
    ):
        # Need to do this first so the type hints are filled in
        drv_connector = fastcs_connector(prefix + drv_suffix, self)
        self.detector = XspressDetectorIO(connector=drv_connector)
        drv_connector.create_children_from_annotations(self.detector)
        self.odin = odin.OdinIO(connector=fastcs_connector(prefix + hdf_suffix))

        self.add_detector_logics(
            XspressTriggerLogic(self.detector),
            XspressArmLogic(self.detector),
            odin.OdinDataLogic(
                path_provider=path_provider,
                odin=self.odin,
                detector_bit_depth=self.detector.bit_depth_image,
            ),
        )
        super().__init__(name=name)
