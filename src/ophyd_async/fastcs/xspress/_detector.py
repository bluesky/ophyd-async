from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.fastcs.core import fastcs_connector

from ._arm_logic import XspressArmLogic
from ._io import XspressDetectorIO
from ._trigger_logic import XspressTriggerLogic
from ._xsp_odin_io import XspressOdinIO


class XspressDetector(StandardDetector):
    """Ophyd-async implementation of an Xspress Detector."""

    xspress: XspressDetectorIO
    od: XspressOdinIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        # Need to do this first so the type hints are filled in
        # drv_connector = fastcs_connector(prefix + "Xspress:")
        # self.xspress = XspressDetectorIO(connector=drv_connector)
        # drv_connector.create_children_from_annotations(self.xspress)
        # self.od = XspressOdinIO(connector=fastcs_connector(prefix + "OD:"))
        connector = fastcs_connector(prefix, self)

        self.add_detector_logics(
            XspressTriggerLogic(self.xspress),
            XspressArmLogic(self.xspress),
            # OdinDataLogic(
            #     path_provider=path_provider,
            #     odin=self.od,
            #     detector_bit_depth=None,
            # ),
        )
        super().__init__(name=name, connector=connector)
